import duckdb, pandas as pd
con=duckdb.connect(); con.execute("PRAGMA threads=10")
q="""select cast(regexp_extract(ngpt_route,'^(\\d+)',1) as int) route, cast(cast(tran_date_time as timestamp) as date) date, hour(cast(tran_date_time as timestamp)) as hr,
 count(distinct garage_number) veh, count(distinct bus_exit_no) exits, count(distinct device_no) dev, sum((validation_result='1')::int) ok, count(*) n_all
 from 'raw.parquet' where cast(tran_date_time as timestamp) < '2025-11-01' group by 1,2,3"""
d=con.execute(q).df().rename(columns={'hr':'hour'}); d['date']=pd.to_datetime(d.date); d.to_parquet('supply_hourly.parquet')
q2="""select cast(regexp_extract(ngpt_route,'^(\\d+)',1) as int) route, cast(cast(tran_date_time as timestamp) as date) date,
 count(distinct garage_number) veh, count(distinct bus_exit_no) exits, min(cast(tran_date_time as timestamp)) first_t, max(cast(tran_date_time as timestamp)) last_t
 from 'raw.parquet' where validation_result='1' and cast(tran_date_time as timestamp) < '2025-11-01' group by 1,2"""
e=con.execute(q2).df(); e['date']=pd.to_datetime(e.date); e.to_parquet('supply_daily.parquet'); print(e.shape, d.shape)
