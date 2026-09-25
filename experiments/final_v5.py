from pipe2 import *
D_="/Users/denis/Documents/Данные хакатон Мос Транспорт/"
tr=G.copy(); origin=tr.date.max(); assert origin==pd.Timestamp('2025-10-31')
fac=seas(origin,[11,12]); print("сезонные множители (годы 2019,2021–2024, данные ≤ окт 2025):",{k:round(v,4) for k,v in fac.items()})
days=pd.date_range('2025-11-01','2025-12-31')
F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
Fb=add_reg(build(F)); models=[fit2(tr,best,s,True,True) for s in range(5)]
Fb['prediction']=forecast2(tr,Fb,best,fac,models=models)[0]
n1=Fb.date.eq('2025-11-01'); fri=Fb[n1].copy(); fri['dow']=4; fri['off']=0; sat=Fb[n1].copy(); sat['dow']=5; sat['off']=1
pf_=forecast2(tr,fri,best,fac,models=models)[0]; ps_=forecast2(tr,sat,best,fac,models=models)[0]
Fb.loc[n1,'prediction']=np.where(np.isin(sat.route.values,CUT),ps_,0.5*pf_+0.5*ps_)   # 1 ноября: рабочая суббота; на 7 и 50 режим субботы
sub=Fb[['route','date','hour','prediction']].copy(); sub['date']=sub.date.dt.strftime('%Y-%m-%d'); sub['prediction']=sub.prediction.round(1).clip(lower=0)
r5=pd.DataFrame([(5,d.strftime('%Y-%m-%d'),h,0.0) for d in days for h in range(24)],columns=sub.columns); sub=pd.concat([sub,r5])
ref=pd.read_csv(D_+'test_submission.csv',sep=';'); sub=ref[['route','date','hour']].merge(sub,on=['route','date','hour'],how='left')
assert len(sub)==14640 and sub.prediction.notna().all() and (sub.prediction>=0).all()
sub.to_csv(D_+'submission_v5.csv',sep=';',index=False); sub[sub.route!=5].to_csv(D_+'submission_v5_9routes.csv',sep=';',index=False)
v4=pd.read_csv(D_+'submission_v4.csv',sep=';'); d=sub.assign(date=pd.to_datetime(sub.date),v4=v4.prediction); d['dow']=d.date.dt.dayofweek; d['m']=d.date.dt.month
t=d[d.route.isin(CUT)&(d.dow>=5)&(d.date!='2025-12-31')].groupby(['route','m']).agg(v5=('prediction','sum'),v4=('v4','sum')); n=d[d.route.isin(CUT)&(d.dow>=5)&(d.date!='2025-12-31')].groupby(['route','m']).date.nunique()
t['дней']=n; t['v5 в сутки']=(t.v5/t['дней']).round(0); t['v4 в сутки']=(t.v4/t['дней']).round(0); print("выходные маршрутов 7 и 50 (среднее посадок в сутки):"); print(t[['дней','v4 в сутки','v5 в сутки']].to_string())
print("будни маршрутов 7/50 v5:",d[d.route.isin(CUT)&(d.dow<5)&(d.hol_wd if 'hol_wd' in d else 0)==0].groupby(['route','m']).prediction.sum().div(d[d.route.isin(CUT)&(d.dow<5)].groupby(['route','m']).date.nunique()).round(0).to_dict())
print("сумма: v4",round(v4.prediction.sum()),"v5",round(sub.prediction.sum()),"| ноябрь v5",round(d[d.m==11].prediction.sum()),"декабрь v5",round(d[d.m==12].prediction.sum()),"| изменение от v4 %:",round((sub.prediction.sum()/v4.prediction.sum()-1)*100,2))
