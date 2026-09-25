import duckdb, pandas as pd
con=duckdb.connect(); con.execute("PRAGMA threads=10")
q="""select cast(regexp_extract(ngpt_route,'^(\\d+)',1) as int) route, cast(date_trunc('day',cast(tran_date_time as timestamp)) as date) date, hour(cast(tran_date_time as timestamp)) as hr,
 case when good_type ilike '%СКМ%' or good_type ilike '%СКМО%' then 'социальная'
      when good_type = 'КОШЕЛЕК' then 'кошелёк'
      when good_type ilike '%ББК%' then 'банк.карта'
      when good_type ilike '%дн%' then 'проездные'
      else 'прочее' end seg, count(*) n
 from 'raw.parquet' where validation_result='1' and cast(tran_date_time as timestamp) < '2025-11-01' group by 1,2,3,4"""
d=con.execute(q).df().rename(columns={'hr':'hour'}); d['date']=pd.to_datetime(d.date); d.to_parquet('seg_counts.parquet')
print(d.groupby('seg').n.sum().div(d.n.sum()).round(3).to_dict())
