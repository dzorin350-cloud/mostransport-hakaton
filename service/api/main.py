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

import io
import re
import uuid

import pandas as pd
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth import current_user, router as auth_router

# DATA_DIR — статические данные сервиса (геометрия маршрутов); STATE_DIR — прогноз, который публикует движок.
DATA = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
STATE = Path(os.environ.get("STATE_DIR", "/app/state"))
STARTUP_WAIT_S = float(os.environ.get("STARTUP_WAIT_S", "600"))

app = FastAPI(
    title="Прогноз пассажиропотока трамваев Москвы",
    description="Модель v7 (WAPE-score 0.88399) + годовая форма дня. Почасовой прогноз посадок, горизонт 12 месяцев.",
    version="2.0.0",
)
app.include_router(auth_router)
INGEST = Path(os.environ.get("INGEST_DIR", "/app/ingest"))


# ------------------------------------------------------------------ ошибки — понятные сообщения на русском
_ERR_RU = {
    "missing": "обязательный параметр не передан",
    "int_parsing": "нужно целое число",
    "float_parsing": "нужно число",
    "literal_error": "недопустимое значение",
    "greater_than": "значение должно быть больше",
    "greater_than_equal": "значение должно быть не меньше",
    "less_than_equal": "значение должно быть не больше",
    "json_invalid": "некорректный JSON",
}


@app.exception_handler(RequestValidationError)
async def _validation_ru(request: Request, exc: RequestValidationError):
    errs = []
    for e in exc.errors():
        field = ".".join(str(x) for x in e.get("loc", []) if x not in ("query", "body"))
        msg = _ERR_RU.get(e.get("type", ""), e.get("msg", "ошибка"))
        ctx = e.get("ctx") or {}
        if "expected" in ctx:
            msg += f" (допустимо: {str(ctx['expected']).replace(' or ', ', ')})"
        for k in ("gt", "ge", "le"):
            if k in ctx:
                msg += f" {ctx[k]}"
        errs.append({"параметр": field, "ошибка": msg})
    return JSONResponse(status_code=422, content={"detail": "некорректные параметры запроса", "errors": errs})


@app.exception_handler(StarletteHTTPException)
async def _http_ru(request: Request, exc: StarletteHTTPException):
    ru = {404: "адрес не найден", 405: "метод не поддерживается для этого адреса"}
    detail = ru.get(exc.status_code, exc.detail) if exc.detail in ("Not Found", "Method Not Allowed") else exc.detail
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def _server_ru(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "внутренняя ошибка сервиса, попробуйте повторить запрос позже"})


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
def model_info(user: str = Depends(current_user)) -> dict:
    """Как построен текущий прогноз: дата данных, горизонт, множители месяцев, источники внешних данных
    (live — скачано сейчас, cache — прошлая успешная загрузка, fallback — встроенная копия)."""
    FC.get()
    out = dict(FC.info)
    try:
        out["last_refresh"] = json.loads((STATE / "refresh_status.json").read_text())
    except (FileNotFoundError, ValueError):
        pass
    return out


@app.get("/routes")
def routes(user: str = Depends(current_user)) -> dict:
    return {"routes": ROUTES}


@app.get("/routes/geometry")
def routes_geometry(user: str = Depends(current_user)) -> dict:
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
        d0 = pd.to_datetime(date_from, format="%Y-%m-%d").date()
        d1 = pd.to_datetime(date_to, format="%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(400, f"неверный формат даты: нужно ГГГГ-ММ-ДД, получено «{date_from}» и «{date_to}»") from None
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
    user: str = Depends(current_user),
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
    user: str = Depends(current_user),
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


# --------------------------------------------------------------------------
# Приём данных: новые валидации → история → движок пересчитывает прогноз сам
# --------------------------------------------------------------------------

def _store(df: pd.DataFrame, kind: str, user: str) -> dict:
    df = df.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum()
    INGEST.mkdir(parents=True, exist_ok=True)
    name = f"ingest_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.csv"
    tmp = INGEST / (name + ".tmp")
    df.to_csv(tmp, sep=";", index=False)
    os.replace(tmp, INGEST / name)                     # движок видит файл только целиком
    return {"принято_строк": int(len(df)), "дат": sorted(df["date"].unique().tolist()), "файл": name, "тип": kind,
            "пользователь": user,
            "сообщение": "данные сохранены; движок подхватит их и пересчитает прогноз в течение ~1 минуты "
                         "(дата данных и горизонт — в /model/info)"}


def _check_new(df: pd.DataFrame) -> None:
    last = FC.info.get("data_until")
    if last and (df["date"] <= last).any():
        raise HTTPException(409, f"данные за {last} и ранее уже есть в истории; принимаются только даты после {last}")


@app.post("/ingest/hourly", tags=["Приём данных"], summary="Почасовые посадки: CSV route;date;hour;boardings")
def ingest_hourly(body: str = Body(..., media_type="text/csv"), user: str = Depends(current_user)) -> dict:
    try:
        df = pd.read_csv(io.StringIO(body), sep=";")
    except Exception as exc:
        raise HTTPException(400, f"не удалось прочитать CSV: {exc}") from exc
    need = {"route", "date", "hour", "boardings"}
    if not need <= set(df.columns):
        raise HTTPException(400, f"нужны колонки {sorted(need)} с разделителем «;», получены {list(df.columns)}")
    try:
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d")
        df["route"] = df["route"].astype(int); df["hour"] = df["hour"].astype(int); df["boardings"] = df["boardings"].astype(float)
    except Exception as exc:
        raise HTTPException(400, f"неверный формат значений (дата ГГГГ-ММ-ДД, route/hour — целые, boardings — число): {exc}") from exc
    if not df["hour"].between(0, 23).all() or (df["boardings"] < 0).any():
        raise HTTPException(400, "hour должен быть 0–23, boardings — не отрицательным")
    _check_new(df)
    return _store(df, "hourly", user)


@app.post("/ingest/validations", tags=["Приём данных"],
          summary="Сырые валидации в формате train.csv (разделитель «;»): агрегация на стороне сервиса")
def ingest_validations(body: str = Body(..., media_type="text/csv"), user: str = Depends(current_user)) -> dict:
    try:
        v = pd.read_csv(io.StringIO(body), sep=";", dtype=str, quoting=3)
    except Exception as exc:
        raise HTTPException(400, f"не удалось прочитать CSV: {exc}") from exc
    need = {"tran_date_time", "validation_result", "ngpt_route"}
    if not need <= set(v.columns):
        raise HTTPException(400, f"нужны колонки {sorted(need)} (как в train.csv)")
    n_all = len(v)
    v = v[v["validation_result"].str.strip() == "1"]                       # посадка = успешная валидация
    ts = pd.to_datetime(v["tran_date_time"], errors="coerce")
    route = v["ngpt_route"].str.extract(r"^(\d+)")[0]
    ok = ts.notna() & route.notna()
    df = pd.DataFrame({"route": route[ok].astype(int), "date": ts[ok].dt.strftime("%Y-%m-%d"), "hour": ts[ok].dt.hour, "boardings": 1.0})
    if df.empty:
        raise HTTPException(400, "нет успешных валидаций с корректной датой и маршрутом")
    _check_new(df)
    out = _store(df, "validations", user)
    out.update({"строк_во_входе": n_all, "успешных_валидаций": int(ok.sum())})
    return out


# --------------------------------------------------------------------------
# Остановки: ОЦЕНОЧНАЯ разбивка прогноза маршрута по остановкам (GTFS data.mos.ru, engine/build_stops.py)
# --------------------------------------------------------------------------
STOPS_PATH = Path(os.environ.get("STOPS_PATH", "/app/service/engine/artifacts/stops.csv"))
STOPS = pd.read_csv(STOPS_PATH) if STOPS_PATH.exists() else None
STOPS_NOTE = ("оценочная разбивка: пассажиропотока по остановкам в данных нет; прогноз маршрута распределён по остановкам "
              "расписания GTFS (data.mos.ru) с весами по пересадочности, жилью и точкам притяжения рядом (OpenStreetMap), "
              "отдельно для утра, дня, вечера и ночи; сумма по остановкам = прогнозу маршрута")
PERIOD_OF_HOUR = {h: ("morning" if 5 <= h <= 9 else "day" if 10 <= h <= 15 else "evening" if 16 <= h <= 20 else "night") for h in range(24)}


@app.get("/stops", tags=["Остановки"], summary="Остановки маршрутов (GeoJSON) для карты")
def stops(route: list[int] | None = Query(None), user: str = Depends(current_user)) -> dict:
    if STOPS is None:
        raise HTTPException(503, "справочник остановок не загружен")
    x = STOPS if not route else STOPS[STOPS.route.isin(route)]
    feats = []
    for (stop, name, lat, lon), g in x.groupby(["stop", "stop_name", "lat", "lon"]):
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {"stop": str(stop), "name": name, "routes": sorted(int(r) for r in g.route.unique())}})
    return {"type": "FeatureCollection", "features": feats, "note": STOPS_NOTE}


@app.get("/forecast/stops", tags=["Остановки"], summary="Прогноз посадок по остановкам (оценочная разбивка)")
def forecast_stops(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    route: list[int] | None = Query(None),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    coefficient: float = Query(1.0, gt=0, le=3.0),
    user: str = Depends(current_user),
) -> dict:
    if STOPS is None:
        raise HTTPException(503, "справочник остановок не загружен")
    src, mask = _slice(date_from, date_to)
    mask &= (src["hour"] >= hour_from) & (src["hour"] <= hour_to)
    if route:
        mask &= src["route"].isin(route)
    sl = src[mask]
    per = sl.assign(period=sl["hour"].map(PERIOD_OF_HOUR)).groupby(["route", "period"])["prediction"].sum() * coefficient
    tot = per.groupby(level=0).sum()
    x = STOPS[STOPS.route.isin(tot.index)].copy()
    has_periods = "share_morning" in x.columns
    x["prediction"] = 0.0
    for p in ("morning", "day", "evening", "night"):
        col = f"share_{p}" if has_periods else "share"
        x["prediction"] += x[col] * x["route"].map(lambda r, p=p: per.get((r, p), 0.0))
    x["prediction"] = x["prediction"].round(1)
    by_stop = (x.groupby(["stop", "stop_name", "lat", "lon"], as_index=False)
                .agg(prediction=("prediction", "sum"), routes=("route", lambda s: sorted({int(r) for r in s})))
                .sort_values("prediction", ascending=False))
    rows = by_stop.assign(stop=by_stop["stop"].astype(str)).to_dict(orient="records")
    return {"count": len(rows), "total_prediction": round(float(tot.sum()), 1), "note": STOPS_NOTE,
            "data_until": FC.info.get("data_until"), "rows": rows}
