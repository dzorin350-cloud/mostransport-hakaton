import optuna, json
from pipe import *
optuna.logging.set_verbosity(optuna.logging.ERROR)
st=optuna.load_study(study_name='cb1',storage='sqlite:///optuna.db'); best=dict(DEF); best.update(st.best_params)
json.dump(dict(params=st.best_params,inner_score=st.best_value,trial=st.best_trial.number,n_trials=len(st.trials)),open('best_params_final.json','w'),ensure_ascii=False,indent=1)
print("Optuna: проб",len(st.trials),"| лучшая №",st.best_trial.number,"| inner-скор",round(st.best_value,4))
tr=G.copy(); origin=tr.date.max(); assert origin==pd.Timestamp('2025-10-31')
months=[11,12]; base=10
yrs=[y for y in P.index if y<2025 and y!=2020 and not P.loc[y,[base]+months].isna().any()]
fac={m:float(np.mean([P.loc[y,m]/P.loc[y,base] for y in yrs])) for m in months}   # только сезонность, данные ≤ окт 2025
print("годы для сезонности:",yrs,"| множители уровня:",{k:round(v,4) for k,v in fac.items()})
days=pd.date_range('2025-11-01','2025-12-31')
F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
L=tr[tr.date>origin-pd.Timedelta(days=best['lvl'])].groupby('route').boardings.sum()/best['lvl']
models=[fit_cb(tr,best,s) for s in range(5)]; PR=prof(tr,best['weeks'])
def pred(frb):
    f=frb.date.dt.month.map(fac).values; X=frb[FEATS].copy(); X['route']=X.route.astype(int)
    cb=np.mean([np.clip(m.predict(X),0,None) for m in models],axis=0)*frb.route.map(L).values*f
    pf=frb.merge(PR,on=['route','dow','hour'],how='left').p.fillna(0).values*f
    w=np.where(frb.dow.values>=5,0.8,0.6); return np.where(frb.hol_wd.values==1,cb,w*cb+(1-w)*pf)
Fb=build(F); Fb['prediction']=pred(Fb)
n1=Fb.date.eq('2025-11-01'); fri=Fb[n1].copy(); fri['dow']=4; fri['off']=0; sat=Fb[n1].copy(); sat['dow']=5; sat['off']=1
Fb.loc[n1,'prediction']=0.5*pred(fri)+0.5*pred(sat)     # 1 ноября = рабочая суббота
sub=Fb[['route','date','hour','prediction']].copy(); sub['date']=sub.date.dt.strftime('%Y-%m-%d'); sub['prediction']=sub.prediction.round(1).clip(lower=0)
r5=pd.DataFrame([(5,d.strftime('%Y-%m-%d'),h,0.0) for d in days for h in range(24)],columns=sub.columns); sub=pd.concat([sub,r5])
ref=pd.read_csv(D+'test_submission.csv',sep=';'); sub=ref[['route','date','hour']].merge(sub,on=['route','date','hour'],how='left')
assert len(sub)==14640 and sub.prediction.notna().all() and (sub.prediction>=0).all()
sub.to_csv(D+'submission_v4.csv',sep=';',index=False)
d=sub.assign(date=pd.to_datetime(sub.date)); dd=d.groupby('date').prediction.sum()
print("saved submission_v4.csv",sub.shape,"| сумма",round(sub.prediction.sum()),"| ноябрь",round(d[d.date.dt.month==11].prediction.sum()),"декабрь",round(d[d.date.dt.month==12].prediction.sum()))
print("сутки: 1.11",round(dd['2025-11-01']),"3.11(выходной)",round(dd['2025-11-03']),"5.11",round(dd['2025-11-05']),"12.11",round(dd['2025-11-12']),"31.12",round(dd['2025-12-31']),"| окт-будни (факт)",round(G[(G.date>='2025-10-06')&(G.date<='2025-10-10')].groupby('date').boardings.sum().mean()))
