"""Продовый прогноз на любой горизонт (день / месяц / год) по итоговой модели.

    python forecast.py --start 2025-11-01 --end 2025-12-31 --out ../output/forecast.csv
    python forecast.py --start 2025-11-01 --end 2026-10-31 --refresh      # год + свежие внешние данные

Логика та же, что в final.py: очистка обучения → уровень маршрута × форма дня (CatBoost + профиль) × сезонный множитель.
Отличия: множители считаются для любого месяца горизонта (до 12 месяцев вперёд), календарь берётся из
external/cal_YYYY.txt (isdayoff.ru), с --refresh внешние данные предварительно обновляются (fetch_external.py).
"""
import argparse, os, sys, subprocess, calendar as _c
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
ap=argparse.ArgumentParser(); ap.add_argument('--start',required=True); ap.add_argument('--end',required=True)
ap.add_argument('--out',default=os.path.join(HERE,'..','output','forecast.csv')); ap.add_argument('--seeds',type=int,default=5)
ap.add_argument('--refresh',action='store_true',help='обновить календарь и сезонность из интернета перед прогнозом')
a=ap.parse_args()
if a.refresh: subprocess.run([sys.executable,os.path.join(HERE,'fetch_external.py')],check=True)
import pandas as pd, numpy as np
import model
from clean import *            # G, clean_grid, fit_cb, prof, build, FEATS, best, P (город по месяцам)
start,end=pd.Timestamp(a.start),pd.Timestamp(a.end)
# 1) календарь горизонта: праздничные будни из isdayoff
for y in range(start.year,end.year+1):
    f=os.path.join(ROOT,'external',f'cal_{y}.txt')
    if not os.path.exists(f): sys.exit(f'нет календаря {f}: запустите fetch_external.py или --refresh')
    for d,c in zip(pd.date_range(f'{y}-01-01',f'{y}-12-31'),open(f).read().strip()):
        if c=='1' and d.dayofweek<5: model.DAYOFF.add(d)
# 2) обучение на очищенных данных
tr,_=clean_grid(G.copy(),1.5,protect_weeks=0); origin=tr.date.max()
if start<=origin: sys.exit(f'начало прогноза должно быть позже конца обучающих данных ({origin.date()})')
# 3) сезонные множители: месяц (через k месяцев) / месяц origin, среднее по годам 2019, 2021+ (без 2020), только данные <= origin
op=pd.Period(origin,'M'); S=P.stack(); S.index=[pd.Period(f'{y}-{m:02d}','M') for y,m in S.index]; S=S[S.index<=op]
COVID=pd.period_range('2020-03','2021-06',freq='M')
def mult(t):
    k=(t-op).n; rs=[]
    for y in range(2019,op.year):
        b=pd.Period(f'{y}-{op.month:02d}','M')
        if y!=2020 and b in S.index and b+k in S.index and (b+k) not in COVID: rs.append(S[b+k]/S[b])
    if not rs: sys.exit(f'нет истории для множителя месяца {t}')
    return float(np.mean(rs))
if (pd.Period(end,'M')-op).n>12: sys.exit('горизонт больше 12 месяцев от конца обучающих данных не поддерживается')
fac={p:mult(p) for p in pd.period_range(pd.Period(start,'M'),pd.Period(end,'M'),freq='M')}
# 4) прогноз
days=pd.date_range(start,end); F=pd.MultiIndex.from_product([ROUTES,days,range(24)],names=['route','date','hour']).to_frame(index=False)
L=tr[tr.date>origin-pd.Timedelta(days=best['lvl'])].groupby('route').boardings.sum()/best['lvl']
t8=build(tr[tr.date>origin-pd.Timedelta(weeks=best['sun_weeks'])]); PRS=t8[(t8.dow==6)&(t8.hol_wd==0)].groupby(['route','hour']).boardings.median().rename('ps').reset_index()   # воскресный профиль
SETS=best['shape_sets']; models=[(fs,[fit_cb(tr,best,s,fs) for s in range(a.seeds)]) for fs in SETS]; PR=prof(tr,best['weeks'],best['prof_agg'])
def pred(frb):
    f=frb.date.dt.to_period('M').map(fac).values
    per_set=[]
    for fs,ms in models:
        X=frb[fs].copy(); X['route']=X.route.astype(int); per_set.append(np.mean([np.clip(m.predict(X),0,None) for m in ms],axis=0))
    cb=np.mean(per_set,axis=0)*frb.route.map(L).values*f
    pf=frb.merge(PR,on=['route','dow','hour'],how='left').p.fillna(0).values*f
    # смесь CatBoost / профиль: будни, выходные, ночные часы; праздничные будни — CatBoost + воскресный профиль
    w=np.where(frb.dow.values>=5,best['w_we'],best['w_wd']); w=np.where(frb.hour.isin(best['night_hours']).values,best['w_night'],w)
    ps=frb.merge(PRS,on=['route','hour'],how='left').ps.fillna(0).values*f
    return np.where(frb.hol_wd.values==1,best['w_hol']*cb+(1-best['w_hol'])*ps,w*cb+(1-w)*pf)
Fb=build(F); Fb['prediction']=pred(Fb)
# рабочие субботы (перенос): среднее прогнозов пятницы и субботы
for y in range(start.year,end.year+1):
    for d,c in zip(pd.date_range(f'{y}-01-01',f'{y}-12-31'),open(os.path.join(ROOT,'external',f'cal_{y}.txt')).read().strip()):
        if c!='1' and d.dayofweek==5 and start<=d<=end:
            n=Fb.date.eq(d); fri=Fb[n].copy(); fri['dow']=4; fri['off']=0; sat=Fb[n].copy(); sat['dow']=5; sat['off']=1
            Fb.loc[n,'prediction']=0.5*pred(fri)+0.5*pred(sat)
# сезонность маршрута (β, сжатие λ) — как в final.py
beta=route_beta(tr); kr=[route_factor(beta,r,fac[p],best['route_season_lambda']) for r,p in zip(Fb.route,Fb.date.dt.to_period('M'))]
Fb['prediction']=Fb.prediction*np.array(kr)
out=Fb[['route','date','hour','prediction']].copy()
r5=pd.DataFrame([(5,d,h,0.0) for d in days for h in range(24)],columns=out.columns); out=pd.concat([out,r5]).sort_values(['route','date','hour'])
out['date']=out.date.dt.strftime('%Y-%m-%d'); out['prediction']=out.prediction.round(1).clip(lower=0)
os.makedirs(os.path.dirname(os.path.abspath(a.out)),exist_ok=True); out.to_csv(a.out,sep=';',index=False)
print('множители месяцев:',{str(k):round(v,3) for k,v in fac.items()}); print('записано',len(out),'строк →',a.out)
