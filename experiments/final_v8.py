import pandas as pd, numpy as np
D_="/Users/denis/Documents/Данные хакатон Мос Транспорт/"
s=pd.read_csv(D_+'external/google_mobility/russia_transit_daily.csv',index_col=0,parse_dates=True).iloc[:,0]
sh=[]
for y in (2020,2021):
    x=s[f'{y}-11-01':f'{y}-12-31']; ref=x[f'{y}-11-09':f'{y}-11-30']; base={k:ref[ref.index.dayofweek==k].median() for k in range(7)}
    r=pd.Series([v/base[k] for v,k in zip(x.values,x.index.dayofweek)],index=x.index)[f'{y}-12-01':f'{y}-12-30']; sh.append(r.values)
shape=pd.Series(np.mean(sh,axis=0),index=range(1,31)).rolling(3,center=True,min_periods=1).mean()
shape=shape/shape.mean()
print("форма декабря (день: множитель, среднее 1-30 = 1):",shape.round(3).to_dict())
v7=pd.read_csv(D_+'submission_v7.csv',sep=';'); dt=pd.to_datetime(v7.date)
m=(dt.dt.month==12)&(dt.dt.day<=30)
v8=v7.copy(); v8.loc[m,'prediction']=(v7.loc[m,'prediction']*dt[m].dt.day.map(shape).values).round(1)
ref=pd.read_csv(D_+'test_submission.csv',sep=';'); assert len(v8)==14640 and (v8[['route','date','hour']].values==ref[['route','date','hour']].values).all() and (v8.prediction>=0).all()
v8.to_csv(D_+'submission_v8.csv',sep=';',index=False)
print("сумма декабря v7",round(v7[dt.dt.month==12].prediction.sum()),"v8",round(v8[dt.dt.month==12].prediction.sum()),"| всего",round(v7.prediction.sum()),round(v8.prediction.sum()))
d=v8.assign(date=dt).groupby('date').prediction.sum(); print("сутки v8: 1.12",round(d['2025-12-01']),"15.12",round(d['2025-12-15']),"22.12",round(d['2025-12-22']),"29.12",round(d['2025-12-29']),"30.12",round(d['2025-12-30']))
shape.to_csv(D_+'external/google_mobility/december_shape.csv')
