"""Нагрузочный тест API — для раздела «Производительность» в README.

Запуск:
    ../.venv/bin/locust -f loadtest.py --host http://127.0.0.1:8123 \
        --headless -u 200 -r 20 -t 30s --csv=loadtest_report

ТЗ хакатона требует явные замеры latency/RPS в README при заявленных
2-4 vCPU / 2-4 ГБ RAM (капслоком: "В ОБЯЗАТЕЛЬНОМ ПОРЯДКЕ УКАЖИТЕ ДАННЫЕ
О ПРОИЗВОДИТЕЛЬНОСТИ"). Этот скрипт — источник этих цифр.
"""

import random

from locust import HttpUser, between, task

ROUTES = [1, 7, 11, 12, 17, 25, 26, 28, 50]
DATES = [f"2025-11-{d:02d}" for d in range(1, 29)] + [f"2025-12-{d:02d}" for d in range(1, 29)]


class ForecastUser(HttpUser):
    wait_time = between(0.05, 0.2)

    @task(5)
    def forecast_hourly(self):
        d0 = random.choice(DATES)
        self.client.get(
            "/forecast",
            params={"date_from": d0, "date_to": d0, "route": random.choice(ROUTES)},
            name="/forecast [hour, 1 day, 1 route]",
        )

    @task(3)
    def forecast_daily(self):
        self.client.get(
            "/forecast",
            params={
                "date_from": "2025-11-01",
                "date_to": "2025-12-31",
                "granularity": "day",
            },
            name="/forecast [day, full horizon, all routes]",
        )

    @task(2)
    def forecast_with_coefficient(self):
        d0 = random.choice(DATES)
        self.client.get(
            "/forecast",
            params={
                "date_from": d0,
                "date_to": d0,
                "coefficient": round(random.uniform(0.7, 1.3), 2),
            },
            name="/forecast [with coefficient]",
        )

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")
