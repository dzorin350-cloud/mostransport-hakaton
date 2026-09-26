"""Оценочная разбивка прогноза маршрута по остановкам (GTFS data.mos.ru: наборы 60661 stop_times, 60662 stops, 60664 routes, 60665 trips).

Пассажиропотока по остановкам в данных нет (в валидациях нет остановки, place_id — депо), поэтому разбивка ОЦЕНОЧНАЯ:
  вес остановки = 1 × (1 + 0,35·ln(1 + число маршрутов любого транспорта через остановку)) × (1,5, если пересадка на метро/МЦК/МЦД/вокзал);
  на конечной остановке направления посадок нет (вес 0); направления делятся пропорционально числу рейсов.
Сумма долей по остановкам маршрута = 1, поэтому сумма по остановкам совпадает с прогнозом маршрута.

    python -m service.engine.build_stops <каталог с CSV data.mos.ru> → service/engine/artifacts/stops.csv, stops.geojson
"""
import json, math, re, sys
from pathlib import Path
import duckdb, pandas as pd
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "external/mos"); OUT = Path(__file__).resolve().parent / "artifacts"
OURS = ["1", "7", "11", "12", "17", "25", "26", "28", "50"]
HUB = re.compile(r"метро|мцк|мцд|вокзал|станция", re.I)
f = lambda pat: str(sorted(SRC.glob(pat))[-1])
con = duckdb.connect()
rd = lambda p: f"read_csv('{p}', delim=';', header=true, all_varchar=true, ignore_errors=true, strict_mode=false)"
R = con.execute(f"select \"Route code\" as rc, trim(\"Number of the route\") as num, \"Full name route\" as rname, trim(\"Type of route\") as typ from {rd(f('data-60664-*.csv'))}").df()
R = R[(R.typ == "0") & R.num.isin(OURS)]
T = con.execute(f"select \"Route code\" as rc, \"Trip code\" as trip, \"Direction of trip\" as dir from {rd(f('data-60665-*.csv'))}").df()
S = con.execute(f"select \"Stop code\" as stop, \"Stop name\" as sname, \"Centroid\" as cen from {rd(f('data-60662-*.csv'))}").df()
ST = con.execute(f"select \"Trip code\" as trip, \"Stop code\" as stop, try_cast(\"Number stop\" as int) as seq from {rd(f('data-60661-*.csv'))}").df()
ST = ST.dropna(subset=["seq"])
# пересадочность: число разных маршрутов (любой вид транспорта), обслуживающих остановку
st_rc = ST.merge(T[["trip", "rc"]], on="trip").drop_duplicates(["stop", "rc"]); nroutes = st_rc.groupby("stop").rc.nunique()
rows = []
for r in R.itertuples():
    tr = T[T.rc == r.rc]
    for d, g in tr.groupby("dir"):
        seqs = ST[ST.trip.isin(g.trip)].sort_values(["trip", "seq"]).groupby("trip").stop.apply(tuple)
        pattern = seqs.value_counts().index[0]; ntrips = len(g)                       # основной вариант рейса направления
        for i, s in enumerate(pattern):
            rows.append(dict(route=int(r.num), direction=str(d), seq=i + 1, stop=s, n_trips_dir=ntrips, last=(i == len(pattern) - 1)))
X = pd.DataFrame(rows).merge(S, on="stop", how="left")
X["lon"] = X.cen.str.extract(r"coordinates=\[([\d.]+)")[0].astype(float); X["lat"] = X.cen.str.extract(r"coordinates=\[[\d.]+, ([\d.]+)")[0].astype(float)
X["n_routes"] = X.stop.map(nroutes).fillna(1).astype(int); X["hub"] = X.sname.fillna("").str.contains(HUB)
X["w"] = (1 + 0.35 * X.n_routes.map(lambda n: math.log1p(n))) * X.hub.map({True: 1.5, False: 1.0}) * (~X["last"]).astype(float)
X["w"] = X.w / X.groupby(["route", "direction"]).w.transform("sum") * X.n_trips_dir / X.groupby("route").n_trips_dir.transform(lambda s: s.drop_duplicates().sum())
X["share"] = X.w / X.groupby("route").w.transform("sum")
out = X[["route", "direction", "seq", "stop", "sname", "lat", "lon", "n_routes", "hub", "last", "share"]].rename(columns={"sname": "stop_name"})
OUT.mkdir(exist_ok=True); out.to_csv(OUT / "stops.csv", index=False)
agg = out.groupby(["stop", "stop_name", "lat", "lon"], dropna=False).agg(routes=("route", lambda s: sorted(set(int(x) for x in s)))).reset_index()
gj = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [a.lon, a.lat]},
      "properties": {"stop": str(a.stop), "name": a.stop_name, "routes": a.routes}} for a in agg.itertuples() if pd.notna(a.lat)]}
(OUT / "stops.geojson").write_text(json.dumps(gj, ensure_ascii=False))
print("остановок-направлений:", len(out), "| уникальных остановок:", out.stop.nunique(), "| без координат:", int(out.lat.isna().sum()))
print(out.groupby("route").agg(остановок=("stop", "size"), направлений=("direction", "nunique"), пересадок_на_метро=("hub", "sum"), сумма_долей=("share", "sum")).round(3).to_string())
