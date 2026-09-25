import pandas as pd, numpy as np
from model import *
for nm,e,s,t in [('F1 Сен–Окт','2025-08-31','2025-09-01','2025-10-31'),('F3 Мар–Апр','2025-02-28','2025-03-01','2025-04-30'),('F2 Июл–Авг','2025-06-30','2025-07-01','2025-08-31')]:
    tr=G[G.date<=e]; te=G[(G.date>=s)&(G.date<=t)].copy()
    Lfc=tr[tr.date>tr.date.max()-pd.Timedelta(days=28)].groupby('route').boardings.sum()/28
    te['p']=np.mean([pred_shape(fit_shape(tr,'RMSE',seed=k),te)[0] for k in range(2)],axis=0)*te.route.map(Lfc).values
    te['wk']=((te.date-pd.Timestamp(s)).dt.days//7)+1
    g=te.groupby('wk').apply(lambda x:pd.Series({'WAPE':wape(x.boardings.values,x.p.values),'bias(pred/fact-1)':x.p.sum()/x.boardings.sum()-1}))
    print(f"\n{nm}: ошибка по неделям горизонта (CatBoost)"); print(g.round(3).T.to_string())
