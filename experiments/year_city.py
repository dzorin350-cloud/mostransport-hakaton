import pandas as pd, numpy as np, calendar
C=pd.read_csv('/Users/denis/Documents/Данные хакатон Мос Транспорт/external/mos/ridership_allowed.csv'); C=C[C.type=='Трамвай'].copy()
C['pd_']=C.pax/[calendar.monthrange(y,m)[1] for y,m in zip(C.year,C.m)]
S=C.set_index(pd.PeriodIndex([f'{y}-{m:02d}' for y,m in zip(C.year,C.m)],freq='M')).pd_.sort_index()
COVID=set(pd.period_range('2020-03','2021-06',freq='M'))
def fc(origin,h=12,method='seas',phi=0.8,years=None):
    """прогноз посадок в сутки на h месяцев после origin, только по данным <= origin"""
    hist=S[S.index<=origin]; out={}
    for k in range(1,h+1):
        t=origin+k; yrs=[y for y in range(2019,origin.year+1) if (pd.Period(f'{y}-{origin.month:02d}','M') in hist.index)]
        # отношение месяца t (через k месяцев) к базовому месяцу в прошлые годы
        rs=[]
        for y in yrs:
            b=pd.Period(f'{y}-{origin.month:02d}','M'); tt=b+k
            if tt in hist.index and b not in COVID and tt not in COVID and (years is None or y in years): rs.append(hist[tt]/hist[b])
        if method=='naive': out[t]=hist[origin]
        elif method=='snaive': out[t]=hist[t-12] if (t-12) in hist.index else hist[origin]
        elif method=='snaive_g':
            g=np.mean([hist[origin-i]/hist[origin-i-12] for i in range(3)]); out[t]=hist[t-12]*(1+(g-1)*phi**(k/12*12/12))
        elif method=='seas': out[t]=hist[origin]*np.mean(rs) if rs else hist[origin]
        elif method=='seas_recent': out[t]=hist[origin]*np.mean(rs[-3:]) if rs else hist[origin]
    return pd.Series(out)
rows=[]
for oy in [2022,2023,2024]:
    o=pd.Period(f'{oy}-10','M'); act=S[(S.index>o)&(S.index<=o+12)]
    for m,kw in [('наивный (как октябрь)',dict(method='naive')),('прошлый год, тот же месяц',dict(method='snaive')),('прошлый год × рост (затухающий)',dict(method='snaive_g')),
                 ('сезонность все годы (как в v7)',dict(method='seas')),('сезонность 3 последних года',dict(method='seas_recent'))]:
        f=fc(o,**kw).reindex(act.index); e=(f-act).abs().sum()/act.sum()
        rows.append((f'{o+1}…{o+12}',m,round(1-e,4),round(((f-act)/act).abs().max(),3)))
df=pd.DataFrame(rows,columns=['горизонт 12 мес','метод','скор (1-WAPE по месяцам)','макс. ошибка месяца']); print(df.to_string(index=False))
print("\nсреднее по трём годам:"); print(df.groupby('метод')['скор (1-WAPE по месяцам)'].mean().sort_values(ascending=False).round(4).to_string())
