"""REST API прогноза пассажиропотока трамваев Москвы.

Архитектурное решение: прогноз строит сам сервис. Фоновый процесс
(service/engine/refresher.py) применяет обученную итоговую модель к истории
валидаций и внешним данным, которые сам скачивает (календарь isdayoff.ru,
сезонность data.mos.ru), и публикует почасовой прогноз на 12 месяцев вперёд
в STATE_DIR/versions/<id>/forecast.parquet. Воркеры API держат его в памяти и
перечитывают при обновлении. На каждый HTTP-запрос ML не запускается —
только фильтр и агрегация готовой сетки. Причины:

1. ТЗ хакатона требует высокую пропускную способность (сотни RPS,
   p95 < 200-300 мс) на 2-4 vCPU / 2-4 ГБ RAM. Инференс CatBoost на 14 640
   строк с признаками — это дольше, чем простой pandas-фильтр по сетке,
   уже лежащей в памяти процесса.
2. Прогноз пересчитывается пакетно (раз в неделю или при поступлении
   новых данных валидаций) — это описано в README как штатный режим
   переобучения модели. Между переобучениями прогноз статичен, и
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

import datetime as dt
import io
import hashlib
from functools import lru_cache
import re

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from auth import current_user, router as auth_router
from store import list_decisions, log_ingest, save_decision

# DATA_DIR — статические данные сервиса (геометрия маршрутов); STATE_DIR — прогноз, который публикует движок.
DATA = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
STATE = Path(os.environ.get("STATE_DIR", "/app/state"))
STARTUP_WAIT_S = float(os.environ.get("STARTUP_WAIT_S", "600"))

app = FastAPI(
    title="Прогноз пассажиропотока трамваев Москвы",
    description="Итоговая модель (WAPE-score 0.88399) + годовая форма дня. Почасовой прогноз посадок, горизонт 12 месяцев.",
    version="2.0.0",
)
app.include_router(auth_router)
INGEST = Path(os.environ.get("INGEST_DIR", "/app/ingest"))
MAX_INGEST_BYTES = int(os.environ.get("MAX_INGEST_BYTES", str(10 * 1024 * 1024)))


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
        self.version = ""

    def _load(self) -> None:
        pointer = STATE / "current.json"
        version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
        if not re.fullmatch(r"[0-9]+-[a-f0-9]{8}", version):
            raise RuntimeError("некорректная версия прогноза")
        directory = STATE / "versions" / version
        df = pd.read_parquet(directory / "forecast.parquet")
        info = json.loads((directory / "info.json").read_text(encoding="utf-8"))
        ts = pd.to_datetime(df["date"])
        df = df.assign(_d=(ts - pd.Timestamp("1970-01-01")).dt.days.astype("int32"))
        df = df.sort_values(["_d", "route", "hour"], kind="stable").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["_d"], unit="D").dt.date
        df["prediction"] = df["prediction"].astype(float)
        self.days = df["_d"].to_numpy()          # отсортировано — диапазон дат ищется двоичным поиском
        self.info = info
        self.df = df
        self.version = version
        self._mtime = pointer.stat().st_mtime_ns

    def wait_first(self) -> None:
        t0 = time.monotonic()
        while not (STATE / "current.json").exists():
            if time.monotonic() - t0 > STARTUP_WAIT_S:
                raise RuntimeError("движок не опубликовал прогноз")
            time.sleep(1)
        self._load()

    def get(self) -> pd.DataFrame:
        now = time.monotonic()
        if now - self._checked > 30:          # не чаще раза в 30 с проверяем, не вышла ли новая версия
            self._checked = now
            try:
                if (STATE / "current.json").stat().st_mtime_ns != self._mtime:
                    self._load()
            except FileNotFoundError:
                pass
        return self.df


FC = _Forecast()
FC.wait_first()
ROUTES_GEOJSON = json.loads((DATA / "routes.geojson").read_text(encoding="utf-8"))
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


@app.get("/ready")
def ready() -> dict:
    FC.get()
    try:
        status = json.loads((STATE / "refresh_status.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        raise HTTPException(503, "прогноз ещё не опубликован или статус пересчёта недоступен") from None
    if not status.get("ok"):
        raise HTTPException(503, "последний пересчёт прогноза не удался; действует предыдущая версия")
    return {"status": "ready", "version": FC.version, "computed_at": FC.info.get("computed_at")}


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
    out["now_mode"] = NOW_MODE
    out["demo_today"] = (DEMO_TODAY or FC.info["horizon"]["start"]) if NOW_MODE == "demo" else None
    try:
        out["last_refresh"] = json.loads((STATE / "refresh_status.json").read_text(encoding="utf-8"))
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


INTERVALS = pd.read_csv(Path(os.environ.get("INTERVALS_PATH", "/app/service/engine/artifacts/interval_factors.csv")))
INTERVAL_NOTE = ("lo–hi — коридор 80 %: в 8 из 10 случаев факт попадал в эти границы на бэктестах того же горизонта "
                 "(проверка покрытия на отложенном периоде: часы 78–83 %, дни 82–89 %)")


_INT_TABLES: dict = {}


def _interval(level: str, start) -> tuple:
    """Множители коридора по детализации и числу дней от даты данных до начала строки."""
    base = pd.Timestamp(FC.info["data_until"]).date()
    t = _INT_TABLES.get(level)
    if t is None:
        t = _INT_TABLES[level] = INTERVALS[INTERVALS.level == level].sort_values("days_from")[["days_to", "lo", "hi"]].to_numpy()
    start = pd.Series(start)
    uniq = start.unique()                                   # дат в ответе мало — считаем горизонт только для уникальных
    ahead_u = np.array([max((d - base).days, 1) for d in uniq])
    idx_u = np.searchsorted(t[:, 0], ahead_u, side="left").clip(0, len(t) - 1)
    pos = pd.Index(uniq).get_indexer(start)
    idx = idx_u[pos]
    return t[idx, 1], t[idx, 2]


def _slice(date_from: str, date_to: str):
    try:
        d0 = pd.to_datetime(date_from, format="%Y-%m-%d").date()
        d1 = pd.to_datetime(date_to, format="%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(400, f"неверный формат даты: нужно ГГГГ-ММ-ДД, получено «{date_from}» и «{date_to}»") from None
    if d0 > d1:
        raise HTTPException(400, "date_from должна быть раньше date_to")
    src = FC.get()
    h = FC.info["horizon"]
    if str(d0) < h["start"] or str(d1) > h["end"]:
        raise HTTPException(400, f"прогноз доступен на {h['start']} … {h['end']} (12 месяцев от даты данных {FC.info['data_until']})")
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
        out = df[["route", "date", "hour", "prediction"]].copy(); start = out["date"]
    elif granularity == "day":
        out = df.groupby(["route", "date"])["prediction"].sum().reset_index(); start = out["date"]
    elif granularity == "week":
        df["week"] = [d - pd.Timedelta(days=d.weekday()) for d in df["date"]]   # понедельник недели
        out = df.groupby(["route", "week"])["prediction"].sum().reset_index(); start = out["week"]
    else:
        df["month"] = [f"{d.year}-{d.month:02d}" for d in df["date"]]
        out = df.groupby(["route", "month"])["prediction"].sum().reset_index(); start = pd.to_datetime(out["month"] + "-01").dt.date
    lo, hi = _interval(granularity, start)
    out["lo"] = (out["prediction"] * lo).round(1); out["hi"] = (out["prediction"] * hi).round(1)
    for col in ("date", "week"):
        if col in out:
            out[col] = out[col].astype(str)
    rows = out.to_dict(orient="records")

    return {
        "count": len(rows),
        "coefficient_applied": coefficient,
        "total_prediction": round(df["prediction"].sum(), 1),
        "data_until": FC.info.get("data_until"),
        "model_version": FC.info.get("model_version"),
        "interval": INTERVAL_NOTE,
        "rows": rows,
    }


@app.get("/forecast/export")
def forecast_export(
    date_from: str = Query(...),
    date_to: str = Query(...),
    route: list[int] | None = Query(None),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    fmt: Literal["csv", "xlsx"] = Query("csv"),
    coefficient: float = Query(1.0, gt=0, le=3.0),
    user: str = Depends(current_user),
) -> Response:
    """Выгрузка прогноза в CSV или XLSX (критерий ТЗ п.4: экспорт данных)."""
    src, mask = _slice(date_from, date_to)
    mask &= (src["hour"] >= hour_from) & (src["hour"] <= hour_to)
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
    df = df.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum().sort_values(["route", "date", "hour"])
    INGEST.mkdir(parents=True, exist_ok=True)
    payload = df.to_csv(sep=";", index=False)
    name = f"ingest_{hashlib.sha256(payload.encode()).hexdigest()[:24]}.csv"
    # Serialize writers from all uvicorn workers. The lock is released by the OS on a crash.
    with (INGEST / ".write.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if (INGEST / name).exists():
                log_ingest(name, user, kind, len(df))
                return {"принято_строк": 0, "повтор": True, "файл": name, "сообщение": "этот пакет уже принят"}
            incoming = set(zip(df.route, df.date, df.hour))
            for old in INGEST.glob("ingest_*.csv"):
                prior = pd.read_csv(old, sep=";", usecols=["route", "date", "hour"])
                if incoming.intersection(zip(prior.route, prior.date, prior.hour)):
                    raise HTTPException(409, f"часы из пакета уже загружены в {old.name}; повторное суммирование запрещено")
            tmp = INGEST / (name + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, INGEST / name)             # движок видит файл только целиком
        finally:
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
    log_ingest(name, user, kind, len(df))
    return {"принято_строк": int(len(df)), "дат": sorted(df["date"].unique().tolist()), "файл": name, "тип": kind,
            "пользователь": user,
            "сообщение": "данные сохранены; движок подхватит их и пересчитает прогноз в течение ~1 минуты "
                         "(дата данных и горизонт — в /model/info)"}


def _check_new(df: pd.DataFrame) -> None:
    if df.empty:
        raise HTTPException(400, "пакет пуст")
    if not set(df.route.unique()).issubset(set(ROUTES)):
        raise HTTPException(400, f"неизвестный маршрут; допустимы {ROUTES}")
    last = FC.info.get("data_until")
    if last and (df["date"] <= last).any():
        raise HTTPException(409, f"данные за {last} и ранее уже есть в истории; принимаются только даты после {last}")


async def _ingest_body(request: Request) -> str:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_INGEST_BYTES:
            raise HTTPException(413, f"файл слишком велик; максимум {MAX_INGEST_BYTES // 1048576} МБ")
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "CSV должен быть в UTF-8") from None


@app.post("/ingest/hourly", tags=["Приём данных"], summary="Почасовые посадки: CSV route;date;hour;boardings")
async def ingest_hourly(request: Request, user: str = Depends(current_user)) -> dict:
    body = await _ingest_body(request)
    return await run_in_threadpool(_ingest_hourly_sync, body, user)


def _ingest_hourly_sync(body: str, user: str) -> dict:
    try:
        df = pd.read_csv(io.StringIO(body), sep=";")
    except Exception as exc:
        raise HTTPException(400, f"не удалось прочитать CSV: {exc}") from exc
    need = {"route", "date", "hour", "boardings"}
    if not need <= set(df.columns):
        raise HTTPException(400, f"нужны колонки {sorted(need)} с разделителем «;», получены {list(df.columns)}")
    try:
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d")
        for col in ("route", "hour"):
            numbers = pd.to_numeric(df[col], errors="raise")
            if not np.isfinite(numbers).all() or not (numbers == np.floor(numbers)).all():
                raise ValueError(f"{col} должен быть целым числом")
            df[col] = numbers.astype(int)
        df["boardings"] = df["boardings"].astype(float)
    except Exception as exc:
        raise HTTPException(400, f"неверный формат значений (дата ГГГГ-ММ-ДД, route/hour — целые, boardings — число): {exc}") from exc
    if not df["hour"].between(0, 23).all() or not np.isfinite(df["boardings"]).all() or (df["boardings"] < 0).any():
        raise HTTPException(400, "hour должен быть 0–23, boardings — конечным неотрицательным числом")
    _check_new(df)
    return _store(df, "hourly", user)


@app.post("/ingest/validations", tags=["Приём данных"],
          summary="Сырые валидации в формате train.csv (разделитель «;»): агрегация на стороне сервиса")
async def ingest_validations(request: Request, user: str = Depends(current_user)) -> dict:
    body = await _ingest_body(request)
    return await run_in_threadpool(_ingest_validations_sync, body, user)


def _ingest_validations_sync(body: str, user: str) -> dict:
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
    FC.get()
    return _stops_cached(FC.version, date_from, date_to, tuple(route or ()), hour_from, hour_to, coefficient)


@lru_cache(maxsize=256)
def _stops_cached(version: str, date_from: str, date_to: str, route: tuple[int, ...],
                  hour_from: int, hour_to: int, coefficient: float) -> dict:
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


# --------------------------------------------------------------------------
# Загрузка вагонов и рекомендация выпуска (engine/build_fleet.py → artifacts/fleet_norms.csv)
# --------------------------------------------------------------------------
FLEET_PATH = Path(os.environ.get("FLEET_PATH", "/app/service/engine/artifacts/fleet_norms.csv"))
FLEET = pd.read_csv(FLEET_PATH) if FLEET_PATH.exists() else None
FLEET_NOTE = ("вагонов в работе — оценка по числу вагонов с валидациями в этот час (последние 8 недель); загрузка — посадок на вагон в час "
              "относительно истории маршрута: «риск переполнения» — выше 90-го процентиля, рекомендация — минимум вагонов, чтобы не "
              "превышать 75-й процентиль. Посадки ≠ наполненность салона (выходов в данных нет) — это относительная оценка.")


def _daytype(dates) -> list:
    """Тип дня по производственному календарю (кэш движка, иначе встроенная копия): hol — праздничный будний, wd, sat, sun."""
    out = []
    for d in pd.to_datetime(pd.Series(dates).astype(str)):
        if d.year not in _CAL:
            here = Path(__file__).resolve().parent            # /app в контейнере, service/api в репозитории
            cands = [STATE / "cache", here / "service" / "engine" / "fallback", here.parent / "engine" / "fallback"]
            f = next((c / f"cal_{d.year}.txt" for c in cands if (c / f"cal_{d.year}.txt").exists()), None)
            _CAL[d.year] = f.read_text().strip() if f else ""
        codes = _CAL[d.year]
        c = codes[d.dayofyear - 1] if len(codes) >= d.dayofyear else ("1" if d.dayofweek >= 5 else "0")
        if c == "1" and d.dayofweek < 5:
            out.append("hol")
        elif d.dayofweek < 5 or c in ("0", "2"):          # рабочий выходной (перенос) — выпуск по будничному графику
            out.append("wd")
        else:
            out.append("sat" if d.dayofweek == 5 else "sun")
    return out


_CAL: dict = {}


def _fleet_frame(date_from, date_to, route=None, hour_from=0, hour_to=23, coefficient=1.0, min_share=0.6) -> pd.DataFrame:
    """Прогноз посадок с коридором, загрузкой вагона, статусом и рекомендацией выпуска по (маршрут, дата, час)."""
    FC.get()
    return _fleet_cached(FC.version, date_from, date_to, tuple(route or ()), hour_from, hour_to,
                         coefficient, min_share).copy()


@lru_cache(maxsize=256)
def _fleet_cached(version, date_from, date_to, route, hour_from, hour_to, coefficient, min_share) -> pd.DataFrame:
    if FLEET is None:
        raise HTTPException(503, "нормы выпуска не загружены")
    src, mask = _slice(date_from, date_to)
    mask &= (src["hour"] >= hour_from) & (src["hour"] <= hour_to) & src["route"].isin(FLEET.route.unique())
    if route:
        mask &= src["route"].isin(route)
    df = src[mask][["route", "date", "hour", "prediction"]].copy()
    df["prediction"] = df["prediction"] * coefficient
    lo, hi = _interval("hour", df["date"]); df["lo"] = df.prediction * lo; df["hi"] = df.prediction * hi
    days = sorted(df["date"].unique()); dt_map = dict(zip(days, _daytype(days)))
    df["dt"] = df["date"].map(dt_map)
    # норм для праздничных будней нет (мало таких дней в истории) — выпуск в праздник по воскресному графику
    df["norm_dt"] = df["dt"].replace({"hol": "sun"})
    df = df.merge(FLEET.rename(columns={"dt": "norm_dt"}), on=["route", "norm_dt", "hour"], how="left")
    df["veh_typ"] = df["veh_typ"].fillna(0)
    df["bpv"] = np.where(df.veh_typ > 0, df.prediction / df.veh_typ.replace(0, np.nan), np.nan)
    df["load_index"] = df.bpv / df.bpv_p90
    df["status"] = np.where(df.load_index > 1.0, "риск переполнения", np.where(df.load_index > 0.85, "повышенная", "норма"))
    # минимум вагонов, чтобы загрузка не превышала 75-й процентиль маршрута; не меньше min_share обычного выпуска
    # (интервалы не растут больше чем в ~1,7 раза при 0,6) — операционное ограничение
    df["veh_recommended"] = np.maximum(np.ceil(df.prediction / df.bpv_p75), np.ceil(df.veh_typ * min_share)).clip(lower=1)
    df["veh_delta"] = df.veh_recommended - df.veh_typ
    return df


@app.get("/fleet", tags=["Выпуск вагонов"], summary="Загрузка вагонов и рекомендация выпуска по часам")
def fleet(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    route: list[int] | None = Query(None),
    hour_from: int = Query(5, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    coefficient: float = Query(1.0, gt=0, le=3.0),
    min_share: float = Query(0.6, ge=0, le=1.0, description="минимальная доля обычного выпуска в рекомендации"),
    user: str = Depends(current_user),
) -> dict:
    df = _fleet_frame(date_from, date_to, route, hour_from, hour_to, coefficient, min_share)
    out = df.assign(date=df["date"].astype(str), prediction=df.prediction.round(1), bpv=df.bpv.round(1), load_index=df.load_index.round(2))
    rows = out[["route", "date", "hour", "prediction", "veh_typ", "bpv", "load_index", "status", "veh_recommended", "veh_delta"]].to_dict(orient="records")
    summ = out.groupby("route").agg(vehicle_hours_typical=("veh_typ", "sum"), vehicle_hours_recommended=("veh_recommended", "sum"),
                                    hours_overload_risk=("status", lambda s: int((s == "риск переполнения").sum()))).reset_index()
    return {"count": len(rows), "note": FLEET_NOTE, "data_until": FC.info.get("data_until"),
            "summary": summ.to_dict(orient="records"),
            "total": {"vehicle_hours_typical": float(summ.vehicle_hours_typical.sum()), "vehicle_hours_recommended": float(summ.vehicle_hours_recommended.sum()),
                      "hours_overload_risk": int(summ.hours_overload_risk.sum())},
            "rows": rows}


def _plan_data(date_from: str, date_to: str, route: list[int] | None, coefficient: float,
               min_share: float) -> tuple[pd.DataFrame, dict]:
    try:
        start, end = pd.Timestamp(dt.date.fromisoformat(date_from)), pd.Timestamp(dt.date.fromisoformat(date_to))
    except ValueError:
        raise HTTPException(400, "даты плана должны быть в формате ГГГГ-ММ-ДД") from None
    if (end - start).days > 6:
        raise HTTPException(400, "план выпуска доступен максимум на 7 дней за один запрос")
    df = _fleet_frame(date_from, date_to, route, 5, 23, coefficient, min_share)
    if df.empty:
        raise HTTPException(404, "нет данных для плана на выбранный период")
    rain_days = set(FC.info.get("rain_adjusted_days", []))
    def reason(x):
        d = str(x.date)
        if d in rain_days:
            return "сильный дождь; поправка уже учтена в базовом прогнозе"
        if x.dt == "hol":
            return "праздничный день"
        if coefficient != 1:
            return f"сценарий ×{coefficient:g}"
        if x.veh_delta > 0:
            return "спрос выше обычного для этого часа"
        if x.veh_delta < 0:
            return "спрос ниже обычного для этого часа"
        return "выпуск без изменений"
    df["reason"] = [reason(x) for x in df.itertuples()]
    df["risk_before"] = df["prediction"] / df["veh_typ"].replace(0, np.nan) > df["bpv_p90"]
    df["risk_after"] = df["prediction"] / df["veh_recommended"].replace(0, np.nan) > df["bpv_p90"]
    total = {
        "vehicle_hours_typical": float(df.veh_typ.sum()),
        "vehicle_hours_recommended": float(df.veh_recommended.sum()),
        "vehicle_hours_delta": float(df.veh_delta.sum()),
        "risk_route_hours_before": int(df.risk_before.sum()),
        "risk_route_hours_after_estimate": int(df.risk_after.sum()),
        "risk_route_hours_reduced_estimate": int(df.risk_before.sum() - df.risk_after.sum()),
    }
    return df, total


@app.get("/plan", tags=["План выпуска"], summary="План выпуска вагонов на 1–7 дней")
def plan(date_from: str = Query(...), date_to: str = Query(...), route: list[int] | None = Query(None),
         coefficient: float = Query(1.0, gt=0, le=3), min_share: float = Query(0.6, ge=0, le=1),
         user: str = Depends(current_user)) -> dict:
    FC.get()
    return _plan_cached(FC.version, date_from, date_to, tuple(route or ()), coefficient, min_share)


@lru_cache(maxsize=64)
def _plan_cached(version: str, date_from: str, date_to: str, route: tuple[int, ...],
                 coefficient: float, min_share: float) -> dict:
    df, total = _plan_data(date_from, date_to, list(route) if route else None, coefficient, min_share)
    cols = ["route", "date", "hour", "prediction", "lo", "hi", "veh_typ", "veh_recommended", "veh_delta", "status", "reason"]
    rows = df[cols].copy()
    rows["date"] = rows["date"].astype(str)
    for col in ("prediction", "lo", "hi"):
        rows[col] = rows[col].round(1)
    return {"count": len(rows), "coefficient_applied": coefficient, "total": total,
            "note": FLEET_NOTE + " Снижение часов риска — оценка при выполнении плана, не измеренный эффект.",
            "data_until": FC.info.get("data_until"), "rows": rows.to_dict(orient="records")}


@app.get("/plan/export", tags=["План выпуска"], summary="Выгрузить план выпуска в XLSX")
def plan_export(date_from: str = Query(...), date_to: str = Query(...), route: list[int] | None = Query(None),
                coefficient: float = Query(1.0, gt=0, le=3), min_share: float = Query(0.6, ge=0, le=1),
                user: str = Depends(current_user)) -> Response:
    FC.get()
    body = _plan_export_bytes(FC.version, date_from, date_to, tuple(route or ()), coefficient, min_share)
    return Response(content=body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="plan_{date_from}_{date_to}.xlsx"'})


@lru_cache(maxsize=64)
def _plan_export_bytes(version: str, date_from: str, date_to: str, route: tuple[int, ...],
                       coefficient: float, min_share: float) -> bytes:
    df, total = _plan_data(date_from, date_to, list(route) if route else None, coefficient, min_share)
    out = df[["route", "date", "hour", "prediction", "lo", "hi", "veh_typ", "veh_recommended", "veh_delta", "reason"]].copy()
    out["date"] = out.date.astype(str)
    out.columns = ["Маршрут", "Дата", "Час", "Посадки", "Нижняя граница", "Верхняя граница",
                   "Обычно вагонов", "Рекомендуется", "Изменение", "Причина"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="План выпуска", index=False)
        pd.DataFrame([total]).to_excel(writer, sheet_name="Итоги", index=False)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Потоковый контур: факт против прогноза, сделанного ДО поступления факта
# --------------------------------------------------------------------------
HIST_DIRS = [Path(os.environ.get("HISTORY_DIR", "/app/history")), INGEST]
ARCHIVE = STATE / "archive"


@app.get("/monitor/accuracy", tags=["Мониторинг"], summary="Точность прогноза на поступивших фактических данных")
def monitor_accuracy(date_from: str | None = Query(None), date_to: str | None = Query(None),
                     forecast: Literal["latest", "earliest"] = Query("latest", description="latest — самый свежий прогноз до факта, earliest — самый ранний"),
                     user: str = Depends(current_user)) -> dict:
    """Для каждой даты с фактом берётся прогноз из архива, опубликованный по данным ДО этой даты (честная проверка «как в жизни»)."""
    files = tuple(sorted((str(f), f.stat().st_mtime_ns, f.stat().st_size)
                         for d in HIST_DIRS + [ARCHIVE] if d.exists() for f in d.glob("*.csv" if d != ARCHIVE else "*.parquet")))
    return _accuracy_cached(date_from, date_to, forecast, files)


@lru_cache(maxsize=64)
def _accuracy_cached(date_from: str | None, date_to: str | None, forecast: str, files: tuple) -> dict:
    snaps = sorted(ARCHIVE.glob("forecast_until_*.parquet"))
    if not snaps:
        return {"detail": "архив прогнозов пуст: точность появится после поступления новых фактических данных", "rows": []}
    facts = pd.concat([pd.read_csv(f, sep=";") for d in HIST_DIRS if d.exists() for f in d.glob("*.csv")], ignore_index=True)
    facts = facts.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum()
    rows, allm = [], []
    for sp in snaps:
        until = sp.stem.replace("forecast_until_", "")
        fc = pd.read_parquet(sp); fc["date"] = pd.to_datetime(fc["date"]).dt.strftime("%Y-%m-%d")
        m = fc.merge(facts, on=["route", "date", "hour"])
        if date_from: m = m[m.date >= date_from]
        if date_to: m = m[m.date <= date_to]
        m = m[m.route.isin(FLEET.route.unique() if FLEET is not None else m.route.unique()) & (m.date > until)]
        if m.empty:
            continue
        m["forecast_until"] = until; allm.append(m)
    if not allm:
        return {"detail": "фактов за даты прогноза пока нет", "rows": []}
    m = pd.concat(allm).sort_values("forecast_until").drop_duplicates(["route", "date", "hour"], keep="last" if forecast == "latest" else "first")
    m["ahead_days"] = (pd.to_datetime(m.date) - pd.to_datetime(m.forecast_until)).dt.days
    def score(g): return round(1 - (g.boardings - g.prediction).abs().sum() / max(g.boardings.sum(), 1), 4)
    by_day = [{"date": d, "wape_score": score(g), "fact": float(g.boardings.sum()), "forecast": round(float(g.prediction.sum()), 1),
               "forecast_made_from_data_until": g.forecast_until.iloc[0]} for d, g in m.groupby("date")]
    by_route = [{"route": int(r), "wape_score": score(g), "bias": round(float(g.prediction.sum() / max(g.boardings.sum(), 1) - 1), 4)} for r, g in m.groupby("route")]
    return {"wape_score": score(m), "hours": int(len(m)), "days": len(by_day), "forecast_used": forecast,
            "mean_days_ahead": round(float(m.ahead_days.mean()), 1), "by_day": by_day, "by_route": by_route,
            "note": "метрика WAPE-score = 1 − Σ|факт − прогноз| / Σ факт; прогноз взят из архива на дату данных до факта"}


# --------------------------------------------------------------------------
# «Сейчас» и алерты для диспетчера. Демо-время: дата — виртуальная (NOW_MODE=demo), время суток — пользователя.
# --------------------------------------------------------------------------
NOW_MODE = os.environ.get("NOW_MODE", "real")                 # real — настоящая дата (Москва); demo — дата DEMO_TODAY
DEMO_TODAY = os.environ.get("DEMO_TODAY", "")                 # пусто — первый день горизонта прогноза
MSK = dt.timezone(dt.timedelta(hours=3))
HELP = {
    "prediction": "прогноз посадок (успешных валидаций) за час, итоговая модель",
    "lo_hi": "коридор 80 %: в 8 из 10 случаев на бэктестах того же горизонта факт попадал в эти границы",
    "load": "загрузка — посадок на вагон в час относительно истории маршрута; «риск переполнения» — выше 90-го процентиля, «повышенная» — выше 85 % от него",
    "vehicles": "вагонов обычно — медиана вагонов с валидациями в этот час за 8 недель; рекомендация — минимум вагонов, чтобы не превышать 75-й процентиль загрузки, но не меньше 60 % обычного выпуска",
    "stops": "по остановкам — оценочная разбивка прогноза маршрута (расписание GTFS, пересадки, жильё и точки притяжения рядом)",
    "demo_time": "демо-время: дата сдвинута к периоду прогноза, время суток — ваше; в проде — текущая дата",
    "weather": "поправка на сильный дождь по прогнозу погоды (−2,5 %); на стенде — демо по фактической погоде архива",
}


def _now(hour: int | None, date: str | None):
    """Виртуальное «сейчас»: (дата, час, режим)."""
    h = FC.info["horizon"]
    if date:
        d = date
    elif NOW_MODE == "demo":
        d = DEMO_TODAY or h["start"]
    else:
        d = dt.datetime.now(MSK).date().isoformat()
    try:
        pd.to_datetime(d, format="%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, f"неверная дата «{d}»: нужно ГГГГ-ММ-ДД") from None
    if not (h["start"] <= d <= h["end"]):
        raise HTTPException(400, f"дата {d} вне горизонта прогноза {h['start']} … {h['end']}")
    hh = dt.datetime.now(MSK).hour if hour is None else hour
    return d, hh, ("demo" if (NOW_MODE == "demo" or date) else "real")


def _daykind(d: str) -> str | None:
    t = pd.Timestamp(d)
    f = STATE / "cache" / f"cal_{t.year}.txt"
    if not f.exists():
        f = Path("/app/service/engine/fallback") / f"cal_{t.year}.txt"
    codes = f.read_text().strip() if f.exists() else ""
    c = codes[t.dayofyear - 1] if len(codes) >= t.dayofyear else ""
    if c == "1" and t.dayofweek < 5:
        return "нерабочий праздничный день"
    if c in ("0", "2") and t.dayofweek >= 5:
        return "рабочий выходной (перенос)" + (", сокращённый" if c == "2" else "")
    if c == "2":
        return "предпраздничный сокращённый день"
    return None


def _hours_text(hrs: list) -> str:
    """[8, 9, 11] → «8:00–10:00, 11:00–12:00»"""
    parts, start = [], hrs[0]
    for a, b in zip(hrs, hrs[1:] + [None]):
        if b != a + 1:
            parts.append(f"{start}:00–{a + 1}:00"); start = b
    return ", ".join(parts)


@app.get("/now", tags=["Диспетчер"], summary="Что сейчас: текущий час и 3 следующих по маршрутам")
def now(hour: int | None = Query(None, ge=0, le=23, description="час пользователя; по умолчанию — текущий час (Москва)"),
        date: str | None = Query(None, description="дата «сегодня» (только для демо); по умолчанию — демо-дата или текущая"),
        route: list[int] | None = Query(None), coefficient: float = Query(1.0, gt=0, le=3),
        user: str = Depends(current_user)) -> dict:
    d, hh, mode = _now(hour, date)
    FC.get()
    return _now_cached(FC.version, d, hh, mode, tuple(route or ()), coefficient)


@lru_cache(maxsize=256)
def _now_cached(version: str, d: str, hh: int, mode: str, route: tuple[int, ...], coefficient: float) -> dict:
    h_end = min(hh + 3, 23)
    df = _fleet_frame(d, d, list(route) if route else None, 0, 23, coefficient)
    cur = df[df.hour == hh]; nxt = df[(df.hour > hh) & (df.hour <= h_end)]
    def rec(x):
        return {"hour": int(x.hour), "prediction": round(float(x.prediction), 1), "lo": round(float(x.lo), 1), "hi": round(float(x.hi), 1),
                "veh_typ": float(x.veh_typ), "veh_recommended": float(x.veh_recommended), "veh_delta": float(x.veh_delta),
                "load_index": None if pd.isna(x.load_index) else round(float(x.load_index), 2), "status": x.status}
    routes = []
    for r, g in df.groupby("route"):
        c = g[g.hour == hh]
        routes.append({"route": int(r), "now": rec(c.iloc[0]) if len(c) else None,
                       "next": [rec(x) for x in g[(g.hour > hh) & (g.hour <= h_end)].itertuples()],
                       "day_total": round(float(g.prediction.sum()), 1), "day_passed": round(float(g[g.hour < hh].prediction.sum()), 1)})
    return {"mode": mode, "today": d, "hour": hh, "day_kind": _daykind(d), "data_until": FC.info.get("data_until"),
            "coefficient_applied": coefficient,
            "network": {"now": round(float(cur.prediction.sum()), 1), "now_lo": round(float(cur.lo.sum()), 1), "now_hi": round(float(cur.hi.sum()), 1),
                        "next_hours": round(float(nxt.prediction.sum()), 1), "day_total": round(float(df.prediction.sum()), 1),
                        "day_passed": round(float(df[df.hour < hh].prediction.sum()), 1),
                        "routes_at_risk_now": sorted(int(x) for x in cur[cur.status == "риск переполнения"].route)},
            "routes": routes, "help": HELP}


@app.get("/alerts", tags=["Диспетчер"], summary="Предупреждения для диспетчера на текущий момент")
def alerts(hour: int | None = Query(None, ge=0, le=23), date: str | None = Query(None), lookahead: int = Query(3, ge=1, le=12),
           coefficient: float = Query(1.0, gt=0, le=3),
           user: str = Depends(current_user)) -> dict:
    d, hh, mode = _now(hour, date)
    FC.get()
    status_file = STATE / "refresh_status.json"
    status_mtime = status_file.stat().st_mtime_ns if status_file.exists() else 0
    return _alerts_cached(FC.version, d, hh, mode, lookahead, coefficient, status_mtime, user)


@lru_cache(maxsize=256)
def _alerts_cached(version: str, d: str, hh: int, mode: str, lookahead: int,
                   coefficient: float, status_mtime: int, user: str) -> dict:
    out = []
    def add(level, kind, text, **kw):
        out.append({"level": level, "type": kind, "text": text, **kw})
    df = _fleet_frame(d, d, None, 0, 23, coefficient)
    win = df[(df.hour >= hh) & (df.hour <= min(hh + lookahead, 23))]
    for r, g in win[win.status == "риск переполнения"].groupby("route"):
        hrs = sorted(int(x) for x in g.hour)
        delta = max(0, int(g.veh_delta.max()))
        confidence = "высокая" if (g.lo / g.veh_typ.replace(0, np.nan) > g.bpv_p90).any() else "умеренная"
        add("критично", "переполнение", f"Маршрут {r}, {_hours_text(hrs)}: риск повышенной нагрузки; добавить до {delta} ваг. к {hrs[0]}:00",
            route=int(r), hours=hrs, veh_delta=delta, action=f"Добавить до {delta} вагонов к {hrs[0]}:00",
            react_by=f"{d}T{hrs[0]:02d}:00:00+03:00", confidence=confidence,
            passengers_at_risk=round(float(g.prediction.sum()), 1))
    for r, g in win[win.status == "повышенная"].groupby("route"):
        hrs = sorted(int(x) for x in g.hour)
        add("внимание", "повышенная загрузка", f"Маршрут {r}, {_hours_text(hrs)}: повышенная загрузка", route=int(r), hours=hrs,
            action="Проверить выпуск и фактическую загрузку", confidence="умеренная", passengers_at_risk=round(float(g.prediction.sum()), 1))
    spare = win[(win.veh_delta <= -3) & (win.status == "норма")]
    for r, g in spare.groupby("route"):
        add("инфо", "избыток вагонов", f"Маршрут {r}, {_hours_text(sorted(int(x) for x in g.hour))}: загрузка низкая, можно снять до {int(-g.veh_delta.min())} ваг. без роста интервалов более чем в 1,7 раза",
            route=int(r), hours=sorted(int(x) for x in g.hour))
    for k in range(0, 8):                                          # праздники и переносы: сегодня и 7 дней вперёд
        day = (pd.Timestamp(d) + pd.Timedelta(days=k)).date().isoformat()
        kind = _daykind(day) if day <= FC.info["horizon"]["end"] else None
        if kind:
            add("инфо" if k else "внимание", "календарь", f"{'Сегодня' if k == 0 else day}: {kind} — спрос отличается от обычного", date=day)
    rain = [x for x in FC.info.get("rain_adjusted_days", []) if d <= x <= (pd.Timestamp(d) + pd.Timedelta(days=7)).date().isoformat()]
    for x in rain:
        add("инфо", "погода", f"{'Сегодня' if x == d else x}: ожидается сильный дождь — прогноз снижен на 2,5 %"
            + (" (демо: фактическая погода архива)" if FC.info.get("sources", {}).get("rain_forecast", {}).get("mode") == "demo" else ""), date=x)
    lag = (pd.Timestamp(d) - pd.Timestamp(FC.info["data_until"])).days
    if lag > 2:
        add("внимание", "данные", f"Последние фактические данные — {FC.info['data_until']}: прогноз на {lag} дн. вперёд, точность ниже (коридор шире)", days=lag)
    try:
        st = json.loads((STATE / "refresh_status.json").read_text(encoding="utf-8"))
        if not st.get("ok", True):
            add("критично", "пересчёт", f"Прогноз не обновился ({st.get('error', '')[:120]}); действует прошлая версия")
    except (FileNotFoundError, ValueError):
        pass
    try:
        acc = monitor_accuracy(date_from=(pd.Timestamp(d) - pd.Timedelta(days=7)).date().isoformat(), date_to=d, forecast="latest", user=user)
        if acc.get("wape_score") is not None and acc["wape_score"] < 0.85:
            add("внимание", "точность", f"Точность прогноза за последние 7 дней {acc['wape_score']:.3f} — ниже обычной (0,88–0,90)")
    except Exception:
        pass
    order = {"критично": 0, "внимание": 1, "инфо": 2}
    for item in out:
        key = f"{d}|{item['type']}|{item.get('route', '')}|{','.join(map(str, item.get('hours', [])))}"
        item["id"] = hashlib.sha256(key.encode()).hexdigest()[:20]
    out.sort(key=lambda a: (order[a["level"]], -a.get("passengers_at_risk", 0)))
    return {"mode": mode, "today": d, "hour": hh, "coefficient_applied": coefficient,
            "count": len(out), "alerts": out}


class DecisionIn(BaseModel):
    alert_id: str = Field(pattern=r"^[0-9a-f]{20}$")
    alert_date: str
    route: int | None = None
    decision: Literal["accepted", "rejected", "postponed"]
    comment: str = Field(default="", max_length=500)


@app.post("/decisions", tags=["Диспетчер"], summary="Принять, отклонить или отложить предупреждение")
def decision_save(body: DecisionIn, user: str = Depends(current_user)) -> dict:
    try:
        date = dt.date.fromisoformat(body.alert_date)
    except ValueError:
        raise HTTPException(400, "alert_date должна быть датой ГГГГ-ММ-ДД") from None
    if body.route is not None and body.route not in ROUTES:
        raise HTTPException(400, "неизвестный маршрут")
    return save_decision(body.alert_id, user, body.decision, body.comment.strip(), date.isoformat(), body.route)


@app.get("/decisions", tags=["Диспетчер"], summary="Журнал решений текущего пользователя")
def decisions(limit: int = Query(100, ge=1, le=500), user: str = Depends(current_user)) -> dict:
    rows = list_decisions(user, limit)
    return {"count": len(rows), "rows": rows,
            "summary": {kind: sum(r["decision"] == kind for r in rows) for kind in ("accepted", "rejected", "postponed")},
            "note": "журнал фиксирует решение диспетчера; фактическое выполнение и эффект отдельно не подтверждены"}


@lru_cache(maxsize=8)
def _decision_facts(stamp: tuple) -> pd.DataFrame:
    files = [Path(path) for path, _, _ in stamp]
    if not files:
        return pd.DataFrame(columns=["route", "date", "boardings"])
    facts = pd.concat([pd.read_csv(f, sep=";", usecols=["route", "date", "boardings"]) for f in files], ignore_index=True)
    return facts.groupby(["route", "date"], as_index=False).boardings.sum()


@app.get("/decisions/report", tags=["Диспетчер"], summary="Решения и спрос после поступления фактов")
def decisions_report(user: str = Depends(current_user)) -> dict:
    rows = list_decisions(user, 500)
    stamp = tuple(sorted((str(f), f.stat().st_mtime_ns, f.stat().st_size)
                         for d in HIST_DIRS if d.exists() for f in d.glob("*.csv")))
    facts = _decision_facts(stamp)
    by_route = {(int(x.route), str(x.date)): float(x.boardings) for x in facts.itertuples()}
    by_day = facts.groupby("date").boardings.sum().to_dict() if not facts.empty else {}
    for row in rows:
        row["factual_boardings"] = (by_route.get((int(row["route"]), row["alert_date"])) if row["route"] is not None
                                      else by_day.get(row["alert_date"]))
    return {"count": len(rows), "with_fact": sum(r["factual_boardings"] is not None for r in rows), "rows": rows,
            "summary": {kind: sum(r["decision"] == kind for r in rows) for kind in ("accepted", "rejected", "postponed")},
            "note": "факт — число посадок после решения, не доказательство выполнения рекомендации или её причинного эффекта"}
