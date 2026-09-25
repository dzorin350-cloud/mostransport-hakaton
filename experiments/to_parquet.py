import duckdb
D="/Users/denis/Documents/Данные хакатон Мос Транспорт/"
con=duckdb.connect(); con.execute("PRAGMA threads=10")
cols="tran_no;device_no;tran_date_time;begin_date_time;input_date_time;crd_hashcode;validation_result;tran_type_id;place_id;good_type;pass_route;ngpt_route;bus_exit_no;garage_number".split(';')
colspec="{"+",".join(f"'{c}':'VARCHAR'" for c in cols)+"}"
con.execute(f"""copy (select *, {"'train'"} src from read_csv('{D}train.csv',delim=';',header=true,quote='',escape='',columns={colspec},strict_mode=false,ignore_errors=true) union all
 select *, 'test' from read_csv('{D}test.csv',delim=';',header=true,quote='',escape='',columns={colspec},strict_mode=false,ignore_errors=true))
 to 'raw.parquet' (format parquet)""")
print(con.execute("select count(*), count(*) filter (where try_cast(tran_date_time as timestamp) is null) from 'raw.parquet'").fetchall())
