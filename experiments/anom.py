import pandas as pd, numpy as np
from model import DAYOFF
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
G=pd.read_parquet('grid.parquet'); G=G[G.route!=5]
d=G.groupby(['route','date']).boardings.sum().reset_index()
s=pd.read_parquet('supply_daily.parquet'); d=d.merge(s[['route','date','veh','exits']],on=['route','date'],how='left')
d['dow']=d.date.dt.dayofweek; d['dt']=np.where(d.date.isin(DAYOFF),'hol',np.where(d.dow<5,'wd',np.where(d.dow==5,'sat','sun')))
# ожидание: медиана того же типа дня за окно ±5 недель (robust), без праздников
out=[]
for (r,t),g in d[d.dt!='hol'].groupby(['route','dt']):
    g=g.sort_values('date').copy(); g['exp']=g.boardings.rolling(11,center=True,min_periods=5).median(); g['vexp']=g.veh.rolling(11,center=True,min_periods=5).median(); out.append(g)
a=pd.concat(out); a['ratio']=a.boardings/a.exp; a['vratio']=a.veh/a.vexp
a.to_parquet('anom_daily.parquet')
# дни-аномалии
bad=a[(a.ratio<0.8)|(a.ratio>1.2)]
print("аномальных дней (|откл|>20%):",len(bad),"из",len(a)); print(bad.groupby('route').size().to_dict())
print(bad.sort_values(['route','date'])[['route','date','dt','boardings','exp','ratio','veh','vexp']].round(2).to_string(index=False))
