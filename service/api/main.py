"""REST API прогноза пассажиропотока трамваев Москвы.

Архитектурное решение: прогноз ПРЕДРАССЧИТАН моделью v7 (см. ../v7/code/)
и лежит в data/*.csv. API не запускает ML на каждый запрос — только
фильтрует и агрегирует готовую сетку в памяти. Причины:

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

# DATA_DIR переопределяется в Docker (см. Dockerfile: COPY data /app/data),
# где main.py и data/ лежат на одном уровне, в отличие от локальной
# структуры репозитория (api/main.py, ../data).
DATA = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))

app = FastAPI(
    title="Прогноз пассажиропотока трамваев Москвы",
    description="Модель v7 (WAPE-score 0.88399). Почасовой прогноз посадок по 9 маршрутам.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Загрузка прогноза в память при старте процесса
# --------------------------------------------------------------------------


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["prediction"] = df["prediction"].astype(float)
    return df


FORECAST_MONTH = _load(DATA / "forecast_nov_dec.csv")
FORECAST_YEAR = _load(DATA / "forecast_year.csv")
ROUTES_GEOJSON = json.loads((DATA / "routes.geojson").read_text())
ROUTES = sorted(FORECAST_YEAR["route"].unique().tolist())

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
    return {"status": "ok", "uptime_s": round(time.monotonic() - _boot_time, 1)}


@app.get("/metrics")
def metrics() -> dict:
    avg = _latency_sum_ms / _request_count if _request_count else 0.0
    return {
        "requests_served": _request_count,
        "avg_latency_ms": round(avg, 3),
        "uptime_s": round(time.monotonic() - _boot_time, 1),
        "model": "v7 (CatBoost x5 + профиль, сезонный множитель data.mos.ru)",
        "leaderboard_wape_score": 0.88399,
    }


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


def _pick_source(date_from: str, date_to: str) -> pd.DataFrame:
    d0, d1 = pd.Timestamp(date_from).date(), pd.Timestamp(date_to).date()
    month_min, month_max = FORECAST_MONTH["date"].min(), FORECAST_MONTH["date"].max()
    if d0 >= month_min and d1 <= month_max:
        return FORECAST_MONTH
    return FORECAST_YEAR


@app.get("/forecast")
def forecast(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    route: list[int] | None = Query(None, description="Фильтр по маршрутам, можно несколько"),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    granularity: Literal["hour", "day", "month"] = Query(
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
    try:
        d0 = pd.Timestamp(date_from).date()
        d1 = pd.Timestamp(date_to).date()
    except ValueError as exc:
        raise HTTPException(400, f"неверный формат даты: {exc}") from exc
    if d0 > d1:
        raise HTTPException(400, "date_from должна быть раньше date_to")

    src = _pick_source(date_from, date_to)
    mask = (src["date"] >= d0) & (src["date"] <= d1)
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
    else:
        df["month"] = [f"{d.year}-{d.month:02d}" for d in df["date"]]
        g = df.groupby(["route", "month"])["prediction"].sum().reset_index()
        rows = g.to_dict(orient="records")

    return {
        "count": len(rows),
        "coefficient_applied": coefficient,
        "total_prediction": round(df["prediction"].sum(), 1),
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
    d0 = pd.Timestamp(date_from).date()
    d1 = pd.Timestamp(date_to).date()
    src = _pick_source(date_from, date_to)
    mask = (src["date"] >= d0) & (src["date"] <= d1)
    if route:
        mask &= src["route"].isin(route)
    df = src[mask].copy()
    df["prediction"] = (df["prediction"] * coefficient).round(1)
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
