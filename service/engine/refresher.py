"""Фоновый процесс сервиса: применяет модель и обновляет прогноз.

Пересчёт (Engine.refresh) выполняется:
  * при старте контейнера;
  * при изменении файлов истории (новые валидации в HISTORY_DIR, проверка раз в CHECK_SECONDS);
  * по расписанию раз в REFRESH_HOURS (заново скачиваются календарь и сезонность).
Результат пишется атомарно в OUT_DIR/forecast.parquet и OUT_DIR/info.json — воркеры API подхватывают новую версию сами.
"""
import json, logging, os, sys, time
from pathlib import Path
from .core import Engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("engine.refresher")
HIST = Path(os.environ.get("HISTORY_DIR", "/app/history")); INGEST = Path(os.environ.get("INGEST_DIR", "/app/ingest")); OUT = Path(os.environ.get("OUT_DIR", "/app/state"))
REFRESH_H = float(os.environ.get("REFRESH_HOURS", "24")); CHECK_S = float(os.environ.get("CHECK_SECONDS", "60"))


def hist_stamp():
    return tuple(sorted((f.name, f.stat().st_mtime, f.stat().st_size) for d in (HIST, INGEST) if d.exists() for f in d.glob("*.csv")))


def run_once(engine: Engine):
    info = engine.refresh()
    OUT.mkdir(parents=True, exist_ok=True)
    t = engine.table
    t.to_parquet(OUT / "forecast.parquet.tmp", index=False); os.replace(OUT / "forecast.parquet.tmp", OUT / "forecast.parquet")
    (OUT / "info.json.tmp").write_text(json.dumps(info, ensure_ascii=False, indent=1)); os.replace(OUT / "info.json.tmp", OUT / "info.json")
    log.info("прогноз опубликован: данные до %s, горизонт %s … %s", info["data_until"], info["horizon"]["start"], info["horizon"]["end"])
    (OUT / "refresh_status.json").write_text(json.dumps({"ok": True, "at": info["computed_at"]}, ensure_ascii=False))


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
            (OUT / "refresh_status.json").write_text(json.dumps({"ok": False, "error": str(exc)[:500],
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "прошлый прогноз остаётся в силе"}, ensure_ascii=False))
            if "--once" in sys.argv:
                raise
        if "--once" in sys.argv:
            return
        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
