import json, numpy as np, pandas as pd
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
CUT=[7,50]
def add_reg(df):
    """режимы ограничений (объявлены заранее): close — закрытие участка 10.07–07.08 (маршруты 7, 50); wkcut — выходные 7 и 50 с 06.09 по 30.11"""
    d=df.copy(); r=d.route.values; dt=d.date; dow=dt.dt.dayofweek.values; m57=np.isin(r,CUT); reg=np.full(len(d),'ok',dtype=object)
    reg[m57&(dt>='2025-07-10').values&(dt<='2025-08-07').values]='close'
    reg[m57&(dow>=5)&(dt>='2025-09-06').values&(dt<='2025-11-30').values]='wkcut'
    d['reg']=reg; return d
def wd_level(tr,win):
    d=tr.groupby(['route','date']).boardings.sum().reset_index(); d=d.merge(cal(d.date.unique())[['date','off']],on='date')
    d['v']=np.where(d.off==0,d.boardings,np.nan); w=d.pivot(index='date',columns='route',values='v')
    return w.rolling(win,center=True,min_periods=5).mean().reset_index().melt(id_vars='date',var_name='route',value_name='L').dropna()
def wd_level_fc(tr,days):
    x=tr[tr.date>tr.date.max()-pd.Timedelta(days=days)].groupby(['route','date']).boardings.sum().reset_index(); x=x.merge(cal(x.date.unique())[['date','off']],on='date')
    return x[x.off==0].groupby('route').boardings.mean()
def fit2(tr,p,seed=0,use_reg=True,wd=True):
    c=add_reg(build(tr))
    if wd: L=wd_level(tr,p['norm_win'])
    else: L=tr.groupby(['route','date']).boardings.sum().unstack(0).rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
    c=c.merge(L,on=['route','date']); c=c[c.L>0]; feats=FEATS+(['reg'] if use_reg else []); X=c[feats].copy(); X['route']=X.route.astype(int)
    m=CatBoostRegressor(loss_function='RMSE',iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],bootstrap_type='Bernoulli',subsample=p['ss'],cat_features=['route']+(['reg'] if use_reg else []),random_seed=seed,verbose=0,thread_count=10)
    m.fit(X,c.boardings/c.L,sample_weight=c.L); return m
def forecast2(tr,frb,p,fac,seeds=2,use_reg=True,wd=True,models=None):
    """frb — уже построенный build()+add_reg() кадр; fac — {месяц: множитель}"""
    origin=tr.date.max(); f=frb.date.dt.month.map(fac).values
    Lf=wd_level_fc(tr,p['lvl']) if wd else tr[tr.date>origin-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']
    feats=FEATS+(['reg'] if use_reg else []); X=frb[feats].copy(); X['route']=X.route.astype(int)
    models=models or [fit2(tr,p,s,use_reg,wd) for s in range(seeds)]
    cb=np.mean([np.clip(m.predict(X),0,None) for m in models],axis=0)*frb.route.map(Lf).values*f
    pf=frb.merge(prof(tr,p['weeks']),on=['route','dow','hour'],how='left').p.fillna(0).values*f
    w=np.where(frb.dow.values>=5,0.8,0.6)
    stale=np.isin(frb.route.values,CUT)&(frb.dow.values>=5)&(frb.reg.values=='ok')&(frb.date.values>=np.datetime64('2025-12-01'))   # профиль устарел (выходные вернулись)
    return np.where((frb.hol_wd.values==1)|stale,cb,w*cb+(1-w)*pf),cb,pf
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
