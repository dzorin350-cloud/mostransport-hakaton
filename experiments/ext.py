import json
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
W=pd.read_csv(D+'external/weather_daily_2022_2025-10.csv',index_col=0,parse_dates=True); W.index.name='date'
Wf=W[['temperature_2m_mean','precipitation_sum','snowfall_sum']].copy(); Wf.columns=['t','pr','sn']
def clim(dates,years=(2022,2023,2024)):
    out=[]
    for d in dates:
        v=[Wf.loc[pd.Timestamp(year=y,month=d.month,day=d.day)-pd.Timedelta(days=3):pd.Timestamp(year=y,month=d.month,day=d.day)+pd.Timedelta(days=3)].mean() for y in years]
        out.append(pd.concat(v,axis=1).mean(axis=1))
    return pd.DataFrame(out,index=pd.DatetimeIndex(dates,name='date'))
BASE=['route','hour','dow','off','hol_wd','pre','post']
def run(feats,wmode,fold='F1',seeds=3,p=best):
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values
    fr=build(te[['route','date','hour']]); trb=build(tr)
    use_w=any(f in feats for f in ['t','pr','sn'])
    if use_w:
        trb=trb.merge(Wf.reset_index(),on='date')
        wte=(Wf.loc[te.date.unique()] if wmode=='actual' else clim(sorted(te.date.unique()))).reset_index()
        fr=fr.merge(wte,on='date')
    dd=tr.groupby(['route','date']).boardings.sum().unstack(0)
    L=dd.rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index(); c=trb.merge(L,on=['route','date']); c=c[c.L>0]
    X=c[feats].copy(); X['route']=X.route.astype(int); Xt=fr[feats].copy(); Xt['route']=Xt.route.astype(int)
    mm=sorted(te.date.dt.month.unique()); yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+mm].isna().any()]; fac={m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in mm}
    Lf=tr[tr.date>o-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']
    f=fr.date.dt.month.map(fac).values
    preds=[]
    for sd in range(seeds):
        m=CatBoostRegressor(loss_function='RMSE',iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],bootstrap_type='Bernoulli',subsample=p['ss'],cat_features=['route'],random_seed=sd,verbose=0,thread_count=10)
        m.fit(X,c.boardings/c.L,sample_weight=c.L); preds.append(np.clip(m.predict(Xt),0,None))
    cb=np.mean(preds,axis=0)*fr.route.map(Lf).values*f
    pf=fr.merge(prof(tr,p['weeks']),on=['route','dow','hour'],how='left').p.fillna(0).values*f
    bl=np.where(fr.hol_wd.values==1,cb,p['w']*cb+(1-p['w'])*pf)
    return 1-wape(y,bl),1-wape(y,cb)
CAL=['off','hol_wd','pre','post']
tests=[('A. базовый: маршрут, час, день недели, календарь',BASE,None),
       ('B. без календаря (только маршрут, час, день недели)',['route','hour','dow'],None),
       ('C. + погода (климатическая норма в прогнозе)',BASE+['t','pr','sn'],'clim'),
       ('D. + погода фактическая (только верхняя оценка, в финале недоступна)',BASE+['t','pr','sn'],'actual')]
print("АБЛЯЦИЯ на валидации (train до 31.08 → test сен–окт), сезонный множитель уровня включён, 3 seed")
rows=[]
for nm,ft,wm in tests:
    r=run(ft,wm); rows.append((nm,round(r[0],4),round(r[1],4))); print(rows[-1],flush=True)
pd.DataFrame(rows,columns=['вариант','смесь','CatBoost один']).to_csv('ablation1.csv',index=False)
