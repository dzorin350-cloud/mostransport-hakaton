import json
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
CALF=['off','hol_wd','pre','post']
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
def cbm(loss,it,dep,lr,l2,seed,boot=None):
    return CatBoostRegressor(loss_function=loss,iterations=it,depth=dep,learning_rate=lr,l2_leaf_reg=l2,cat_features=['route'],random_seed=seed,verbose=0,thread_count=10)
def hier(tr,fr,p,seeds=2,dloss='RMSE',sloss='RMSE'):
    dd=tr.groupby(['route','date']).boardings.sum().rename('D').reset_index()
    wide=tr.groupby(['route','date']).boardings.sum().unstack(0)
    L=wide.rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
    d=dd.merge(L,on=['route','date']).merge(cal(dd.date.unique()),on='date'); d=d[d.L>0]
    Xd=d[['route','dow']+CALF].copy(); Xd['route']=Xd.route.astype(int)
    trb=build(tr).merge(dd,on=['route','date']); trb=trb[trb.D>0]; trb['s']=trb.boardings/trb.D
    Xs=trb[['route','hour','dow']+CALF].copy(); Xs['route']=Xs.route.astype(int)
    frb=build(fr); ud=frb[['route','date','dow']+CALF].drop_duplicates(); Xu=ud[['route','dow']+CALF].copy(); Xu['route']=Xu.route.astype(int)
    Xf=frb[['route','hour','dow']+CALF].copy(); Xf['route']=Xf.route.astype(int)
    dp=np.mean([np.clip(cbm(dloss,600,6,0.05,5,s).fit(Xd,d.D/d.L,sample_weight=d.L).predict(Xu),0,None) for s in range(seeds)],axis=0)
    sp=np.mean([np.clip(cbm(sloss,p['iters'],p['depth'],p['lr'],p['l2'],s).fit(Xs,trb.s,sample_weight=trb.D).predict(Xf),0,None) for s in range(seeds)],axis=0)
    ud=ud.assign(dp=dp); frb=frb.assign(sp=sp).merge(ud[['route','date','dp']],on=['route','date'],how='left')
    frb['sp']=frb.sp/frb.groupby(['route','date']).sp.transform('sum')
    Lf=tr[tr.date>tr.date.max()-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']
    return (frb.dp*frb.sp*frb.route.map(Lf)).values     # без сезонного множителя
res=[]
for fold in ['F1','F4','F2','F3']:
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
    fac=seas(o,sorted(te.date.dt.month.unique())); f=te.date.dt.month.map(fac).values
    _,cbf,pf=forecast(tr,fr,best,seeds=2,fac=fac)                # плоская CB и профиль (с множителем)
    h=hier(tr,fr,best)*f; av=(cbf+h)/2; w=best['w']; hol=build(fr).hol_wd.values==1
    bl=lambda c:np.where(hol,c,w*c+(1-w)*pf)
    sc=lambda p:round(1-wape(y,p),4)
    r=dict(период=fold,плоская_CB=sc(cbf),иерарх_CB=sc(h),среднее_CB=sc(av),профиль=sc(pf),смесь_плоская=sc(bl(cbf)),смесь_иерарх=sc(bl(h)),смесь_среднее=sc(bl(av)))
    res.append(r); print(r,flush=True)
df=pd.DataFrame(res); print(df.to_string(index=False)); print("среднее:",df.drop(columns='период').mean().round(4).to_dict()); df.to_csv('hier_result.csv',index=False)
