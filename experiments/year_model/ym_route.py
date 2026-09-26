"""Годовая модель, шаг 2: наши маршруты по часам, длинный горизонт (обучение до конца фев/мар/апр 2025 → прогноз до октября).
Сравнение множителей: текущий (v7), явный рост, среднее двух. Плюс оценка потолка выгоды от сезонной формы дня (оракул)."""
import sys, os; sys.path.insert(0,os.path.abspath('../FROZEN_v7_score_0.88399/code'))
from clean import *
import ym_city as yc
def mults(o,how):
    op=pd.Period(o,'M'); hist=yc.S[yc.S.index<=op]; out={}
    for k in range(1,13):
        t=op+k; a=hist[op]*yc.m_ratio(hist,op,k); b=yc.fc(op,k,method='si',alpha=1,phi=1.0)
        f={'текущий':a,'явный рост':b,'среднее двух':(a+b)/2}[how]; out[t.month]=f/hist[op]
    return out
rows=[]; RES=[]
for o in ['2025-02-28','2025-03-31','2025-04-30']:
    o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>o)&(G.date<='2025-10-31')].copy(); fr=te[['route','date','hour']]
    b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1; c=clean_grid(tr,1.5,protect_weeks=0)[0]
    _,cb,pf=forecast(c,fr,best,seeds=2,fac={m:1.0 for m in range(1,13)}); base=np.where(hol,cb,w*cb+(1-w)*pf)   # без множителя
    for how in ['текущий','явный рост','среднее двух']:
        te[how]=base*te.date.dt.month.map(mults(o,how)).values
    # оракул формы дня: сумма за маршрут-день как в прогнозе «среднее двух», а распределение по часам — фактическое среднее этого месяца
    d=te.copy(); d['dt']=dtype(d.date); d['m']=d.date.dt.month
    tot=d.groupby(['route','date']).boardings.transform('sum'); d['sh']=d.boardings/tot.replace(0,np.nan)
    shm=d.groupby(['route','m','dt','hour']).sh.mean().rename('shm').reset_index()
    d=d.merge(shm,on=['route','m','dt','hour'],how='left'); dayp=d.groupby(['route','date'])['среднее двух'].transform('sum')
    te['оракул формы']=(dayp*d.shm.fillna(0)).values
    te['origin']=o.strftime('%Y-%m'); te['k']=te.date.dt.month-o.month; RES.append(te)
    print(o.date(),{c:round(1-wape(te.boardings.values,te[c].values),4) for c in ['текущий','явный рост','среднее двух','оракул формы']},flush=True)
A=pd.concat(RES); cols=['текущий','явный рост','среднее двух','оракул формы']
T=A.groupby('k').apply(lambda g:pd.Series({c:1-wape(g.boardings.values,g[c].values) for c in cols})).round(4)
T.loc['все']=[round(1-wape(A.boardings.values,A[c].values),4) for c in cols]; T.loc['3–8 мес']=[round(1-wape(A[A.k>=3].boardings.values,A[A.k>=3][c].values),4) for c in cols]
print(T.to_string()); A.to_parquet('ym_route_backtest.parquet')
