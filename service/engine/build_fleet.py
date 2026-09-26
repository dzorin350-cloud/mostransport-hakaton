"""Нормы выпуска вагонов для оценки загрузки и рекомендации выпуска (artifacts/fleet_norms.csv).

Источник — сырые валидации (train.csv, test.csv): число разных вагонов (garage_number) с успешными валидациями
на маршруте в каждый час — оценка вагонов в работе; посадок на вагон в час = посадки / вагоны.
  veh_typ  — обычное число вагонов: медиана за последние 8 недель по (маршрут, тип дня, час)
  bpv_p75  — «комфортная» загрузка маршрута: 75-й процентиль посадок на вагон в час (будни 7–20 ч, вся история)
  bpv_p90  — «высокая» загрузка: 90-й процентиль; выше — риск переполнения
Проверка (обучение до 31.08, прогноз сен–окт): рекомендация «не выше p75» совпадает с потребностью по фактическому спросу
(пик 676 против 674 вагоно-часов, межпик 734 против 702); риск переполнения — полнота 0,63, точность 0,45 (docs/TESTS.md).

    python -m service.engine.build_fleet <supply_hourly.parquet | каталог с train.csv и test.csv>
"""
import sys
from pathlib import Path
import duckdb, numpy as np, pandas as pd
ART = Path(__file__).resolve().parent / "artifacts"
src = Path(sys.argv[1])
if src.suffix == ".parquet":
    S = pd.read_parquet(src)[["route", "date", "hour", "veh", "ok"]]
else:
    q = f"""select cast(regexp_extract(ngpt_route,'^(\\d+)',1) as int) as route, cast(cast(tran_date_time as timestamp) as date) as date,
             hour(cast(tran_date_time as timestamp)) as hour, count(distinct garage_number) as veh, count(*) as ok
            from read_csv(['{src}/train.csv','{src}/test.csv'], delim=';', header=true, all_varchar=true, quote='', strict_mode=false, ignore_errors=true)
            where validation_result='1' group by 1,2,3"""
    S = duckdb.connect().execute(q).df()
S["date"] = pd.to_datetime(S.date); S = S[S.route.isin([1, 7, 11, 12, 17, 25, 26, 28, 50])]
cal = pd.read_csv(ART.parent / "fallback" / "cal_2025.txt", header=None) if False else None
codes = open(ART.parent / "fallback" / "cal_2025.txt").read().strip(); off = {pd.Timestamp("2025-01-01") + pd.Timedelta(days=i) for i, c in enumerate(codes) if c == "1"}
dow = S.date.dt.dayofweek
S["dt"] = np.where(S.date.isin(off) & (dow < 5), "hol", np.where(dow < 5, "wd", np.where(dow == 5, "sat", "sun")))
S["bpv"] = S.ok / S.veh.replace(0, np.nan)
end = S.date.max()
last = S[S.date > end - pd.Timedelta(weeks=8)]
N = last.groupby(["route", "dt", "hour"]).veh.median().rename("veh_typ").reset_index()
pk = S[(S.dt == "wd") & S.hour.between(7, 20) & (S.date >= "2025-01-09")].groupby("route").bpv
TH = pd.DataFrame({"bpv_p75": pk.quantile(0.75), "bpv_p90": pk.quantile(0.90)}).reset_index()
out = N.merge(TH, on="route"); out["norms_until"] = str(end.date())
ART.mkdir(exist_ok=True); out.to_csv(ART / "fleet_norms.csv", index=False)
print(out.groupby("route").agg(veh_8h_wd=("veh_typ", lambda s: s.max()), bpv_p75=("bpv_p75", "first"), bpv_p90=("bpv_p90", "first")).round(0).to_string())
