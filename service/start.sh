#!/bin/sh
# Один контейнер: фоновый движок (применяет модель, сам скачивает внешние данные, пересчитывает прогноз)
# + API-воркеры (отдают прогноз из памяти, подхватывают новые версии).
set -e
python -m service.engine.refresher &
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers "${WORKERS:-4}"
