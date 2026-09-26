"""Годовая модель, шаг 3: сезонная форма дня. Реалистичная (не оракульная) оценка: форма месяца по нечётным неделям → на чётные и наоборот.
Также вариант со сглаживанием: смесь формы месяца и формы модели (alpha)."""
import sys, os; sys.path.insert(0,os.path.abspath('../FROZEN_v7_score_0.88399/code'))
from clean import dtype, wape
import pandas as pd, numpy as np
A=pd.read_parquet('ym_route_backtest.parquet').reset_index(drop=True); A['dt']=dtype(A.date); A['m']=A.date.dt.month; A['half']=A.date.dt.isocalendar().week.values%2
tot=A.groupby(['origin','route','date']).boardings.transform('sum'); A['sh']=A.boardings/tot.replace(0,np.nan)
base='текущий'; dayp=A.groupby(['origin','route','date'])[base].transform('sum'); A['sh_model']=A[base]/dayp.replace(0,np.nan)
S=A.groupby(['origin','route','m','dt','half','hour']).sh.mean().rename('shx').reset_index(); S['half']=1-S.half      # форма другой половины месяца
A=A.merge(S,on=['origin','route','m','dt','half','hour'],how='left'); dayp=A.groupby(['origin','route','date'])[base].transform('sum')
res={}
for a in [0,0.25,0.5,0.75,1.0]:
    shp=a*A.shx.fillna(A.sh_model)+(1-a)*A.sh_model.fillna(0)
    shp=shp/pd.Series(shp.values).groupby([A.origin.values,A.route.values,A.date.values]).transform('sum').replace(0,np.nan).values
    p=(dayp*shp).fillna(0); res[a]=p
out=A[['origin','k','boardings']].copy()
for a,p in res.items(): out[f'alpha={a}']=p.values
cols=[c for c in out if c.startswith('alpha')]
T=out.groupby('k').apply(lambda g:pd.Series({c:1-wape(g.boardings.values,g[c].values) for c in cols})).round(4)
T.loc['все']=[round(1-wape(out.boardings.values,out[c].values),4) for c in cols]
print("alpha — доля сезонной формы месяца (0 = как v7, 1 = только форма месяца); форма считается по другой половине месяца"); print(T.to_string())
