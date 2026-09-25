import json, pipe
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
def fit_cb2(tr,p,seed=0):
    c=build(tr); dd=tr.groupby(['route','date']).boardings.sum().unstack(0)
    L=dd.rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
    c=c.merge(L,on=['route','date']); c=c[c.L>0]
    X=c[FEATS].copy(); X['route']=X.route.astype(int); w=c.L.values
    if p.get('tau'): w=w*np.exp(-(tr.date.max()-c.date).dt.days.values/p['tau'])
    m=CatBoostRegressor(loss_function='RMSE',iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],bootstrap_type='Bernoulli',subsample=p['ss'],cat_features=['route'],random_seed=seed,verbose=0,thread_count=10)
    m.fit(X,c.boardings/c.L,sample_weight=w); return m
pipe.fit_cb=fit_cb2
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
rows=[]
for tau in [None,30,60,120]:
    r=[]
    for fold in ['F3','F4','F2','F1']:
        o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]
        fac=seas(o,sorted(te.date.dt.month.unique())); out,cb,pf=pipe.forecast(tr,te[['route','date','hour']],{**best,'tau':tau},seeds=2,fac=fac)
        r.append(round(1-wape(te.boardings.values,out),4))
    rows.append((str(tau),)+tuple(r)+(round(float(np.mean(r)),4),)); print(rows[-1],flush=True)
print(pd.DataFrame(rows,columns=['tau (дни, None=без затухания)','F3 мар–апр','F4 май–июнь','F2 июл–авг','F1 сен–окт','среднее']).to_string(index=False))
