"""Финал v7 (train + test), но праздничный календарь — из isdayoff.ru (как в движке). Код v7 не меняется, только читается."""
import sys
sys.path.insert(0,'/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
sys.path.insert(0,'/private/tmp/claude-501/-Users-denis-Documents-----------------------------/010cb3cc-d4d5-4cc0-bfa4-a45169a45c88/scratchpad/repo')
import model
from clean import *
from service.engine.sources import fetch_calendar
from service.engine.core import Calendar
from pathlib import Path
codes,st=fetch_calendar([2024,2025,2026],Path('cache')); cal=Calendar(codes); print('календарь isdayoff:',st['years'])
ISD={pd.Timestamp(d) for d in cal.holidays if d.year==2025}; model.DAYOFF.clear(); model.DAYOFF.update(ISD)
print('праздничные дни 2025 по isdayoff:',len(ISD))
tr,dd=clean_grid(G.copy(),1.5,protect_weeks=0); origin=tr.date.max(); assert origin==pd.Timestamp('2025-10-31')
print('обучение: до',origin.date(),'| очищено маршруто-дней:',int(dd.m.sum()))
fac=seas(origin,[11,12]); days=pd.date_range('2025-11-01','2025-12-31'); print('множители:',{k:round(v,4) for k,v in fac.items()})
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
Fb.loc[n1,'prediction']=0.5*pred(fri)+0.5*pred(sat)
sub=Fb[['route','date','hour','prediction']].copy(); sub['date']=sub.date.dt.strftime('%Y-%m-%d'); sub['prediction']=sub.prediction.round(1).clip(lower=0)
r5=pd.DataFrame([(5,d.strftime('%Y-%m-%d'),h,0.0) for d in days for h in range(24)],columns=sub.columns); sub=pd.concat([sub,r5])
ref=pd.read_csv(D+'test_submission.csv',sep=';'); sub=ref[['route','date','hour']].merge(sub,on=['route','date','hour'],how='left')
assert len(sub)==14640 and sub.prediction.notna().all() and (sub.prediction>=0).all() and (sub[['route','date','hour']].values==ref[['route','date','hour']].values).all()
out='/Users/denis/Documents/Данные хакатон Мос Транспорт/submission_v7_isdayoff.csv'; sub.to_csv(out,sep=';',index=False); print('сохранено:',out,sub.shape)
v7=pd.read_csv(D+'../submission_v7_ORIGINAL.csv',sep=';'); d=(sub.prediction-v7.prediction).abs()
print('против v7: строк отличается',int((d>0).sum()),'из',len(d),'| сумма |разница|',round(d.sum(),1),'| в % от суммы',round(d.sum()/v7.prediction.sum()*100,4),'| сумма v7',round(v7.prediction.sum()),'новый',round(sub.prediction.sum()))
eng=pd.read_parquet('/private/tmp/claude-501/-Users-denis-Documents-----------------------------/010cb3cc-d4d5-4cc0-bfa4-a45169a45c88/scratchpad/engine_table.parquet'); eng['date']=pd.to_datetime(eng.date).dt.strftime('%Y-%m-%d')
m=sub.merge(eng,on=['route','date','hour'],suffixes=('','_eng')); print('против движка в сервисе: |разница| в % от суммы',round((m.prediction-m.prediction_eng).abs().sum()/m.prediction.sum()*100,4))
