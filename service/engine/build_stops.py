"""Оценочная разбивка прогноза маршрута по остановкам с учётом времени суток и окружения остановки.

Источники: GTFS data.mos.ru (60661 stop_times, 60662 stops, 60664 routes, 60665 trips) — остановки и их порядок;
OpenStreetMap (osm_context.py → artifacts/osm_stop_context.csv) — жилые дома (сумма этажей) и точки притяжения
(офисы, вузы, школы, больницы, ТЦ) в радиусе 400 м.
Пассажиропотока по остановкам в данных нет, поэтому разбивка ОЦЕНОЧНАЯ, коэффициенты заданы экспертно, не обучены:
  базовый вес      b = 1 + 0,35·ln(1 + число маршрутов через остановку)
  жильё            r = R / (R + медиана R),  притяжение a = A / (A + медиана A)   (0…1)
  утро   5–9 ч:    b·(1 + 0,6·r)·(1,3 у пересадок на метро/МЦК/МЦД/вокзалы)·(1,25 направление в центр, 0,8 из центра)
  день  10–15 ч:   b·(1 + 0,6·a)·(1,4 у пересадок)
  вечер 16–20 ч:   b·(1 + 0,6·a)·(1,6 у пересадок)·(1,25 направление из центра, 0,8 в центр)
  ночь  21–4 ч:    b·(1,5 у пересадок)
  конечная направления — 0; направления — пропорционально числу рейсов; доли нормированы по маршруту в каждом периоде.
Сумма долей по маршруту в каждом периоде = 1 → сумма по остановкам равна прогнозу маршрута.

    python -m service.engine.build_stops <каталог CSV data.mos.ru> → artifacts/stops.csv, stops.geojson
"""
import json, math, re, sys
from pathlib import Path
import duckdb, numpy as np, pandas as pd
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
X["base"] = 1 + 0.35 * X.n_routes.map(lambda n: math.log1p(n))
ctx_path = OUT / "osm_stop_context.csv"
if ctx_path.exists():
    ctx = pd.read_csv(ctx_path, dtype={"stop": str})[["stop", "res_floors_400m", "attractors_400m"]]
    X = X.merge(ctx, on="stop", how="left").fillna({"res_floors_400m": 0, "attractors_400m": 0})
else:
    X["res_floors_400m"] = 0.0; X["attractors_400m"] = 0.0
r = X.res_floors_400m / (X.res_floors_400m + max(X.res_floors_400m.median(), 1))
a = X.attractors_400m / (X.attractors_400m + max(X.attractors_400m.median(), 1))
# направление «в центр»: конечная направления ближе к Кремлю, чем начальная
KR = (55.7520, 37.6175); dist = lambda la, lo: math.hypot(la - KR[0], (lo - KR[1]) * 0.56)
ends = X.sort_values("seq").groupby(["route", "direction"]).agg(la0=("lat", "first"), lo0=("lon", "first"), la1=("lat", "last"), lo1=("lon", "last"))
ends["inbound"] = [dist(r_.la1, r_.lo1) < dist(r_.la0, r_.lo0) for r_ in ends.itertuples()]
X = X.merge(ends[["inbound"]].reset_index(), on=["route", "direction"])
hub, alive = X.hub.astype(bool), (~X["last"]).astype(float)
# вес остановки внутри направления (по периоду) и множитель направления (утром больше едут в центр, вечером — из центра)
PER = {"morning": (X.base * (1 + 0.6 * r) * np.where(hub, 1.3, 1), np.where(X.inbound, 1.25, 0.8)),
       "day": (X.base * (1 + 0.6 * a) * np.where(hub, 1.4, 1), np.ones(len(X))),
       "evening": (X.base * (1 + 0.6 * a) * np.where(hub, 1.6, 1), np.where(X.inbound, 0.8, 1.25)),
       "night": (X.base * np.where(hub, 1.5, 1), np.ones(len(X)))}
trips = X.groupby(["route", "direction"]).n_trips_dir.transform("first")
tot_trips = X.drop_duplicates(["route", "direction"]).groupby("route").n_trips_dir.sum()
for k, (w, dirf) in PER.items():
    w = w * alive
    w = w / w.groupby([X.route, X.direction]).transform("sum")                   # доли внутри направления
    w = w * trips / X.route.map(tot_trips) * dirf                                 # доля направления: рейсы × поправка на час пик
    X[f"share_{k}"] = w / w.groupby(X.route).transform("sum")
X["share"] = X[[f"share_{k}" for k in PER]].mean(axis=1)          # средняя доля (для справки)
out = X[["route", "direction", "seq", "stop", "sname", "lat", "lon", "n_routes", "hub", "last", "inbound", "res_floors_400m", "attractors_400m",
           "share_morning", "share_day", "share_evening", "share_night", "share"]].rename(columns={"sname": "stop_name"})
OUT.mkdir(exist_ok=True); out.to_csv(OUT / "stops.csv", index=False)
agg = out.groupby(["stop", "stop_name", "lat", "lon"], dropna=False).agg(routes=("route", lambda s: sorted(set(int(x) for x in s)))).reset_index()
gj = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [a.lon, a.lat]},
      "properties": {"stop": str(a.stop), "name": a.stop_name, "routes": a.routes}} for a in agg.itertuples() if pd.notna(a.lat)]}
(OUT / "stops.geojson").write_text(json.dumps(gj, ensure_ascii=False))
print("остановок-направлений:", len(out), "| уникальных остановок:", out.stop.nunique(), "| без координат:", int(out.lat.isna().sum()))
print(out.groupby("route").agg(остановок=("stop", "size"), в_центр=("inbound", "mean"), утро=("share_morning", "sum"), день=("share_day", "sum"), вечер=("share_evening", "sum"), ночь=("share_night", "sum")).round(3).to_string())
