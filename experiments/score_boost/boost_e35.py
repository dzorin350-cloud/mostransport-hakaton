from boost2 import *
from catboost import CatBoostRegressor
B={f:fold_pred(f) for f in ORDER}
base={f:score(B[f][0]) for f in ORDER}
F3=['F4','F2','F1']
show('итоговая модель',base,F3)
print('=== 3. Чувствительность маршрута к сезонности города (β по месяцам 2025 до старта)')
def beta_route(tr):
    o=tr.date.max(); d=tr.groupby(['route',tr.date.dt.month]).agg(s=('boardings','sum'),n=('date','nunique')).reset_index()
    d=d[d.n>=20]; d['pd']=d.s/d.n*24/24
    M=o.month; out={}
    for r,g in d.groupby('route'):
        g=g.set_index('date')
        if M not in g.index: continue
        ms=[m for m in g.index if m!=M]
        if len(ms)<2: continue
        y=np.log(g.loc[ms,'pd']/g.loc[M,'pd']).values
        x=np.log(np.array([P.loc[2025,m]/P.loc[2025,M] for m in ms]))
        out[r]=float((x*y).sum()/(x*x).sum())
    return out
for lam in [0.3,0.5,1.0]:
    res={}
    for f in F3:
        b,tr=B[f]; bt=beta_route(tr); be=b.route.map(lambda r:1+lam*(bt.get(r,1)-1)).clip(0,2)
        b2=b.assign(p2=b.pred*(b.f**(be-1)))       # множитель маршрута = f^β вместо f
        res[f]=score(b2,'p2')
    show(f'   β маршрута, сжатие λ={lam}',res,F3)
b,tr=B['F1']; print('   β маршрутов (старт 31.08):',{k:round(v,2) for k,v in beta_route(tr).items()})
print('=== 5. Отдельная модель уровня: суточная сумма маршрута на горизонте h, много точек старта внутри истории')
_seas={}
def sr(oo,m):
    k=(oo.year,oo.month,m)
    if k not in _seas: _seas[k]=seas(oo,[m])[m] if m!=oo.month else 1.0
    return _seas[k]
def level_rows(D, origins, horizon_end, cal_x):
    rows=[]
    for oo in origins:
        hist=D[D.date<=oo]; L56=hist[hist.date>oo-pd.Timedelta(days=56)].groupby('route').tot.mean()
        L28=hist[hist.date>oo-pd.Timedelta(days=28)].groupby('route').tot.mean(); L7=hist[hist.date>oo-pd.Timedelta(days=7)].groupby('route').tot.mean()
        fut=D[(D.date>oo)&(D.date<=min(oo+pd.Timedelta(days=61),horizon_end))] if horizon_end is not None else None
        rows.append((oo,L56,L28,L7,fut))
    return rows
def make_X(t_dates, routes, oo, L56, L28, L7, cx):
    g=pd.MultiIndex.from_product([routes,t_dates],names=['route','date']).to_frame(index=False).merge(cx,on='date')
    g['h']=(g.date-oo).dt.days; g['L56']=g.route.map(L56); g['r28']=g.route.map(L28/L56); g['r7']=g.route.map(L7/L56)
    g['sr']=[sr(oo,m) for m in g.date.dt.month]; g['dl0']=float(cx.loc[cx.date==oo,'daylen'].iloc[0]) if (cx.date==oo).any() else np.nan
    g['ddl']=g.daylen-g.dl0; return g
FE=['route','h','dow','off','hol_wd','pre','post','daylen','ddl','sr','r28','r7']
def level_model(f, feats=FE, seeds=2):
    b,tr=B[f]; o=tr.date.max()
    D=tr.groupby(['route','date']).boardings.sum().rename('tot').reset_index()
    alld=pd.date_range(tr.date.min(), b.date.max()); cx=build_x(alld)
    origins=pd.date_range(tr.date.min()+pd.Timedelta(days=56), o-pd.Timedelta(days=7), freq='7D')
    parts=[]
    for oo in origins:
        hist=D[D.date<=oo]; L56=hist[hist.date>oo-pd.Timedelta(days=56)].groupby('route').tot.mean()
        L28=hist[hist.date>oo-pd.Timedelta(days=28)].groupby('route').tot.mean(); L7=hist[hist.date>oo-pd.Timedelta(days=7)].groupby('route').tot.mean()
        td=pd.date_range(oo+pd.Timedelta(days=1), min(oo+pd.Timedelta(days=61),o))
        g=make_X(td, sorted(D.route.unique()), oo, L56, L28, L7, cx).merge(D,on=['route','date'])
        g['y']=g.tot/g.L56; parts.append(g)
    T=pd.concat(parts)
    L56=D[D.date>o-pd.Timedelta(days=56)].groupby('route').tot.mean(); L28=D[D.date>o-pd.Timedelta(days=28)].groupby('route').tot.mean(); L7=D[D.date>o-pd.Timedelta(days=7)].groupby('route').tot.mean()
    Q=make_X(pd.date_range(b.date.min(),b.date.max()), sorted(D.route.unique()), o, L56, L28, L7, cx)
    ps=[]
    for s in range(seeds):
        m=CatBoostRegressor(loss_function='RMSE',iterations=600,depth=6,learning_rate=0.05,l2_leaf_reg=5,cat_features=['route'],random_seed=s,verbose=0,thread_count=10)
        X=T[feats].copy(); X['route']=X.route.astype(int); m.fit(X,T.y,sample_weight=T.L56)
        Xq=Q[feats].copy(); Xq['route']=Xq.route.astype(int); ps.append(m.predict(Xq))
    Q['tot_hat']=np.mean(ps,axis=0)*Q.L56
    return Q[['route','date','tot_hat']], len(origins), len(T)
LM={}
for f in F3:
    LM[f]=level_model(f); print(f'   {f}: точек старта {LM[f][1]}, обучающих строк {LM[f][2]}',flush=True)
def apply_level(f, a, Qd):
    b=B[f][0].merge(Qd,on=['route','date'],how='left')
    day=b.groupby(['route','date']).pred.transform('sum')
    k=(b.tot_hat/day.replace(0,np.nan)).fillna(1)
    b['p2']=b.pred*(k**a); return score(b,'p2')
for a in [0.3,0.5,1.0]:
    show(f'   модель уровня, вес α={a} (сумма дня = база^(1−α)·модель^α)',{f:apply_level(f,a,LM[f][0]) for f in F3},F3)
FE2=[x for x in FE if x not in ('sr',)]
LM2={f:level_model(f,FE2) for f in F3}
for a in [0.5,1.0]:
    show(f'   модель уровня без городской сезонности, α={a}',{f:apply_level(f,a,LM2[f][0]) for f in F3},F3)
