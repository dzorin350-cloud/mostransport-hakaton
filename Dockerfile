FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p model/output && cd model/code && python build_grid.py
WORKDIR /app/model/code
# по умолчанию: обновить внешние данные и построить прогноз на ноябрь–декабрь 2025
ENTRYPOINT ["python", "forecast.py", "--refresh"]
CMD ["--start", "2025-11-01", "--end", "2025-12-31", "--out", "/app/model/output/forecast.csv"]
