"""Mixed dispatcher workload. Run for 10–15 minutes on 2 and 4 vCPU.

The test intentionally has no writes: ingestion must be tested on a disposable
copy of the history, with a separate concurrent writer and restore check.
"""
import random

from locust import HttpUser, between, task


class DispatcherUser(HttpUser):
    wait_time = between(0.2, 0.8)

    def on_start(self):
        response = self.client.post("/auth/token", data={"username": "demo", "password": "demo2025"})
        response.raise_for_status()
        self.client.headers.update({"Authorization": "Bearer " + response.json()["access_token"]})

    @task(8)
    def hourly(self):
        day = f"2025-11-{random.randint(1, 28):02d}"
        self.client.get("/forecast", params={"date_from": day, "date_to": day, "route": random.choice([1, 7, 17, 25, 50])},
                        name="/forecast hourly route/day")

    @task(3)
    def now(self):
        self.client.get("/now", params={"date": "2025-11-12", "hour": 8}, name="/now")

    @task(2)
    def alerts(self):
        self.client.get("/alerts", params={"date": "2025-11-12", "hour": 8}, name="/alerts")

    @task(2)
    def plan(self):
        self.client.get("/plan", params={"date_from": "2025-11-12", "date_to": "2025-11-12"}, name="/plan day")

    @task(2)
    def stops(self):
        self.client.get("/forecast/stops", params={"date_from": "2025-11-12", "date_to": "2025-11-12",
                                                   "hour_from": 8, "hour_to": 8}, name="/forecast/stops hour")

    @task(1)
    def quality(self):
        self.client.get("/monitor/accuracy", name="/monitor/accuracy")

    @task(1)
    def export_plan(self):
        self.client.get("/plan/export", params={"date_from": "2025-11-12", "date_to": "2025-11-12"},
                        name="/plan/export xlsx")
