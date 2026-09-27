from clean import *
D_=D
tr,dd=clean_grid(G.copy(),1.5,protect_weeks=0); origin=tr.date.max(); assert origin==pd.Timestamp('2025-10-31')
print("помечено маршруто-дней:",int(dd.m.sum()),dd[dd.m].groupby('route').size().to_dict())
fac=seas(origin,[11,12]); days=pd.date_range('2025-11-01','2025-12-31')
F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
L=tr[tr.date>origin-pd.Timedelta(days=best['lvl'])].groupby('route').boardings.sum()/best['lvl']
SETS=best['shape_sets']; models=[(fs,[fit_cb(tr,best,s,fs) for s in range(5)]) for fs in SETS]; PR=prof(tr,best['weeks'],best['prof_agg'])
def pred(frb):
    f=frb.date.dt.month.map(fac).values
    per_set=[]
    for fs,ms in models:                       # форма дня: среднее 5 seed внутри набора признаков, затем среднее наборов
        X=frb[fs].copy(); X['route']=X.route.astype(int); per_set.append(np.mean([np.clip(m.predict(X),0,None) for m in ms],axis=0))
    cb=np.mean(per_set,axis=0)*frb.route.map(L).values*f
    pf=frb.merge(PR,on=['route','dow','hour'],how='left').p.fillna(0).values*f
    w=np.where(frb.dow.values>=5,0.8,0.6); return np.where(frb.hol_wd.values==1,cb,w*cb+(1-w)*pf)
Fb=build(F); Fb['prediction']=pred(Fb)
n1=Fb.date.eq('2025-11-01'); fri=Fb[n1].copy(); fri['dow']=4; fri['off']=0; sat=Fb[n1].copy(); sat['dow']=5; sat['off']=1
Fb.loc[n1,'prediction']=0.5*pred(fri)+0.5*pred(sat)
sub=Fb[['route','date','hour','prediction']].copy(); sub['date']=sub.date.dt.strftime('%Y-%m-%d'); sub['prediction']=sub.prediction.round(1).clip(lower=0)
r5=pd.DataFrame([(5,d.strftime('%Y-%m-%d'),h,0.0) for d in days for h in range(24)],columns=sub.columns); sub=pd.concat([sub,r5])
ref=pd.read_csv(D_+'test_submission.csv',sep=';'); sub=ref[['route','date','hour']].merge(sub,on=['route','date','hour'],how='left')
assert len(sub)==14640 and sub.prediction.notna().all() and (sub.prediction>=0).all()
sub.to_csv(os.path.join(D_,'..','output','submission.csv'),sep=';',index=False)
v4=pd.read_csv(D_+'submission_v4.csv',sep=';'); print("сумма v4",round(v4.prediction.sum()),"итоговая",round(sub.prediction.sum()),"| |итоговая-v4|/v4 %",round((sub.prediction-v4.prediction).abs().sum()/v4.prediction.sum()*100,2))
d=sub.assign(date=pd.to_datetime(sub.date),v4=v4.prediction); d['we']=d.date.dt.dayofweek>=5
print((d.groupby(['route','we'])[['v4','prediction']].sum().unstack().div(d.groupby(['route','we']).date.nunique().unstack().reindex(columns=[False,True]).values.repeat(1,axis=0).tolist() if False else 1)).round(0).head(0))
print(d.groupby(['route',d.date.dt.month])[['v4','prediction']].sum().unstack().round(-3).to_string())
