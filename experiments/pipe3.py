from pipe2 import *
from model import DAYOFF
def add_reg2(df):
    d=df.copy(); r=d.route.values; dt=d.date; m57=np.isin(r,CUT); reg=np.full(len(d),'ok',dtype=object)
    reg[m57&(dt>='2025-07-10').values&(dt<='2025-08-07').values]='close'
    reg[m57&(dt>='2025-09-06').values&(dt<='2025-11-30').values]='wkcut'     # весь период ограничений, все дни
    d['reg']=reg; return d
def r_pre(tr):
    x=tr[(tr.date>='2025-01-09')&(tr.date<='2025-07-09')].groupby(['route','date']).boardings.sum().reset_index(); x=x[~x.date.isin(DAYOFF)]; x['dow']=x.date.dt.dayofweek
    return x[x.dow>=5].groupby('route').boardings.mean()/x[x.dow<5].groupby('route').boardings.mean()
def fit3(tr,p,seed=0):
    c=add_reg2(build(tr)); L=tr.groupby(['route','date']).boardings.sum().unstack(0).rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
    c=c.merge(L,on=['route','date']); c=c[c.L>0]; X=c[FEATS+['reg']].copy(); X['route']=X.route.astype(int)
    m=CatBoostRegressor(loss_function='RMSE',iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],bootstrap_type='Bernoulli',subsample=p['ss'],cat_features=['route','reg'],random_seed=seed,verbose=0,thread_count=10)
    m.fit(X,c.boardings/c.L,sample_weight=c.L); return m
def forecast3(tr,frb,p,fac,seeds=2,models=None):
    origin=tr.date.max(); f=frb.date.dt.month.map(fac).values
    La=tr[tr.date>origin-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']; Lw=wd_level_fc(tr,p['lvl']); rp=r_pre(tr)
    Lrow=frb.route.map(La).values.astype(float)
    dec=np.isin(frb.route.values,CUT)&(frb.reg.values=='ok')&(frb.date.values>=np.datetime64('2025-12-01'))
    Lrow=np.where(dec,frb.route.map(Lw*(5+2*rp)/7).values,Lrow)      # декабрь: уровень при возвращённых выходных
    X=frb[FEATS+['reg']].copy(); X['route']=X.route.astype(int); models=models or [fit3(tr,p,s) for s in range(seeds)]
    cb=np.mean([np.clip(m.predict(X),0,None) for m in models],axis=0)*Lrow*f
    pf=frb.merge(prof(tr,p['weeks']),on=['route','dow','hour'],how='left').p.fillna(0).values*f
    w=np.where(frb.dow.values>=5,0.8,0.6); stale=dec&(frb.dow.values>=5)
    return np.where((frb.hol_wd.values==1)|stale,cb,w*cb+(1-w)*pf),cb,pf
