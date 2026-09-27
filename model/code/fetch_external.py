"""Обновляет внешние данные для прода (нужен интернет из РФ).
1) производственный календарь: isdayoff.ru → external/cal_YYYY.txt (текущий и следующий год, + 2022–2025);
2) месячный пассажиропоток трамвая: data.mos.ru (набор 62521) → external/mos/ridership_allowed.csv,
   ТОЛЬКО месяцы не позже конца обучающих данных (иначе утечка будущего в модель).
"""
import os, json, datetime, urllib.request, io, zipfile, ssl, pandas as pd
try:
    import certifi; CTX=ssl.create_default_context(cafile=certifi.where())
except ImportError: CTX=ssl.create_default_context()
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.abspath(os.path.join(HERE,'..','..')); EXT=os.path.join(ROOT,'external')
def get(u): return urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=60,context=CTX).read()
y0=datetime.date.today().year
for y in sorted(set(range(2022,2026))|{y0,y0+1}):
    try:
        s=get(f'https://isdayoff.ru/api/getdata?year={y}&pre=1').decode().strip()
        if len(s) in (365,366): open(os.path.join(EXT,f'cal_{y}.txt'),'w').write(s); print('календарь',y,'ok')
    except Exception as e: print('календарь',y,'ошибка:',e,'(оставлен кэш)')
# конец обучающих данных — последний день в labels
L=pd.read_csv(os.path.join(ROOT,'labels','labels_day_test.csv'),sep=';'); cutoff=pd.Timestamp(L.date.max())
try:
    meta=json.load(open(os.path.join(EXT,'mos','meta_62521.json'))); url=meta['data'][0]['source']     # самая свежая выгрузка
    raw=get(url)
    try: z=zipfile.ZipFile(io.BytesIO(raw)); raw=z.read(z.namelist()[0])
    except zipfile.BadZipFile: pass
    txt=raw.decode('utf-8-sig')
    d=pd.read_json(io.StringIO(txt)) if txt.lstrip().startswith('[') else pd.read_csv(io.StringIO(txt),sep=';').iloc[1:]
    cols={c:c for c in d.columns}; d=d.rename(columns={'Year':'year','Month':'month','TypeOfTransport':'type','Type of transport':'type','PassengerTraffic':'pax','Passenger traffic':'pax'})
    mm={m:i+1 for i,m in enumerate(['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'])}
    d['year']=d.year.astype(int); d['m']=d.month.map(mm); d['pax']=pd.to_numeric(d.pax)
    d=d[(d.year<cutoff.year)|((d.year==cutoff.year)&(d.m<=cutoff.month))]
    d=d.assign(code=range(1,len(d)+1))[['code','year','month','type','pax','m']]
    for p in (os.path.join(EXT,'mos','ridership_allowed.csv'),os.path.join(HERE,'..','data','ridership_allowed.csv')): d.to_csv(p,index=False); print('data.mos.ru 62521 ok, до',cutoff.date())
except Exception as e: print('data.mos.ru: ошибка',e,'(оставлен кэш external/mos/ridership_allowed.csv)')
