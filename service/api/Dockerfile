FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/main.py .
COPY data /app/data
ENV DATA_DIR=/app/data
EXPOSE 8000
# Число воркеров = числу vCPU контейнера (по умолчанию 4; для 2 vCPU: WORKERS=2,
# см. docker-compose.2cpu.yml и README service, раздел «Производительность»)
ENV WORKERS=4
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS}"]
