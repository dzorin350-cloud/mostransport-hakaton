FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/main.py .
COPY data /app/data
ENV DATA_DIR=/app/data
EXPOSE 8000
# 2 воркера — под заявленные 2-4 vCPU (README service, раздел «Производительность»)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
