"""Фоновый процесс сервиса: применяет модель и обновляет прогноз.

Пересчёт (Engine.refresh) выполняется:
  * при старте контейнера;
  * при изменении файлов истории (новые валидации в HISTORY_DIR, проверка раз в CHECK_SECONDS);
  * по расписанию раз в REFRESH_HOURS (заново скачиваются календарь и сезонность).
Результат пишется в неизменяемый каталог OUT_DIR/versions/<id>;
указатель OUT_DIR/current.json заменяется атомарно после завершения записи.
"""
import json, logging, os, sys, time, uuid
from pathlib import Path
from .core import Engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("engine.refresher")
HIST = Path(os.environ.get("HISTORY_DIR", "/app/history")); INGEST = Path(os.environ.get("INGEST_DIR", "/app/ingest")); OUT = Path(os.environ.get("OUT_DIR", "/app/state"))
REFRESH_H = float(os.environ.get("REFRESH_HOURS", "24")); CHECK_S = float(os.environ.get("CHECK_SECONDS", "60"))


def hist_stamp():
    return tuple(sorted((f.name, f.stat().st_mtime, f.stat().st_size) for d in (HIST, INGEST) if d.exists() for f in d.glob("*.csv")))


def _status(data: dict):
    tmp = OUT / "refresh_status.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUT / "refresh_status.json")


def run_once(engine: Engine):
    info = engine.refresh()
    OUT.mkdir(parents=True, exist_ok=True)
    t = engine.table
    # A version is immutable. The single pointer swap makes data and metadata visible together.
    version = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    target = OUT / "versions" / version
    target.mkdir(parents=True)
    t.to_parquet(target / "forecast.parquet", index=False)
    (target / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    # архив: прогноз, сделанный по данным до даты X, — для честной проверки на фактах, которые придут позже
    (OUT / "archive").mkdir(parents=True, exist_ok=True)
    arch = OUT / "archive" / f"forecast_until_{info['data_until']}.parquet"
    if not arch.exists():
        arch_tmp = arch.with_suffix(".parquet.tmp")
        t.to_parquet(arch_tmp, index=False)
        os.replace(arch_tmp, arch)
    pointer = OUT / "current.json.tmp"
    pointer.write_text(json.dumps({"version": version}), encoding="utf-8")
    os.replace(pointer, OUT / "current.json")
    log.info("прогноз опубликован: данные до %s, горизонт %s … %s", info["data_until"], info["horizon"]["start"], info["horizon"]["end"])
    _status({"ok": True, "at": info["computed_at"]})


def main():
    engine = Engine([HIST, INGEST], cache_dir=OUT / "cache")
    stamp, last = None, 0.0
    while True:
        try:
            s = hist_stamp()
            if s != stamp or time.time() - last > REFRESH_H * 3600:
                run_once(engine); stamp, last = s, time.time()
        except Exception as exc:
            log.exception("ошибка пересчёта; прошлый прогноз остаётся в силе")
            OUT.mkdir(parents=True, exist_ok=True)
            _status({"ok": False, "error": str(exc)[:500],
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "прошлый прогноз остаётся в силе"})
            if "--once" in sys.argv:
                raise
        if "--once" in sys.argv:
            return
        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
