import json, os
from pipe import *
from model import DAYOFF
best=dict(DEF); best.update(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'best_params_final.json')))['params'])
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
def route_beta(tr):
    """чувствительность маршрута к сезонности города: log(месяц маршрута / месяц старта) ≈ β·log(то же по городу),
    по полным месяцам истории (≥ 20 дней); маршрут без двух таких месяцев — без поправки"""
    o=tr.date.max(); O=pd.Period(o,'M')
    d=tr.assign(per=tr.date.dt.to_period('M')).groupby(['route','per']).agg(s=('boardings','sum'),n=('date','nunique')).reset_index()
    d=d[d.n>=20]; d['pd']=d.s/d.n; out={}
    for r,g in d.groupby('route'):
        g=g.set_index('per')
        if O not in g.index: continue
        ps=[x for x in g.index if x!=O and x.year in P.index and not np.isnan(P.loc[x.year,x.month])]
        if len(ps)<2: continue
        y=np.log(g.loc[ps,'pd']/g.loc[O,'pd']).values
        x=np.log(np.array([P.loc[q.year,q.month]/P.loc[O.year,O.month] for q in ps]))
        out[r]=float((x*y).sum()/(x*x).sum())
    return out
def route_factor(beta,r,f,lam):
    """множитель маршрута к городской сезонности f: f^(β'−1), β' = 1 + λ(β − 1) (сжатие к городу)"""
    return f**(lam*(beta.get(r,1.0)-1))
def dtype(dates):
    dow=dates.dt.dayofweek; return np.where(dates.isin(DAYOFF),'hol',np.where(dow<5,'wd',np.where(dow==5,'sat','sun')))
def clean_grid(tr,thr=1.3,wk_thr=0.15,protect_weeks=4):
    """возвращает очищенную копию tr: аномальные маршруто-дни заменены ожидаемым значением"""
    d=tr.groupby(['route','date']).boardings.sum().reset_index(); d['dt']=dtype(d.date)
    end=tr.date.max(); prot=end-pd.Timedelta(weeks=protect_weeks)
    mask=pd.Series(False,index=d.index)
    # 1) многонедельные сдвиги: недельная доля маршрута в будни вне ±wk_thr
    w=d[d.dt=='wd'].copy(); w['wk']=w.date.dt.to_period('W').dt.start_time
    sh=w.groupby(['wk','route']).boardings.sum().unstack(); sh=sh.div(sh.sum(1),axis=0); rel=sh/sh.median()
    badwk=rel.stack(); badwk=badwk[(badwk-1).abs()>wk_thr].reset_index()[['wk','route']]
    d['wk']=d.date.dt.to_period('W').dt.start_time
    mw=d.merge(badwk.assign(b=1),on=['wk','route'],how='left').b.fillna(0).values==1
    mask|=pd.Series(mw,index=d.index)
    # 2) разовые дни: откл. от медианы того же типа дня (±5 недель) > thr раз
    d['exp']=np.nan
    for it in range(2):
        for (r,t),g in d[d.dt!='hol'].groupby(['route','dt']):
            v=g.boardings.where(~mask[g.index]); e=v.rolling(11,center=True,min_periods=3).median().ffill().bfill(); d.loc[g.index,'exp']=e
        rr=d.boardings/d.exp; mask|=((rr>thr)|(rr<1/thr))&(d.dt!='hol')
    mask&=(d.date<prot)                      # свежие недели не трогаем
    d['m']=mask
    # замена: exp × средняя почасовая доля (route, dt, hour) по чистым дням
    t=tr.merge(d[['route','date','dt','m','exp']],on=['route','date'])
    tot=t.groupby(['route','date']).boardings.transform('sum'); t['sh']=t.boardings/tot.replace(0,np.nan)
    shp=t[~t.m].groupby(['route','dt','hour']).sh.mean().rename('shp').reset_index()
    t=t.merge(shp,on=['route','dt','hour'],how='left')
    t['boardings']=np.where(t.m,t.exp*t.shp.fillna(0),t.boardings)
    return t[['route','date','hour','boardings']].sort_values(['route','date','hour']).reset_index(drop=True), d
if __name__=='__main__':
    rows=[]
    for fold in ['F3','F4','F2','F1']:
        o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
        fac=seas(o,sorted(te.date.dt.month.unique())); b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
        r=[fold]
        for nm,trx in [('как есть',tr)]+[(f'очистка thr={th}',clean_grid(tr,th)[0]) for th in [1.3,1.5]]:
            _,cb,pf=forecast(trx,fr,best,seeds=2,fac=fac); p=np.where(hol,cb,w*cb+(1-w)*pf); r.append(round(1-wape(y,p),4))
        _,dd=clean_grid(tr,1.3); r.append(int(dd.m.sum())); rows.append(r); print(r,flush=True)
    df=pd.DataFrame(rows,columns=['период','как есть (v4)','очистка 1.3','очистка 1.5','помечено маршруто-дней']); print(df.to_string(index=False)); print("среднее:",df.iloc[:,1:4].mean().round(4).to_dict())
