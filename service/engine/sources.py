"""Внешние данные, которые сервис скачивает сам.

1. Производственный календарь РФ — isdayoff.ru (открытый API без ключа).
2. Месячный пассажиропоток трамвая Москвы — data.mos.ru, набор 62521.
   Берутся только месяцы не позже даты последних фактических данных (защита от утечки будущего).

Порядок для каждого источника: интернет → кэш прошлой успешной загрузки → встроенная копия (fallback/).
Откуда реально взяты данные, записывается в статус и отдаётся в API (/model/info).
"""
from __future__ import annotations

import calendar
import datetime as dt
import io
import json
import logging
import ssl
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

log = logging.getLogger("engine.sources")
HERE = Path(__file__).resolve().parent
FALLBACK = HERE / "fallback"
MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
             "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _CTX = ssl.create_default_context()


def _get(url: str, timeout: float) -> bytes:
    """GET с жёстким общим лимитом времени (включая DNS и повторные попытки соединения)."""
    import concurrent.futures as cf
    def go():
        req = urllib.request.Request(url, headers={"User-Agent": "tram-forecast/1.0"})
        return urllib.request.urlopen(req, timeout=timeout, context=_CTX).read()
    ex = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(go).result(timeout=timeout + 1)
    except cf.TimeoutError as exc:
        raise TimeoutError(f"нет ответа за {timeout} с: {url}") from exc
    finally:
        ex.shutdown(wait=False)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- календарь
def fetch_calendar(years: list[int], cache_dir: Path, timeout: float = 15) -> tuple[dict, dict]:
    """→ ({date: код}, статус по годам). Код isdayoff: 0 — рабочий, 1 — выходной, 2 — сокращённый рабочий."""
    codes, status = {}, {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    for y in years:
        s, src = None, None
        try:
            txt = _get(f"https://isdayoff.ru/api/getdata?year={y}&pre=1", timeout).decode().strip()
            if len(txt) == (366 if calendar.isleap(y) else 365) and set(txt) <= set("0124"):
                s, src = txt, "live"
                (cache_dir / f"cal_{y}.txt").write_text(txt)
        except Exception as exc:  # сеть недоступна — идём в кэш
            log.warning("isdayoff %s: %s", y, exc)
        for path, name in ((cache_dir / f"cal_{y}.txt", "cache"), (FALLBACK / f"cal_{y}.txt", "fallback")):
            if s is None and path.exists():
                s, src = path.read_text().strip(), name
        if s is None:
            raise RuntimeError(f"нет производственного календаря на {y} год (ни в сети, ни в кэше)")
        start = dt.date(y, 1, 1)
        for i, c in enumerate(s):
            codes[start + dt.timedelta(days=i)] = c
        status[str(y)] = src
    return codes, {"source": "isdayoff.ru", "years": status, "fetched_at": _now()}


# --------------------------------------------------------------------------- сезонность
def _parse_62521(raw: bytes) -> pd.DataFrame:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    except zipfile.BadZipFile:
        pass
    txt = raw.decode("utf-8-sig")
    if txt.lstrip().startswith("["):
        d = pd.read_json(io.StringIO(txt))
        d = d.rename(columns={"Year": "year", "Month": "month_ru", "TypeOfTransport": "type", "PassengerTraffic": "pax"})
    else:  # CSV выгрузка: вторая строка — русские заголовки
        d = pd.read_csv(io.StringIO(txt), sep=";").iloc[1:]
        d = d.rename(columns={"Year": "year", "Month": "month_ru", "Type of transport": "type", "Passenger traffic": "pax"})
    d = d[d["type"].astype(str).str.strip() == "Трамвай"].copy()
    d["year"] = d["year"].astype(int)
    d["month"] = d["month_ru"].map({m: i + 1 for i, m in enumerate(MONTHS_RU)})
    d["pax"] = pd.to_numeric(d["pax"])
    return d[["year", "month", "pax"]].dropna().astype({"month": int}).sort_values(["year", "month"])


def fetch_ridership(cutoff: dt.date, cache_dir: Path, timeout: float = 20) -> tuple[pd.DataFrame, dict]:
    """→ (year, month, pax) по трамваю, только месяцы <= cutoff; статус."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "ridership_tram_monthly.csv"
    d, src, err = None, None, None
    try:
        meta = json.loads((FALLBACK / "meta_62521.json").read_text())
        for item in meta.get("data", [])[:1]:               # самая свежая выгрузка
            try:
                d = _parse_62521(_get(item["source"], timeout)); src = "live"; break
            except Exception as exc:
                err = exc
        if d is not None:
            d.to_csv(cache, index=False)
    except Exception as exc:
        err = exc
    if d is None:
        log.warning("data.mos.ru 62521 недоступен: %s", err)
        for path, name in ((cache, "cache"), (FALLBACK / "ridership_tram_monthly.csv", "fallback")):
            if d is None and path.exists():
                d, src = pd.read_csv(path), name
    if d is None:
        raise RuntimeError("нет данных о месячном пассажиропотоке трамвая")
    n_all = len(d)
    d = d[(d.year < cutoff.year) | ((d.year == cutoff.year) & (d.month <= cutoff.month))].reset_index(drop=True)
    last = f"{int(d.year.iloc[-1])}-{int(d.month.iloc[-1]):02d}"
    return d, {"source": "data.mos.ru/opendata/62521", "origin": src, "rows_total": n_all,
               "rows_used": len(d), "last_month_used": last, "cutoff": str(cutoff), "fetched_at": _now()}


# --------------------------------------------------------------------------- прогноз погоды
def fetch_rain_forecast(timeout: float = 15) -> tuple[dict, dict]:
    """Прогноз осадков на 16 дней (Open-Meteo, без ключа) → {дата: число дневных сроков 6,9,12,15,18,21 ч с осадками ≥ 0,1 мм}.
    Мера та же, что при оценке эффекта по метеостанции Москва-ВДНХ (число дневных сроков с дождём)."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude=55.83&longitude=37.63&hourly=precipitation"
           "&timezone=Europe%2FMoscow&forecast_days=16")
    try:
        h = json.loads(_get(url, timeout))["hourly"]
        df = pd.DataFrame({"t": pd.to_datetime(h["time"]), "p": h["precipitation"]})
        df = df[df.t.dt.hour.isin([6, 9, 12, 15, 18, 21])]
        slots = (df.p.fillna(0) >= 0.1).groupby(df.t.dt.date).sum().astype(int).to_dict()
        return slots, {"source": "open-meteo.com (прогноз)", "origin": "live", "days": len(slots), "fetched_at": _now()}
    except Exception as exc:
        log.warning("прогноз погоды недоступен: %s", exc)
        return {}, {"source": "open-meteo.com (прогноз)", "origin": "недоступен", "error": str(exc)[:200], "fetched_at": _now()}


def _slots(times, precip) -> dict:
    df = pd.DataFrame({"t": pd.to_datetime(times), "p": precip})
    df = df[df.t.dt.hour.isin([6, 9, 12, 15, 18, 21])]
    return (df.p.fillna(0) >= 0.1).groupby(df.t.dt.date).sum().astype(int).to_dict()


def fetch_rain_archive(start, end, timeout: float = 20) -> tuple[dict, dict]:
    """ТОЛЬКО ДЛЯ ДЕМОНСТРАЦИИ: фактические осадки из архива Open-Meteo за даты горизонта вместо прогноза.
    Используется на стенде, где данные старые и настоящего прогноза погоды на даты горизонта нет. В сабмите не используется."""
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude=55.83&longitude=37.63&start_date={start}&end_date={end}"
           "&hourly=precipitation&timezone=Europe%2FMoscow")
    try:
        h = json.loads(_get(url, timeout))["hourly"]
        s = _slots(h["time"], h["precipitation"])
        return s, {"source": "archive-api.open-meteo.com (фактическая погода)", "origin": "live", "days": len(s), "fetched_at": _now()}
    except Exception as exc:
        log.warning("архив погоды недоступен: %s", exc)
        return {}, {"source": "archive-api.open-meteo.com", "origin": "недоступен", "error": str(exc)[:200], "fetched_at": _now()}
