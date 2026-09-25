from clean import *
import model
from year_city import S
CAL={}
for y in (2022,2023,2024,2025):
    s=open(f'cal_{y}.txt').read().strip(); d=pd.date_range(f'{y}-01-01',f'{y}-12-31'); CAL.update(dict(zip(d,s)))
for d,c in CAL.items():
    if c=='1' and d.dayofweek<5: model.DAYOFF.add(d)          # праздники 2022–2024 в общий календарь
def synth(tr,years=(2022,2023,2024)):
    """синтетическая почасовая история маршрутов; шаблоны — только из tr (реальные очищенные данные <= origin)"""
    o=tr.date.max(); t=tr[tr.date>='2025-01-09'].copy(); t['dt']=dtype(t.date); t['m']=t.date.dt.month
    day=t.groupby(['route','date','dt','m']).boardings.sum().reset_index()
    lvl=day.groupby(['route','m','dt']).boardings.mean()                      # уровень суток по типу дня и месяцу
    tot=t.groupby(['route','date']).boardings.transform('sum'); t['sh']=t.boardings/tot.replace(0,np.nan)
    shp=t.groupby(['route','dt','hour']).sh.mean()
    avail=sorted(day.m.unique()); last=o.month if o.day>=20 else o.month-1
    out=[]
    dates=pd.date_range(f'{years[0]}-01-01',f'{years[-1]}-12-31'); dts=dtype(pd.Series(dates))
    for r in ROUTES:
        for d,dt in zip(dates,dts):
            mt=d.month if (d.month in avail and d.month<=last) else last       # месяц-шаблон
            dt2=dt if (r,mt,dt) in lvl.index else ('sun' if dt=='hol' else dt)
            if (r,mt,dt2) not in lvl.index: continue
            k=S[pd.Period(d,'M')]/S[pd.Period(f'2025-{mt:02d}','M')]
            L=lvl[(r,mt,dt2)]*k; sh=shp.loc[(r,dt2)].reindex(range(24)).fillna(0).values
            out.append(pd.DataFrame({'route':r,'date':d,'hour':range(24),'boardings':L*sh}))
    return pd.concat(out,ignore_index=True)
def fit_cb_syn(real,syn,p,seed=0,ws=0.3):
    g=pd.concat([syn.assign(ws=ws),real.assign(ws=1.0)],ignore_index=True)
    c=build(g); dd=g.groupby(['route','date']).boardings.sum().unstack(0)
    L=dd.rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
    c=c.merge(L,on=['route','date']); c=c[c.L>0]; X=c[FEATS].copy(); X['route']=X.route.astype(int)
    m=CatBoostRegressor(loss_function='RMSE',iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],bootstrap_type='Bernoulli',subsample=p['ss'],cat_features=['route'],random_seed=seed,verbose=0,thread_count=10)
    m.fit(X,c.boardings/c.L,sample_weight=c.L*c.ws); return m
def forecast_syn(real,syn,fr,p,fac,seeds=2,ws=0.3):
    origin=real.date.max(); frb=build(fr); f=frb.date.dt.month.map(fac).values
    L=real[real.date>origin-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']
    X=frb[FEATS].copy(); X['route']=X.route.astype(int)
    cb=np.mean([np.clip(fit_cb_syn(real,syn,p,s,ws).predict(X),0,None) for s in range(seeds)],axis=0)*frb.route.map(L).values*f
    pf=frb.merge(prof(real,p['weeks']),on=['route','dow','hour'],how='left').p.fillna(0).values*f
    w=np.where(frb.dow.values>=5,0.8,0.6); return np.where(frb.hol_wd.values==1,cb,w*cb+(1-w)*pf)
if __name__=='__main__':
    rows=[]
    for fold in ['F4','F2','F1']:
        o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
        fac=seas(o,sorted(te.date.dt.month.unique())); c=clean_grid(tr,1.5,protect_weeks=0)[0]; sy=synth(c)
        b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
        _,cb,pf=forecast(c,fr,best,seeds=2,fac=fac); r=[fold,round(1-wape(y,np.where(hol,cb,w*cb+(1-w)*pf)),4)]
        for ws in (0.1,0.3,1.0): r.append(round(1-wape(y,forecast_syn(c,sy,fr,best,fac,2,ws)),4))
        rows.append(r); print(r,len(sy),flush=True)
    df=pd.DataFrame(rows,columns=['период','v7','v7+синт (вес 0,1)','вес 0,3','вес 1,0']); print(df.to_string(index=False)); print(df.iloc[:,1:].mean().round(4).to_dict())
