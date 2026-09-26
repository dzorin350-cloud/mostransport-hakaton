"""Архив наблюдений метеостанции Москва-ВДНХ (WMO 27612) с pogodaiklimat.ru («Погода и климат»), шаг 3 часа.
Сохраняет сырые наблюдения и суточные признаки. Только период до даты последних данных модели (без утечки)."""
import calendar, io, sys, time, subprocess
import pandas as pd, numpy as np
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
def month(y, m):
    last = calendar.monthrange(y, m)[1]
    url = f"http://www.pogodaiklimat.ru/weather.php?id=27612&bday=1&fday={last}&amonth={m}&ayear={y}&bot=2"
    html = subprocess.run(["curl", "-s", "-m", "60", "-A", "Mozilla/5.0", url], capture_output=True).stdout.decode("utf-8", "replace")
    t = pd.read_html(io.StringIO(html))
    a, b = t[0].iloc[1:].reset_index(drop=True), t[1].iloc[1:].reset_index(drop=True)
    b.columns = ["wind_dir", "wind", "vis", "phen", "cloud", "T", "Td", "f", "Te", "Tes", "comfort", "P", "Po", "Tmin", "Tmax", "R", "R24", "S"][: b.shape[1]]
    d = pd.DataFrame({"hh": a[0].astype(int), "dm": a[1].astype(str)})
    d["day"] = d.dm.str.split(".").str[0].astype(int); d["month"] = d.dm.str.split(".").str[1].astype(int)
    d = pd.concat([d, b], axis=1); d["year"] = y
    d = d[d.month == m]
    d["ts_utc"] = pd.to_datetime(dict(year=d.year, month=d.month, day=d.day, hour=d.hh))
    return d.drop(columns=["dm"])
frames = []
for y in range(2022, 2026):
    for m in range(1, 13):
        if (y, m) > (2025, 10): break
        for k in range(3):
            try: frames.append(month(y, m)); break
            except Exception as e: time.sleep(2); err = e
        else: print("не скачано", y, m, err)
        time.sleep(0.3)
raw = pd.concat(frames, ignore_index=True).drop_duplicates("ts_utc").sort_values("ts_utc")
raw.to_csv(f"{OUT}/pogodaiklimat_27612_raw_2022-01_2025-10.csv", index=False)
num = lambda s: pd.to_numeric(s.astype(str).str.replace("+", "", regex=False).str.replace("−", "-"), errors="coerce")
raw["T"] = num(raw["T"]); raw["R"] = num(raw["R"]); raw["S"] = num(raw["S"])
raw["ts"] = raw.ts_utc + pd.Timedelta(hours=3)                       # московское время
ph = raw.phen.fillna("").str.lower()
raw["rain"] = ph.str.contains("дожд|ливен|ливн|морос").astype(int); raw["snow"] = ph.str.contains("снег|метел|крупа").astype(int)
day = raw.set_index("ts").between_time("06:00", "21:00").groupby(lambda x: x.normalize())
D = pd.DataFrame({"t_mean": raw.groupby(raw.ts.dt.normalize())["T"].mean(),
                  "t_min": raw.groupby(raw.ts.dt.normalize())["T"].min(),
                  "precip_mm": raw.groupby(raw.ts_utc.dt.normalize())["R"].sum(min_count=1),
                  "rain_obs_day": day["rain"].sum(), "snow_obs_day": day["snow"].sum(),
                  "snow_depth_cm": raw.groupby(raw.ts.dt.normalize())["S"].max()})
D.index.name = "date"; D.to_csv(f"{OUT}/pogodaiklimat_27612_daily_2022-01_2025-10.csv")
print(raw.shape, D.shape, D.index.min().date(), D.index.max().date()); print(D.describe().round(2).to_string())
