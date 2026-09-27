import hashlib, numpy as np, pandas as pd
from catboost import CatBoostRegressor
from clean import clean_grid, G, seas
from harness import build_x
from boost_lib35 import beta_route, make_X, sr
P0="/Users/denis/Documents/Данные хакатон Мос Транспорт/"
A=pd.read_csv(P0+'submission_candidate_daylen_prof4med.csv',sep=';'); A['d']=pd.to_datetime(A.date)
tr,_=clean_grid(G.copy(),1.5,protect_weeks=0); o=tr.date.max()
bt=beta_route(tr); fac=seas(o,[11,12])
k=np.array([fac[m]**(0.5*(bt.get(r,1)-1)) if r!=5 else 1.0 for r,m in zip(A.route,A.d.dt.month)])
C1=A.assign(prediction=(A.prediction*k).round(1))
# модель уровня на всей истории
D=tr.groupby(['route','date']).boardings.sum().rename('tot').reset_index()
alld=pd.date_range(tr.date.min(),'2025-12-31'); cx=build_x(alld)
FE=['route','h','dow','off','hol_wd','pre','post','daylen','ddl','sr','r28','r7']
parts=[]
for oo in pd.date_range(tr.date.min()+pd.Timedelta(days=56), o-pd.Timedelta(days=7), freq='7D'):
    hist=D[D.date<=oo]; L56=hist[hist.date>oo-pd.Timedelta(days=56)].groupby('route').tot.mean()
    L28=hist[hist.date>oo-pd.Timedelta(days=28)].groupby('route').tot.mean(); L7=hist[hist.date>oo-pd.Timedelta(days=7)].groupby('route').tot.mean()
    g=make_X(pd.date_range(oo+pd.Timedelta(days=1),min(oo+pd.Timedelta(days=61),o)),sorted(D.route.unique()),oo,L56,L28,L7,cx).merge(D,on=['route','date']); g['y']=g.tot/g.L56; parts.append(g)
T=pd.concat(parts)
L56=D[D.date>o-pd.Timedelta(days=56)].groupby('route').tot.mean(); L28=D[D.date>o-pd.Timedelta(days=28)].groupby('route').tot.mean(); L7=D[D.date>o-pd.Timedelta(days=7)].groupby('route').tot.mean()
Q=make_X(pd.date_range('2025-11-01','2025-12-31'),sorted(D.route.unique()),o,L56,L28,L7,cx)
ps=[]
for s in range(2):
    m=CatBoostRegressor(loss_function='RMSE',iterations=600,depth=6,learning_rate=0.05,l2_leaf_reg=5,cat_features=['route'],random_seed=s,verbose=0,thread_count=10)
    X=T[FE].copy(); X['route']=X.route.astype(int); m.fit(X,T.y,sample_weight=T.L56); Xq=Q[FE].copy(); Xq['route']=Xq.route.astype(int); ps.append(m.predict(Xq))
Q['tot_hat']=np.mean(ps,axis=0)*Q.L56
x=C1.assign(p=C1.prediction*1.0, d=A.d).merge(Q[['route','date','tot_hat']].rename(columns={'date':'d'}),on=['route','d'],how='left')
day=x.groupby(['route','d']).p.transform('sum'); kk=(x.tot_hat/day.replace(0,np.nan)).fillna(1)**0.2
C2=C1.assign(prediction=(x.p*kk).round(1).values)
for nm,df in [('C1_route_beta',C1),('C2_route_beta_levelmodel',C2)]:
    out=P0+f'submission_candidate_{nm}.csv'; df[['route','date','hour','prediction']].to_csv(out,sep=';',index=False)
    assert len(df)==14640 and df.prediction.notna().all() and (df.prediction>=0).all()
    d=(df.prediction-A.prediction).abs().sum()/A.prediction.sum()
    mo=df.groupby(A.d.dt.month).prediction.sum()/A.groupby(A.d.dt.month).prediction.sum()-1
    print(nm, f'| от A: Σ|Δ|/Σ {d:.2%} | ноябрь {mo[11]:+.2%} декабрь {mo[12]:+.2%} | md5',hashlib.md5(open(out,'rb').read()).hexdigest()[:8])
