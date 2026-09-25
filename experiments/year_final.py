from synth import *
from year_route import fac_year
# 1) синтетика на длинном горизонте (обучение до 31.03, прогноз апр–окт)
o=pd.Timestamp('2025-03-31'); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>o)&(G.date<='2025-10-31')].copy(); fr=te[['route','date','hour']]
fac,_=fac_year(o); c=clean_grid(tr,1.5,protect_weeks=0)[0]; b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
_,cb,pf=forecast(c,fr,best,seeds=2,fac=fac); p0=np.where(hol,cb,w*cb+(1-w)*pf); p1=forecast_syn(c,synth(c),fr,best,fac,2,0.1); y=te.boardings.values
print("длинный горизонт (до 31.03 → апр–окт): без синтетики",round(1-wape(y,p0),4),"| с синтетикой",round(1-wape(y,p1),4),flush=True)
# 2) годовой прогноз: 1.11.2025 – 31.10.2026, модель v7 + 12-мес. множители; календарь 2026 из isdayoff
s=open('cal_2026.txt').read().strip()
for d,cc in zip(pd.date_range('2026-01-01','2026-12-31'),s):
    if cc=='1' and d.dayofweek<5: model.DAYOFF.add(d)
tr=G.copy(); c=clean_grid(tr,1.5,protect_weeks=0)[0]; fac,fcity=fac_year(pd.Timestamp('2025-10-31'))
print("множители к октябрю 2025 (город):",{k:round(v,3) for k,v in fac.items()})
days=pd.date_range('2025-11-01','2026-10-31'); F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
L=c[c.date>c.date.max()-pd.Timedelta(days=best['lvl'])].groupby('route').boardings.sum()/best['lvl']
models=[fit_cb(c,best,s) for s in range(3)]; PR=prof(c,best['weeks'])
Fb=build(F); f=Fb.date.dt.month.map(fac).values; X=Fb[FEATS].copy(); X['route']=X.route.astype(int)
cbp=np.mean([np.clip(m.predict(X),0,None) for m in models],axis=0)*Fb.route.map(L).values*f
pfp=Fb.merge(PR,on=['route','dow','hour'],how='left').p.fillna(0).values*f
w=np.where(Fb.dow.values>=5,0.8,0.6); Fb['prediction']=np.where(Fb.hol_wd.values==1,cbp,w*cbp+(1-w)*pfp).round(1)
out=Fb[['route','date','hour','prediction']]; out.to_csv('/Users/denis/Documents/Данные хакатон Мос Транспорт/forecast_year_2025-11_2026-10.csv',sep=';',index=False)
m=out.groupby(out.date.dt.to_period('M')).prediction.sum()/out.groupby(out.date.dt.to_period('M')).date.nunique()*24/24
print("годовой прогноз, посадок в сутки (9 маршрутов):"); print((out.groupby(out.date.dt.to_period('M')).prediction.sum()/out.groupby(out.date.dt.to_period('M')).date.nunique()).round(0).to_string())
v7=pd.read_csv('/Users/denis/Documents/Данные хакатон Мос Транспорт/submission_v7.csv',sep=';'); v7['date']=pd.to_datetime(v7.date)
chk=out.merge(v7,on=['route','date','hour'],suffixes=('','_v7')); print("совпадение с v7 на ноябре–декабре, |разница|/сумма %:",round((chk.prediction-chk.prediction_v7).abs().sum()/chk.prediction_v7.sum()*100,2))
