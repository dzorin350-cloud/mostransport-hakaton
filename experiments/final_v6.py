from pipe3 import *
D_="/Users/denis/Documents/Данные хакатон Мос Транспорт/"
tr=G.copy(); origin=tr.date.max(); assert origin==pd.Timestamp('2025-10-31')
fac=seas(origin,[11,12]); print("сезонные множители:",{k:round(v,4) for k,v in fac.items()},"| r_pre 7,50:",r_pre(tr).round(3)[[7,50]].to_dict())
days=pd.date_range('2025-11-01','2025-12-31')
F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
Fb=add_reg2(build(F)); models=[fit3(tr,best,s) for s in range(5)]
Fb['prediction']=forecast3(tr,Fb,best,fac,models=models)[0]
n1=Fb.date.eq('2025-11-01'); fri=Fb[n1].copy(); fri['dow']=4; fri['off']=0; sat=Fb[n1].copy(); sat['dow']=5; sat['off']=1
pf_=forecast3(tr,fri,best,fac,models=models)[0]; ps_=forecast3(tr,sat,best,fac,models=models)[0]
Fb.loc[n1,'prediction']=np.where(np.isin(sat.route.values,CUT),ps_,0.5*pf_+0.5*ps_)
sub=Fb[['route','date','hour','prediction']].copy(); sub['date']=sub.date.dt.strftime('%Y-%m-%d'); sub['prediction']=sub.prediction.round(1).clip(lower=0)
r5=pd.DataFrame([(5,d.strftime('%Y-%m-%d'),h,0.0) for d in days for h in range(24)],columns=sub.columns); sub=pd.concat([sub,r5])
ref=pd.read_csv(D_+'test_submission.csv',sep=';'); sub=ref[['route','date','hour']].merge(sub,on=['route','date','hour'],how='left')
assert len(sub)==14640 and sub.prediction.notna().all() and (sub.prediction>=0).all() and set(sub.route)==set(ref.route)
sub.to_csv(D_+'submission_v6.csv',sep=';',index=False)
v4=pd.read_csv(D_+'submission_v4.csv',sep=';'); d=sub.assign(date=pd.to_datetime(sub.date),v4=v4.prediction); d['dow']=d.date.dt.dayofweek; d['m']=d.date.dt.month
cut=d[d.route.isin(CUT)&(d.dow>=5)&(d.date!='2025-12-31')]; t=cut.groupby(['route','m']).agg(v6=('prediction','sum'),v4=('v4','sum'),n=('date','nunique'))
t['v4 в сутки']=(t.v4/t.n).round(0); t['v6 в сутки']=(t.v6/t.n).round(0); print("выходные маршрутов 7 и 50 (посадок в сутки):"); print(t[['n','v4 в сутки','v6 в сутки']].to_string())
oct_=G[(G.date>='2025-10-06')&(G.date<='2025-10-31')&(G.date.dt.dayofweek<5)].groupby(['route','date']).boardings.sum().groupby('route').mean()
w=d[(d.dow<5)&(~d.date.isin(pd.to_datetime(['2025-11-03','2025-11-04','2025-12-31','2025-11-01'])))].groupby(['route','date'])[['prediction','v4']].sum().reset_index(); w['m']=w.date.dt.month
g=w.groupby(['route','m'])[['prediction','v4']].mean().unstack(); r=pd.DataFrame({'v4 ноя':g[('v4',11)]/oct_,'v6 ноя':g[('prediction',11)]/oct_,'v4 дек':g[('v4',12)]/oct_,'v6 дек':g[('prediction',12)]/oct_}).dropna()
print("будни относительно октября (ожидание ноя≈0,985, дек≈1,05):"); print(r.round(3).to_string())
print("сумма: v4",round(v4.prediction.sum()),"v6",round(sub.prediction.sum()),"| изменение %",round((sub.prediction.sum()/v4.prediction.sum()-1)*100,2))
