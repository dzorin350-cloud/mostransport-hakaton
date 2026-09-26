"""REST API прогноза пассажиропотока трамваев Москвы.

Архитектурное решение: прогноз строит сам сервис. Фоновый процесс
(service/engine/refresher.py) применяет обученную модель v7 к истории
валидаций и внешним данным, которые сам скачивает (календарь isdayoff.ru,
сезонность data.mos.ru), и публикует почасовой прогноз на 12 месяцев вперёд
в STATE_DIR/forecast.parquet. Воркеры API держат его в памяти и
перечитывают при обновлении. На каждый HTTP-запрос ML не запускается —
только фильтр и агрегация готовой сетки. Причины:

1. ТЗ хакатона требует высокую пропускную способность (сотни RPS,
   p95 < 200-300 мс) на 2-4 vCPU / 2-4 ГБ RAM. Инференс CatBoost на 14 640
   строк с признаками — это дольше, чем простой pandas-фильтр по сетке,
   уже лежащей в памяти процесса.
2. Прогноз пересчитывается пакетно (раз в неделю или при поступлении
   новых данных валидаций) — это описано в README как штатный режим
   переобучения модели v7. Между переобучениями прогноз статичен, и
   вызывать дорогой пайплайн на каждый HTTP-запрос бессмысленно.
3. Корректирующие коэффициенты (сезон/событие/погода) применяются
   МНОЖИТЕЛЕМ поверх готового прогноза — ARCHITECTURE.md прямо называет
   это следствием мультипликативной структуры модели. Для этого тоже не
   нужен повторный инференс, только арифметика над числом.

Эндпоинты см. README.md сервиса.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# DATA_DIR — статические данные сервиса (геометрия маршрутов); STATE_DIR — прогноз, который публикует движок.
DATA = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
STATE = Path(os.environ.get("STATE_DIR", "/app/state"))
STARTUP_WAIT_S = float(os.environ.get("STARTUP_WAIT_S", "600"))

app = FastAPI(
    title="Прогноз пассажиропотока трамваев Москвы",
    description="Модель v7 (WAPE-score 0.88399) + годовая форма дня. Почасовой прогноз посадок, горизонт 12 месяцев.",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class _Forecast:
    """Прогноз в памяти воркера; перечитывается, когда движок публикует новую версию."""

    def __init__(self) -> None:
        self.df: pd.DataFrame | None = None
        self.info: dict = {}
        self._mtime = 0.0
        self._checked = 0.0

    def _load(self) -> None:
        df = pd.read_parquet(STATE / "forecast.parquet")
        ts = pd.to_datetime(df["date"])
        df = df.assign(_d=(ts - pd.Timestamp("1970-01-01")).dt.days.astype("int32"))
        df = df.sort_values(["_d", "route", "hour"], kind="stable").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["_d"], unit="D").dt.date
        df["prediction"] = df["prediction"].astype(float)
        self.days = df["_d"].to_numpy()          # отсортировано — диапазон дат ищется двоичным поиском
        self.info = json.loads((STATE / "info.json").read_text())
        self.df = df
        self._mtime = (STATE / "forecast.parquet").stat().st_mtime

    def wait_first(self) -> None:
        t0 = time.monotonic()
        while not (STATE / "forecast.parquet").exists():
            if time.monotonic() - t0 > STARTUP_WAIT_S:
                raise RuntimeError("движок не опубликовал прогноз")
            time.sleep(1)
        self._load()

    def get(self) -> pd.DataFrame:
        now = time.monotonic()
        if now - self._checked > 30:          # не чаще раза в 30 с проверяем, не вышла ли новая версия
            self._checked = now
            try:
                if (STATE / "forecast.parquet").stat().st_mtime != self._mtime:
                    self._load()
            except FileNotFoundError:
                pass
        return self.df


FC = _Forecast()
FC.wait_first()
ROUTES_GEOJSON = json.loads((DATA / "routes.geojson").read_text())
ROUTES = sorted(r for r in FC.df["route"].unique().tolist() if FC.df.loc[FC.df.route == r, "prediction"].sum() > 0)

_boot_time = time.monotonic()
_request_count = 0
_latency_sum_ms = 0.0


@app.middleware("http")
async def _timing(request, call_next):
    global _request_count, _latency_sum_ms
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _request_count += 1
    _latency_sum_ms += elapsed_ms
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


# --------------------------------------------------------------------------
# /health, /metrics
# --------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    FC.get()
    return {"status": "ok", "uptime_s": round(time.monotonic() - _boot_time, 1),
            "data_until": FC.info.get("data_until"), "computed_at": FC.info.get("computed_at")}


@app.get("/metrics")
def metrics() -> dict:
    FC.get()
    avg = _latency_sum_ms / _request_count if _request_count else 0.0
    return {
        "requests_served": _request_count,
        "avg_latency_ms": round(avg, 3),
        "uptime_s": round(time.monotonic() - _boot_time, 1),
        "model": FC.info.get("model_version"),
        "leaderboard_wape_score": 0.88399,
        "data_until": FC.info.get("data_until"),
        "forecast_computed_at": FC.info.get("computed_at"),
    }


@app.get("/model/info")
def model_info() -> dict:
    """Как построен текущий прогноз: дата данных, горизонт, множители месяцев, источники внешних данных
    (live — скачано сейчас, cache — прошлая успешная загрузка, fallback — встроенная копия)."""
    FC.get()
    return FC.info


@app.get("/routes")
def routes() -> dict:
    return {"routes": ROUTES}


@app.get("/routes/geometry")
def routes_geometry() -> dict:
    """GeoJSON геометрии маршрутов (OpenStreetMap, CC-BY-SA).

    Источник: Overpass API, relation route=tram, ref в {1,7,11,12,17,25,26,28,50}.
    Маршрут 5 не включён: у нас 5 — пустой маршрут без реальных рейсов (0
    строк в train.csv), поэтому геометрии для него в датасете нет.
    """
    return ROUTES_GEOJSON


# --------------------------------------------------------------------------
# /forecast — основной эндпоинт
# --------------------------------------------------------------------------


def _slice(date_from: str, date_to: str):
    try:
        d0, d1 = pd.Timestamp(date_from).date(), pd.Timestamp(date_to).date()
    except ValueError as exc:
        raise HTTPException(400, f"неверный формат даты: {exc}") from exc
    if d0 > d1:
        raise HTTPException(400, "date_from должна быть раньше date_to")
    h = FC.info["horizon"]
    if str(d0) < h["start"] or str(d1) > h["end"]:
        raise HTTPException(400, f"прогноз доступен на {h['start']} … {h['end']} (12 месяцев от даты данных {FC.info['data_until']})")
    src = FC.get()
    days = src["_d"].to_numpy()               # из той же версии таблицы (безопасно при горячей перезагрузке)
    lo = days.searchsorted((pd.Timestamp(d0) - pd.Timestamp("1970-01-01")).days, side="left")
    hi = days.searchsorted((pd.Timestamp(d1) - pd.Timestamp("1970-01-01")).days, side="right")
    sub = src.iloc[lo:hi]
    return sub, pd.Series(True, index=sub.index)


@app.get("/forecast")
def forecast(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    route: list[int] | None = Query(None, description="Фильтр по маршрутам, можно несколько"),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    granularity: Literal["hour", "day", "week", "month"] = Query(
        "hour", description="Уровень агрегации ответа"
    ),
    coefficient: float = Query(1.0, gt=0, le=3.0, description="Корректирующий множитель"),
) -> dict:
    """Прогноз посадок по фильтрам.

    coefficient — тот самый корректирующий коэффициент из критерия ТЗ
    "область адаптации модели": пользователь может смоделировать сценарий
    (похолодание, закрытие параллельной ветки метро, разовое событие) без
    переобучения — множитель применяется поверх готового прогноза.
    """
    src, mask = _slice(date_from, date_to)
    mask &= (src["hour"] >= hour_from) & (src["hour"] <= hour_to)
    if route:
        mask &= src["route"].isin(route)
    df = src[mask].copy()
    df["prediction"] = (df["prediction"] * coefficient).round(1)

    if granularity == "hour":
        out = df[["route", "date", "hour", "prediction"]].copy()
        out["date"] = out["date"].astype(str)
        rows = out.to_dict(orient="records")
    elif granularity == "day":
        g = df.groupby(["route", "date"])["prediction"].sum().reset_index()
        g["date"] = g["date"].astype(str)
        rows = g.to_dict(orient="records")
    elif granularity == "week":
        df["week"] = [str(d - pd.Timedelta(days=d.weekday())) for d in df["date"]]   # понедельник недели
        g = df.groupby(["route", "week"])["prediction"].sum().reset_index()
        rows = g.to_dict(orient="records")
    else:
        df["month"] = [f"{d.year}-{d.month:02d}" for d in df["date"]]
        g = df.groupby(["route", "month"])["prediction"].sum().reset_index()
        rows = g.to_dict(orient="records")

    return {
        "count": len(rows),
        "coefficient_applied": coefficient,
        "total_prediction": round(df["prediction"].sum(), 1),
        "data_until": FC.info.get("data_until"),
        "model_version": FC.info.get("model_version"),
        "rows": rows,
    }


@app.get("/forecast/export")
def forecast_export(
    date_from: str = Query(...),
    date_to: str = Query(...),
    route: list[int] | None = Query(None),
    fmt: Literal["csv", "xlsx"] = Query("csv"),
    coefficient: float = Query(1.0, gt=0, le=3.0),
) -> Response:
    """Выгрузка прогноза в CSV или XLSX (критерий ТЗ п.4: экспорт данных)."""
    src, mask = _slice(date_from, date_to)
    if route:
        mask &= src["route"].isin(route)
    df = src[mask].copy()
    df["prediction"] = (df["prediction"] * coefficient).round(1)
    df = df.drop(columns="_d").sort_values(["route", "date", "hour"])
    df["date"] = df["date"].astype(str)

    if fmt == "csv":
        body = df.to_csv(sep=";", index=False)
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="forecast_{date_from}_{date_to}.csv"'},
        )

    import io

    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="forecast_{date_from}_{date_to}.xlsx"'},
    )
