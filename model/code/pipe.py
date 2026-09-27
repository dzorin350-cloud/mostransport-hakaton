import pandas as pd, numpy as np, calendar, warnings
warnings.filterwarnings('ignore')
from catboost import CatBoostRegressor
from model import G, ROUTES, cal, build, wape, D, FEATS
C=pd.read_csv(D+'ridership_allowed.csv'); C=C[C.type=='Трамвай'].copy()
C['pd_']=C.pax/[calendar.monthrange(y,m)[1] for y,m in zip(C.year,C.m)]
P=C.pivot(index='year',columns='m',values='pd_')
def factors(origin,months):
    """сезонный множитель уровня: оценка суток месяца m / сутки базового месяца; только данные города до origin"""
    Y=origin.year; base=origin.month
    yrs=[y for y in P.index if y<Y and y!=2020 and not P.loc[y,[base]+list(months)].isna().any()]
    g=np.mean([P.loc[Y,k]/P.loc[Y-1,k] for k in [base-2,base-1,base] if k>=1])
    return {m:((P.loc[Y,base]*np.mean([P.loc[y,m]/P.loc[y,base] for y in yrs]))+(P.loc[Y-1,m]*g))/2/P.loc[Y,base] for m in months}
DEF=dict(loss='RMSE',iters=600,depth=6,lr=0.06,l2=3.0,rs=1.0,boot='MVS',bt=1.0,ss=0.8,vp=1.5,norm_win=28,lvl=28,weeks=4,w=0.5)
def fit_cb(tr,p,seed=0,feats=None):
    c=build(tr); dd=tr.groupby(['route','date']).boardings.sum().unstack(0)
    L=dd.rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
    c=c.merge(L,on=['route','date']); c=c[c.L>0]
    X=c[feats or FEATS].copy(); X['route']=X.route.astype(int)
    loss=f"Tweedie:variance_power={p['vp']}" if p['loss']=='Tweedie' else p['loss']
    kw=dict(loss_function=loss,iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],cat_features=['route'],random_seed=seed,verbose=0,thread_count=10)
    if p['boot']=='Bayesian': kw.update(bootstrap_type='Bayesian',bagging_temperature=p['bt'])
    elif p['boot']=='Bernoulli': kw.update(bootstrap_type='Bernoulli',subsample=p['ss'])
    m=CatBoostRegressor(**kw); m.fit(X,c.boardings/c.L,sample_weight=c.L); return m
def prof(tr,weeks,agg='mean'):
    t=build(tr[tr.date>tr.date.max()-pd.Timedelta(weeks=weeks)]); t=t[t.hol_wd==0]
    return t.groupby(['route','dow','hour']).boardings.agg(agg).rename('p').reset_index()
def forecast(tr,fr,p,seeds=1,use_fac=True,fac=None):
    fr=build(fr); origin=tr.date.max(); months=sorted(fr.date.dt.month.unique())
    fac=fac or (factors(origin,months) if use_fac else {m:1.0 for m in months}); f=fr.date.dt.month.map(fac).values
    L=tr[tr.date>origin-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']
    X=fr[FEATS].copy(); X['route']=X.route.astype(int)
    cb=np.mean([np.clip(fit_cb(tr,p,s).predict(X),0,None) for s in range(seeds)],axis=0)*fr.route.map(L).values*f
    pf=fr.merge(prof(tr,p['weeks']),on=['route','dow','hour'],how='left').p.fillna(0).values*f
    return np.where(fr.hol_wd.values==1,cb,p['w']*cb+(1-p['w'])*pf),cb,pf
FOLDS={'F1':('2025-08-31','2025-09-01','2025-10-31'),'F2':('2025-06-30','2025-07-01','2025-08-31'),'F3':('2025-02-28','2025-03-01','2025-04-30'),'F4':('2025-04-30','2025-05-01','2025-06-30')}
def score(p,fold,seeds=1,use_fac=True):
    o,s,e=FOLDS[fold]; tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]
    out,cb,pf=forecast(tr,te[['route','date','hour']],p,seeds,use_fac); y=te.boardings.values
    return 1-wape(y,out),1-wape(y,cb),1-wape(y,pf)
