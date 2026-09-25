import pandas as pd, numpy as np, duckdb
pd.set_option('display.width',220); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',100)
D="/Users/denis/Documents/Данные хакатон Мос Транспорт/"
L=pd.concat([pd.read_csv(D+'labels/labels_day_train.csv',sep=';'),pd.read_csv(D+'labels/labels_day_test.csv',sep=';')])
L['date']=pd.to_datetime(L['date']); print(L.shape, L.date.min(), L.date.max(), sorted(L.route.unique()))
print("dups key:",L.duplicated(['route','date','hour']).sum())
# check vs raw
con=duckdb.connect()
r=con.execute("select cast(regexp_extract(ngpt_route,'^(\\d+)',1) as int) route, date_trunc('hour',cast(tran_date_time as timestamp)) h, count(*) n from 'raw.parquet' where validation_result='1' group by 1,2").df()
r['date']=r.h.dt.normalize(); r['hour']=r.h.dt.hour
m=L.merge(r[['route','date','hour','n']],on=['route','date','hour'],how='outer')
print("labels vs raw: only-in-raw rows",m.boardings.isna().sum(), "(sum",m[m.boardings.isna()].n.sum(),") only-in-labels",m.n.isna().sum(),"diff rows",((m.boardings!=m.n)&m.boardings.notna()&m.n.notna()).sum())
print("raw ok total",r.n.sum(),"labels total",L.boardings.sum())
print(m[m.boardings.isna()].groupby('date').n.sum().tail(3))
# full grid
routes=[1,5,7,11,12,17,25,26,28,50]
days=pd.date_range('2025-01-01','2025-10-31')
g=pd.MultiIndex.from_product([routes,days,range(24)],names=['route','date','hour']).to_frame(index=False)
G=g.merge(L,how='left',on=['route','date','hour']); G['boardings']=G.boardings.fillna(0)
G.to_parquet('grid.parquet')
print("route 5 total:",G[G.route==5].boardings.sum())
d=G.groupby(['route','date']).boardings.sum().unstack(0)
d['dow']=d.index.dayofweek
print("\nDaily mean by dow x route"); print(d.groupby('dow').mean().round(0).astype(int).T)
print("\nMonthly daily-mean by route"); print(d.drop(columns='dow').groupby(d.index.month).mean().round(0).astype(int).T)
tot=d.drop(columns='dow').sum(1)
print("\nDays with zero-service routes (daily==0):");print((d.drop(columns=[5,'dow'])==0).sum())
# hourly profile share (weekday vs sat vs sun)
G['dow']=G.date.dt.dayofweek; G['dt']=np.where(G.dow<5,'wkd',np.where(G.dow==5,'sat','sun'))
p=G[G.route!=5].groupby(['dt','hour']).boardings.sum().unstack(0); p=(p/p.sum()).round(3)
print("\nHourly share by daytype (all routes)");print(p.T.to_string())
# anomalous days: total vs same-dow median of surrounding +-3 wks
tot_df=tot.to_frame('t'); tot_df['dow']=tot_df.index.dayofweek
tot_df['med']=tot_df.groupby('dow').t.transform(lambda s:s.rolling(7,center=True,min_periods=3).median())
tot_df['ratio']=tot_df.t/tot_df.med
print("\nDays deviating >12% from same-dow rolling median:");print(tot_df[(tot_df.ratio<0.88)|(tot_df.ratio>1.12)].round(2).to_string())
# correlation between routes' daily series (detrended by dow)
z=d.drop(columns=[5,'dow']); z=z/z.groupby(d.dow).transform('mean'); print("\ncorr of dow-normalized daily route series");print(z.corr().round(2))
# weekly total trend
w=tot.resample('W').sum();print("\nweekly totals (k):");print((w/1000).round(0).astype(int).to_string())
