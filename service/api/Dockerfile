# Контекст сборки — корень репозитория (см. docker-compose.yml: build.context: ..)
FROM python:3.12-slim
WORKDIR /app
COPY service/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY service/__init__.py service/__init__.py
COPY service/engine service/engine
COPY service/api/main.py main.py
COPY service/api/auth.py auth.py
COPY service/data/routes.geojson data/routes.geojson
COPY service/start.sh start.sh
# история валидаций (почасовые агрегаты route;date;hour;boardings); в проде монтируется томом и пополняется
COPY labels/ history/
ENV DATA_DIR=/app/data STATE_DIR=/app/state OUT_DIR=/app/state HISTORY_DIR=/app/history \
    INGEST_DIR=/app/ingest AUTH_DIR=/app/auth \
    WORKERS=4 REFRESH_HOURS=24 CHECK_SECONDS=60 PYTHONUNBUFFERED=1
EXPOSE 8000
# Число воркеров = числу vCPU контейнера (для 2 vCPU: WORKERS=2, см. docker-compose.2cpu.yml)
CMD ["./start.sh"]
