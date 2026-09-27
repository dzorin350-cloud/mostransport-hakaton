"""Движок прогноза: применяет обученную модель v7 к истории валидаций и внешним данным.

Что делает refresh():
  1. читает историю (почасовые посадки маршрут × дата × час) и определяет дату последних данных;
  2. сам скачивает внешние данные (sources.py): производственный календарь и месячный пассажиропоток трамвая;
  3. очищает историю от аномалий (перекрытия, объединения маршрутов, сбои) — как в v7;
  4. считает уровень маршрута (последние 56 дней) и профиль (последние 2 недели);
  5. загружает 5 обученных моделей CatBoost (обучаются офлайн, train.py) и строит почасовой прогноз
     на 12 месяцев вперёд от даты данных:
       прогноз = уровень × форма дня (CatBoost + профиль) × сезонный множитель месяца;
     годовая часть: для месяцев, у которых в истории есть тот же месяц год назад, форма дня
     смешивается с формой того месяца (доля SHAPE_ALPHA).
Обучения здесь нет. Модели CatBoost — артефакты в artifacts/.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
import json
import logging
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from . import sources

log = logging.getLogger("engine")
HERE = Path(__file__).resolve().parent
FEATS = ["route", "hour", "dow", "off", "hol_wd", "pre", "post"]
COVID = pd.period_range("2020-03", "2021-06", freq="M")
RAIN_EFFECT = -0.025      # сильно дождливый день (3+ дневных срока с осадками): −2…−3 % посадок (бэктест: +0,65 пункта на таких днях)
RAIN_SLOTS = 3
SHAPE_ALPHA = 0.5          # доля формы дня «тот же месяц год назад» (годовая модель, бэктест +1,2 пункта)
HORIZON_MONTHS = 12
import os as _os
# forecast — прод: настоящий прогноз погоды на 16 дней вперёд от сегодняшнего дня;
# demo — ТОЛЬКО ДЕМОНСТРАЦИЯ на стенде со старыми данными: фактическая погода из архива за первые 16 дней горизонта.
WEATHER_MODE = _os.environ.get("WEATHER_MODE", "forecast")


# ============================================================================ календарь
class Calendar:
    """Производственный календарь по кодам isdayoff (0 рабочий, 1 выходной, 2 сокращённый)."""

    def __init__(self, codes: dict):
        self.codes = codes
        # праздничные блоки: непрерывные серии нерабочих дней, в которых есть хотя бы один нерабочий будний день
        days = sorted(codes)
        self.holidays: set = set()
        run: list = []
        for d in days + [None]:
            if d is not None and codes[d] == "1":
                run.append(d); continue
            if run and any(x.weekday() < 5 for x in run):
                self.holidays.update(run)
            run = []

    def is_off(self, d) -> bool:
        return self.codes.get(d, "1" if d.weekday() >= 5 else "0") == "1"

    def working_weekends(self, d0, d1) -> list:
        return [d for d in pd.date_range(d0, d1).date if d.weekday() >= 5 and not self.is_off(d)]

    def features(self, dates) -> pd.DataFrame:
        """Признаки дня, как в v7: dow, off, hol_wd, pre, post."""
        ds = pd.to_datetime(pd.Series(pd.unique(pd.Series(dates))))
        c = pd.DataFrame({"date": ds})
        c["dow"] = c.date.dt.dayofweek
        d = c.date.dt.date
        c["off"] = [int(self.is_off(x)) for x in d]
        c["hol_wd"] = [int(self.is_off(x) and x.weekday() < 5) for x in d]
        nxt = [int(self.is_off(x + dt.timedelta(1)) or (x + dt.timedelta(1)).weekday() >= 5) for x in d]
        prv = [int(self.is_off(x - dt.timedelta(1)) or (x - dt.timedelta(1)).weekday() >= 5) for x in d]
        c["pre"] = ((np.array(nxt) == 1) & (c.off == 0)).astype(int)
        c["post"] = ((np.array(prv) == 1) & (c.off == 0)).astype(int)
        return c

    def daytype(self, dates: pd.Series) -> np.ndarray:
        """Тип дня для очистки и форм: hol (праздничный блок), wd, sat, sun."""
        d = dates.dt.date
        dow = dates.dt.dayofweek
        hol = np.array([x in self.holidays for x in d])
        return np.where(hol, "hol", np.where(dow < 5, "wd", np.where(dow == 5, "sat", "sun")))


# ============================================================================ очистка (как v7)
def clean_history(tr: pd.DataFrame, cal: Calendar, thr=1.5, wk_thr=0.15) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = tr.groupby(["route", "date"]).boardings.sum().reset_index()
    d["dt"] = cal.daytype(d.date)
    mask = pd.Series(False, index=d.index)
    w = d[d.dt == "wd"].copy(); w["wk"] = w.date.dt.to_period("W").dt.start_time
    sh = w.groupby(["wk", "route"]).boardings.sum().unstack(); sh = sh.div(sh.sum(1), axis=0); rel = sh / sh.median()
    badwk = rel.stack(); badwk = badwk[(badwk - 1).abs() > wk_thr].reset_index()[["wk", "route"]]
    d["wk"] = d.date.dt.to_period("W").dt.start_time
    mw = d.merge(badwk.assign(b=1), on=["wk", "route"], how="left").b.fillna(0).values == 1
    mask |= pd.Series(mw, index=d.index)
    d["exp"] = np.nan
    for _ in range(2):
        for (_r, _t), g in d[d.dt != "hol"].groupby(["route", "dt"]):
            v = g.boardings.where(~mask[g.index])
            d.loc[g.index, "exp"] = v.rolling(11, center=True, min_periods=3).median().ffill().bfill()
        rr = d.boardings / d.exp
        mask |= ((rr > thr) | (rr < 1 / thr)) & (d.dt != "hol")
    d["m"] = mask
    t = tr.merge(d[["route", "date", "dt", "m", "exp"]], on=["route", "date"])
    tot = t.groupby(["route", "date"]).boardings.transform("sum"); t["sh"] = t.boardings / tot.replace(0, np.nan)
    shp = t[~t.m].groupby(["route", "dt", "hour"]).sh.mean().rename("shp").reset_index()
    t = t.merge(shp, on=["route", "dt", "hour"], how="left")
    t["boardings"] = np.where(t.m, t.exp * t.shp.fillna(0), t.boardings)
    return t[["route", "date", "hour", "boardings"]].sort_values(["route", "date", "hour"]).reset_index(drop=True), d


# ============================================================================ движок
class Engine:
    def __init__(self, history_dir, artifacts_dir: Path = HERE / "artifacts",
                 cache_dir: Path = Path("/tmp/tram_engine_cache"), fetch: bool = True, until: str | None = None,
                 weather: bool = True):
        dirs = history_dir if isinstance(history_dir, (list, tuple)) else [history_dir]
        self.history_dirs = [Path(d) for d in dirs]
        self.artifacts_dir, self.cache_dir, self.fetch = Path(artifacts_dir), Path(cache_dir), fetch
        self.until = pd.Timestamp(until) if until else None
        self.weather = weather                                  # False — без поправки на дождь (архивные прогнозы для демо)     # обрезка истории: прогноз «как если бы данные были только до этой даты»
        self.config = json.loads((self.artifacts_dir / "config.json").read_text())
        self.routes_all = self.config["routes_all"]
        self.models = []
        for f in self.config["models"]:
            m = CatBoostRegressor(); m.load_model(str(self.artifacts_dir / f)); self.models.append(m)
        self.table: pd.DataFrame | None = None
        self.info: dict = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- история
    def load_history(self) -> pd.DataFrame:
        files = sorted(f for d in self.history_dirs if d.exists() for f in d.glob("*.csv"))
        if not files:
            raise RuntimeError(f"нет истории в {self.history_dirs}")
        h = pd.concat([pd.read_csv(f, sep=";") for f in files], ignore_index=True)
        h["date"] = pd.to_datetime(h["date"])
        if self.until is not None:
            h = h[h.date <= self.until]
        h = h.groupby(["route", "date", "hour"], as_index=False).boardings.sum()
        days = pd.date_range(h.date.min(), h.date.max())
        g = pd.MultiIndex.from_product([self.routes_all, days, range(24)], names=["route", "date", "hour"]).to_frame(index=False)
        g = g.merge(h, how="left", on=["route", "date", "hour"]); g["boardings"] = g.boardings.fillna(0)
        self.history_files = [f.name for f in files]
        return g[g.route.isin(self.config["routes_model"])].reset_index(drop=True)

    # ---------------------------------------------------------------- множители месяцев
    @staticmethod
    def month_multipliers(rid: pd.DataFrame, origin: pd.Period, horizon: int) -> dict:
        s = pd.Series(rid.pax.values / [_cal.monthrange(y, m)[1] for y, m in zip(rid.year, rid.month)],
                      index=pd.PeriodIndex([f"{y}-{m:02d}" for y, m in zip(rid.year, rid.month)], freq="M"))
        out = {}
        for k in range(1, horizon + 1):
            rs = []
            for y in range(2019, origin.year):
                b = pd.Period(f"{y}-{origin.month:02d}", "M")
                if y != 2020 and b in s.index and b + k in s.index and (b + k) not in COVID:
                    rs.append(s[b + k] / s[b])
            if rs:
                out[origin + k] = float(np.mean(rs))
        return out

    # ---------------------------------------------------------------- основной пересчёт
    def refresh(self) -> dict:
        t0 = time.perf_counter()
        p = self.config["params"]
        hist = self.load_history()
        data_until = hist.date.max().date()
        origin = pd.Period(data_until, "M")
        if data_until != (origin.end_time.date()):          # неполный месяц — прогноз начинается со следующего дня
            log.warning("последний месяц истории неполный: %s", data_until)
        h_start = data_until + dt.timedelta(1)
        h_end = (origin + HORIZON_MONTHS).end_time.date()
        years = sorted(set(range(hist.date.min().year - 1, h_end.year + 2)))
        codes, cal_status = (sources.fetch_calendar(years, self.cache_dir) if self.fetch
                             else sources.fetch_calendar(years, self.cache_dir, timeout=0.001))
        cal = Calendar(codes)
        # городская статистика — только по последний ПОЛНЫЙ месяц истории (иначе в месячный итог попадают дни, которых у модели ещё нет)
        last_full = data_until if data_until == origin.end_time.date() else (origin - 1).end_time.date()
        rid, rid_status = sources.fetch_ridership(last_full, self.cache_dir, timeout=20 if self.fetch else 0.001)
        # база множителей — последний месяц с городскими данными (при неполном текущем месяце это прошлый месяц)
        base = min(pd.Period(last_full, "M"), pd.Period(f"{int(rid.year.iloc[-1])}-{int(rid.month.iloc[-1]):02d}", "M"))
        mult = self.month_multipliers(rid, base, (origin + HORIZON_MONTHS - base).n)
        tr, flags = clean_history(hist, cal)
        L = tr[tr.date > pd.Timestamp(data_until) - pd.Timedelta(days=p["lvl"])].groupby("route").boardings.sum() / p["lvl"]
        pt = tr[tr.date > pd.Timestamp(data_until) - pd.Timedelta(weeks=p["weeks"])].merge(cal.features(tr.date), on="date")
        PR = pt[pt.hol_wd == 0].groupby(["route", "dow", "hour"]).boardings.mean().rename("p").reset_index()
        # формы дня по месяцам истории (для годовой части)
        th = tr.copy(); th["dt"] = cal.daytype(th.date); th["ym"] = th.date.dt.to_period("M")
        tot = th.groupby(["route", "date"]).boardings.transform("sum"); th["sh"] = th.boardings / tot.replace(0, np.nan)
        ndays = th.groupby("ym").date.nunique()
        full_months = set(ndays[ndays >= 20].index)
        MS = th[th.ym.isin(full_months)].groupby(["route", "ym", "dt", "hour"]).sh.mean()

        months_missing = [str(p) for p in pd.period_range(pd.Period(h_start, "M"), pd.Period(h_end, "M"), freq="M") if p not in mult]
        if months_missing:
            raise RuntimeError(f"нет сезонных множителей для {months_missing}")

        days = pd.date_range(h_start, h_end)
        F = pd.MultiIndex.from_product([self.config["routes_model"], days, range(24)], names=["route", "date", "hour"]).to_frame(index=False)
        C = cal.features(days)

        def pred(frb: pd.DataFrame) -> np.ndarray:
            f = frb.date.dt.to_period("M").map(mult).values.astype(float)
            X = frb[FEATS].copy(); X["route"] = X.route.astype(int)
            cb = np.mean([np.clip(m.predict(X), 0, None) for m in self.models], axis=0) * frb.route.map(L).values * f
            pf = frb.merge(PR, on=["route", "dow", "hour"], how="left").p.fillna(0).values * f
            w = np.where(frb.dow.values >= 5, 0.8, 0.6)
            return np.where(frb.hol_wd.values == 1, cb, w * cb + (1 - w) * pf)

        Fb = F.merge(C, on="date")
        Fb["prediction"] = pred(Fb)
        for d in cal.working_weekends(h_start, h_end):                   # перенос: среднее прогнозов пятницы и субботы
            n = Fb.date.dt.date.eq(d); fri = Fb[n].copy(); fri["dow"] = 4; fri["off"] = 0
            sat = Fb[n].copy(); sat["dow"] = 5; sat["off"] = 1
            Fb.loc[n, "prediction"] = 0.5 * pred(fri) + 0.5 * pred(sat)

        # годовая часть: форма дня «тот же месяц год назад»
        Fb["dt"] = cal.daytype(Fb.date); Fb["ym_prev"] = (Fb.date.dt.to_period("M") - 12)
        ww = set(cal.working_weekends(h_start, h_end))
        elig = Fb.ym_prev.isin(full_months) & ~Fb.date.dt.date.isin(ww)
        blended_months = sorted({str(x + 12) for x in Fb.loc[elig, "ym_prev"].unique()})
        if elig.any():
            key = pd.MultiIndex.from_arrays([Fb.route, Fb.ym_prev, Fb.dt, Fb.hour])
            shm = pd.Series(MS.reindex(key).values, index=Fb.index)
            key_sun = pd.MultiIndex.from_arrays([Fb.route, Fb.ym_prev, np.where(Fb.dt == "hol", "sun", Fb.dt), Fb.hour])
            shm = shm.fillna(pd.Series(MS.reindex(key_sun).values, index=Fb.index))
            day = Fb.groupby(["route", "date"]).prediction.transform("sum")
            model_sh = Fb.prediction / day.replace(0, np.nan)
            ok = elig & shm.notna() & model_sh.notna()
            mix = SHAPE_ALPHA * shm + (1 - SHAPE_ALPHA) * model_sh
            mix = mix.where(ok)
            norm = mix.groupby([Fb.route, Fb.date]).transform("sum")
            Fb.loc[ok, "prediction"] = (day * mix / norm)[ok]

        # поправка на сильный дождь по прогнозу погоды (только ближайшие дни, где прогноз есть; сухие дни не меняются)
        if not self.weather:
            rain_slots, rain_status = {}, {"mode": "off", "note": "поправка на погоду выключена"}
        elif WEATHER_MODE == "demo":
            demo_end = min(h_start + dt.timedelta(days=15), h_end)
            rain_slots, rain_status = sources.fetch_rain_archive(h_start, demo_end, timeout=20 if self.fetch else 0.001)
            rain_status["mode"] = "demo"
            rain_status["note"] = ("ДЕМОНСТРАЦИЯ: данные стенда старые, настоящего прогноза погоды на даты горизонта нет, поэтому для первых "
                                   "16 дней горизонта взята фактическая погода из архива. В проде — прогноз погоды; в сабмите погода не используется.")
        else:
            rain_slots, rain_status = sources.fetch_rain_forecast(timeout=15 if self.fetch else 0.001)
            rain_status["mode"] = "forecast"
        heavy = sorted(d for d, n in rain_slots.items() if n >= RAIN_SLOTS and h_start <= d <= h_end)
        if heavy:
            m = Fb.date.dt.date.isin(set(heavy))
            Fb.loc[m, "prediction"] = Fb.loc[m, "prediction"] * (1 + RAIN_EFFECT)

        out = Fb[["route", "date", "hour", "prediction"]].copy()
        zero_routes = [r for r in self.routes_all if r not in self.config["routes_model"]]
        if zero_routes:
            z = pd.MultiIndex.from_product([zero_routes, days, range(24)], names=["route", "date", "hour"]).to_frame(index=False)
            out = pd.concat([out, z.assign(prediction=0.0)])
        out["prediction"] = out.prediction.round(1).clip(lower=0)
        out = out.sort_values(["route", "date", "hour"]).reset_index(drop=True)
        out["date"] = out.date.dt.date

        info = {
            "model_version": self.config["model_version"],
            "data_until": str(data_until),
            "history_files": self.history_files,
            "horizon": {"start": str(h_start), "end": str(h_end)},
            "month_multipliers": {str(k): round(v, 4) for k, v in mult.items() if k >= pd.Period(h_start, "M")},
            "multiplier_base_month": str(base),
            "year_shape_months": blended_months,
            "year_shape_alpha": SHAPE_ALPHA,
            "cleaned_route_days": int(flags.m.sum()),
            "rain_adjusted_days": [str(d) for d in heavy],
            "rain_slots_by_day": {str(d): int(n) for d, n in sorted(rain_slots.items()) if h_start <= d <= h_end},
            "rain_effect": RAIN_EFFECT,
            "route_levels_per_day": {int(k): round(float(v), 1) for k, v in L.items()},
            "sources": {"calendar": cal_status, "ridership": rid_status, "rain_forecast": rain_status},
            "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "compute_seconds": round(time.perf_counter() - t0, 1),
        }
        with self._lock:
            self.table, self.info = out, info
        log.info("прогноз пересчитан: %s строк, %s с", len(out), info["compute_seconds"])
        return info
