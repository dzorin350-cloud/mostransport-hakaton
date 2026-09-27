"""Кандидат в сабмит: ансамбль формы дня (база + световой день) и профиль. Конфигурация через аргументы."""
import sys, hashlib
from harness import *
from clean import ROUTES
variant=sys.argv[1]; out=sys.argv[2]
cfg={'base':dict(vars=[BASE_FEATS],weeks=2,agg='mean'),
     'daylen_prof4med':dict(vars=[BASE_FEATS,BASE_FEATS+['daylen']],weeks=4,agg='median'),
     'daylen':dict(vars=[BASE_FEATS,BASE_FEATS+['daylen']],weeks=2,agg='mean')}[variant]
p=dict(best)
tr,_=clean_grid(G.copy(),1.5,protect_weeks=0); origin=tr.date.max(); assert origin==pd.Timestamp('2025-10-31')
fac=seas(origin,[11,12]); days=pd.date_range('2025-11-01','2025-12-31')
F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
L=tr[tr.date>origin-pd.Timedelta(days=p['lvl'])].groupby('route').boardings.sum()/p['lvl']
ctr=build_x(tr.date.unique()); a=tr.merge(ctr,on='date')
dd=tr.groupby(['route','date']).boardings.sum().unstack(0)
Ln=dd.rolling(p['norm_win'],center=True,min_periods=10).mean().stack().rename('L').reset_index()
a=a.merge(Ln,on=['route','date']); a=a[a.L>0]
models=[]
for fs in cfg['vars']:
    for s in range(5):
        X=a[fs].copy(); X['route']=X.route.astype(int)
        m=CatBoostRegressor(loss_function=p['loss'],iterations=p['iters'],depth=p['depth'],learning_rate=p['lr'],l2_leaf_reg=p['l2'],random_strength=p['rs'],
            cat_features=['route'],random_seed=s,verbose=0,thread_count=10,bootstrap_type='Bernoulli',subsample=p['ss'])
        m.fit(X,a.boardings/a.L,sample_weight=a.L); models.append((fs,m))
t=tr[tr.date>origin-pd.Timedelta(weeks=cfg['weeks'])].merge(cal(tr.date.unique()),on='date'); t=t[t.hol_wd==0]
PR=t.groupby(['route','dow','hour']).boardings.agg(cfg['agg']).rename('p').reset_index()
def pred(frb):
    f=frb.date.dt.month.map(fac).values
    per_var=[]
    for fs in cfg['vars']:
        ms=[m for v,m in models if v==fs]; X=frb[fs].copy(); X['route']=X.route.astype(int)
        per_var.append(np.mean([np.clip(m.predict(X),0,None) for m in ms],axis=0))
    cb=np.mean(per_var,axis=0)*frb.route.map(L).values*f
    pf=frb.merge(PR,on=['route','dow','hour'],how='left').p.fillna(0).values*f
    w=np.where(frb.dow.values>=5,0.8,0.6); return np.where(frb.hol_wd.values==1,cb,w*cb+(1-w)*pf)
Fb=F.merge(build_x(days),on='date'); Fb['prediction']=pred(Fb)
n1=Fb.date.eq('2025-11-01'); fri=Fb[n1].copy(); fri['dow']=4; fri['off']=0; sat=Fb[n1].copy(); sat['dow']=5; sat['off']=1
Fb.loc[n1,'prediction']=0.5*pred(fri)+0.5*pred(sat)
sub=Fb[['route','date','hour','prediction']].copy(); sub['date']=sub.date.dt.strftime('%Y-%m-%d'); sub['prediction']=sub.prediction.round(1).clip(lower=0)
r5=pd.DataFrame([(5,d.strftime('%Y-%m-%d'),h,0.0) for d in days for h in range(24)],columns=sub.columns); sub=pd.concat([sub,r5])
ref=pd.read_csv('../data/test_submission.csv',sep=';'); sub=ref[['route','date','hour']].merge(sub,on=['route','date','hour'],how='left')
assert len(sub)==14640 and sub.prediction.notna().all() and (sub.prediction>=0).all()
sub.to_csv(out,sep=';',index=False); print(variant,'->',out,'md5',hashlib.md5(open(out,'rb').read()).hexdigest(),'сумма',round(sub.prediction.sum()))
