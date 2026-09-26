"""Годовая модель, шаг 1: сезонность и рост на месячных данных трамвая Москвы (data.mos.ru 62521, только <= окт 2025)."""
import pandas as pd, numpy as np, calendar
C=pd.read_csv('../external/mos/ridership_allowed.csv'); C=C[C.type=='Трамвай'].copy()
C['pd_']=C.pax/[calendar.monthrange(y,m)[1] for y,m in zip(C.year,C.m)]
S=C.set_index(pd.PeriodIndex([f'{y}-{m:02d}' for y,m in zip(C.year,C.m)],freq='M')).pd_.sort_index()
COVID=pd.period_range('2020-03','2021-06',freq='M')
def ok(p): return p in S.index and p not in COVID
def m_ratio(hist,op,k):
    """текущий метод (v7): среднее по прошлым годам отношения «месяц op+k / месяц op»; рост зашит"""
    rs=[hist[pd.Period(f'{y}-{op.month:02d}','M')+k]/hist[pd.Period(f'{y}-{op.month:02d}','M')] for y in range(2019,op.year)
        if y!=2020 and ok(pd.Period(f'{y}-{op.month:02d}','M')) and ok(pd.Period(f'{y}-{op.month:02d}','M')+k) and pd.Period(f'{y}-{op.month:02d}','M')+k<=op]
    return np.mean(rs) if rs else np.nan
def seas_index(hist):
    """сезонный индекс месяца: доля месяца к среднему своего календарного года; только полные не-ковидные годы <= origin"""
    yrs=[y for y in range(2019,2026) if all(ok(pd.Period(f'{y}-{m:02d}','M')) and pd.Period(f'{y}-{m:02d}','M') in hist.index for m in range(1,13))]
    si=pd.concat([hist[[pd.Period(f'{y}-{m:02d}','M') for m in range(1,13)]].pipe(lambda x:pd.Series(x.values/x.values.mean(),index=range(1,13))) for y in yrs],axis=1).mean(axis=1)
    return si/si.mean()
def fc(op,k,method,phi=1.0,alpha=1.0):
    hist=S[S.index<=op]; t=op+k
    if method=='ratio': return hist[op]*m_ratio(hist,op,k)
    si=seas_index(hist)
    lvl=np.mean([hist[op-i]/si[(op-i).month] for i in range(3)])            # десезонированный уровень, 3 последних месяца
    g=hist[op-11:op].sum()/hist[op-23:op-12].sum()                          # рост последних 12 мес. к предыдущим 12
    if (op-23) in COVID or (op-11) in COVID or (op-23)<S.index.min(): g=1.0
    r=(g-1)*alpha; steps=sum(phi**i for i in range(1,k+1))/12 if phi<1 else k/12
    return lvl*si[t.month]*(1+r)**steps
methods={'текущий (множители, рост зашит)':dict(method='ratio'),
         'индекс сезонности, без роста':dict(method='si',alpha=0),
         'индекс + явный рост, без затухания':dict(method='si',alpha=1,phi=1.0),
         'индекс + явный рост, затухание 0,9':dict(method='si',alpha=1,phi=0.9),
         'индекс + половина роста':dict(method='si',alpha=0.5,phi=1.0)}
rows=[]
for op in pd.period_range('2022-01','2024-10',freq='M'):
    for k in range(1,13):
        t=op+k
        if t>pd.Period('2025-10','M') or not ok(t): continue
        for nm,kw in methods.items():
            f=fc(op,k,**kw)
            if np.isfinite(f): rows.append((str(op),k,nm,f,S[t]))
R=pd.DataFrame(rows,columns=['origin','k','метод','f','y'])
def sc(g): return 1-(g.f-g.y).abs().sum()/g.y.sum()
print("Город, прогноз суточного пассажиропотока месяца; стартов:",R.origin.nunique(),"(все месяцы 2022-01…2024-10)")
T=R.groupby(['метод','k']).apply(sc).unstack().round(3); T['среднее 1–12']=R.groupby('метод').apply(sc).round(4); T['среднее 3–12']=R[R.k>=3].groupby('метод').apply(sc).round(4)
print(T.to_string())
B=R.assign(b=(R.f/R.y-1)).groupby(['метод']).b.mean().round(4); print("\nсреднее смещение (прогноз/факт−1):"); print(B.to_string())
R.to_csv('ym_city_backtest.csv',index=False)
