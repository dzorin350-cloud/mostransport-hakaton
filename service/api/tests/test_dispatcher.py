"""Smoke tests for versioned forecast, planning, decisions and idempotent ingest.

Нужен PostgreSQL: TEST_DATABASE_URL (или DATABASE_URL), например
  docker run -d --name tram-test-db -e POSTGRES_USER=tram -e POSTGRES_PASSWORD=tram -e POSTGRES_DB=tram_test -p 55432:5432 postgres:17-alpine
  TEST_DATABASE_URL=postgresql://tram:tram@localhost:55432/tram_test python -m unittest service/api/tests/test_dispatcher.py
Таблицы users, decisions, ingest_batches в этой базе очищаются перед тестами.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[3]
TEMP = tempfile.TemporaryDirectory()
BASE = Path(TEMP.name)
for name in ("state", "auth", "ingest", "history"):
    (BASE / name).mkdir()
os.environ.update({
    "STATE_DIR": str(BASE / "state"), "AUTH_DIR": str(BASE / "auth"),
    "INGEST_DIR": str(BASE / "ingest"), "HISTORY_DIR": str(BASE / "history"),
    "DATA_DIR": str(ROOT / "service" / "data"),
    "FLEET_PATH": str(ROOT / "service" / "engine" / "artifacts" / "fleet_norms.csv"),
    "STOPS_PATH": str(ROOT / "service" / "engine" / "artifacts" / "stops.csv"),
    "INTERVALS_PATH": str(ROOT / "service" / "engine" / "artifacts" / "interval_factors.csv"),
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"],
    "NOW_MODE": "demo", "DEMO_TODAY": "2025-11-01", "DEMO_USER": "demo", "DEMO_PASSWORD": "demo2025",
})
version = BASE / "state" / "versions" / "1-12345678"
version.mkdir(parents=True)
day = dt.date(2025, 11, 1)
holiday = dt.date(2025, 11, 4)                     # День народного единства, вторник
pd.DataFrame([{"route": route, "date": d, "hour": hour, "prediction": 100.0} for d in (day, holiday)
              for route in (1, 5, 7, 11, 12, 17, 25, 26, 28, 50) for hour in range(24)]).to_parquet(version / "forecast.parquet")
(version / "info.json").write_text(json.dumps({"model_version": "test", "data_until": "2025-10-31",
    "horizon": {"start": "2025-11-01", "end": "2025-11-04"}, "rain_adjusted_days": []}), encoding="utf-8")
(BASE / "state" / "current.json").write_text('{"version":"1-12345678"}', encoding="utf-8")
sys.path.insert(0, str(ROOT / "service" / "api"))
import psycopg  # noqa: E402
with psycopg.connect(os.environ["DATABASE_URL"]) as _con:
    for _t in ("users", "decisions", "ingest_batches"):
        _con.execute(f"DROP TABLE IF EXISTS {_t}")
import main  # noqa: E402


class DispatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        response = cls.client.post("/auth/token", data={"username": "demo", "password": "demo2025"})
        assert response.status_code == 200, response.text
        cls.headers = {"Authorization": "Bearer " + response.json()["access_token"]}

    def test_plan_and_scenario(self):
        base = self.client.get("/plan?date_from=2025-11-01&date_to=2025-11-01", headers=self.headers)
        self.assertEqual(base.status_code, 200, base.text)
        rows = base.json()["rows"]
        self.assertTrue(rows)
        self.assertIn("veh_recommended", rows[0])
        scenario = self.client.get("/plan?date_from=2025-11-01&date_to=2025-11-01&coefficient=1.2", headers=self.headers)
        self.assertEqual(scenario.status_code, 200, scenario.text)
        self.assertGreater(scenario.json()["rows"][0]["prediction"], rows[0]["prediction"])
        export = self.client.get("/plan/export?date_from=2025-11-01&date_to=2025-11-01", headers=self.headers)
        self.assertEqual(export.status_code, 200, export.text)
        self.assertTrue(export.content.startswith(b"PK"))

    def test_plan_on_holiday_uses_sunday_norms(self):
        hol = self.client.get("/plan?date_from=2025-11-04&date_to=2025-11-04", headers=self.headers)
        self.assertEqual(hol.status_code, 200, hol.text)
        body = hol.json()
        self.assertGreater(body["total"]["vehicle_hours_typical"], 0)
        self.assertEqual({r["reason"] for r in body["rows"]}, {"праздничный день"})
        norms = main.FLEET[(main.FLEET.dt == "sun") & (main.FLEET.route == 17) & (main.FLEET.hour == 8)].veh_typ.iloc[0]
        row = next(r for r in body["rows"] if r["route"] == 17 and r["hour"] == 8)
        self.assertEqual(row["veh_typ"], norms)
        fleet = self.client.get("/fleet?date_from=2025-11-04&date_to=2025-11-04", headers=self.headers)
        self.assertEqual(fleet.status_code, 200, fleet.text)
        self.assertGreater(fleet.json()["total"]["vehicle_hours_typical"], 0)

    def test_now_alerts_and_stops(self):
        base = self.client.get("/now?date=2025-11-01&hour=8", headers=self.headers)
        changed = self.client.get("/now?date=2025-11-01&hour=8&coefficient=1.2", headers=self.headers)
        self.assertEqual(base.status_code, 200, base.text)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertGreater(changed.json()["network"]["now"], base.json()["network"]["now"])
        alerts = self.client.get("/alerts?date=2025-11-01&hour=8", headers=self.headers)
        self.assertEqual(alerts.status_code, 200, alerts.text)
        self.assertTrue(all(len(a["id"]) == 20 for a in alerts.json()["alerts"]))
        stops = self.client.get("/forecast/stops?date_from=2025-11-01&date_to=2025-11-01&hour_from=8&hour_to=8",
                                headers=self.headers)
        self.assertEqual(stops.status_code, 200, stops.text)
        self.assertGreater(stops.json()["count"], 0)

    def test_decisions(self):
        response = self.client.post("/decisions", headers=self.headers, json={"alert_id": "a" * 20,
            "alert_date": "2025-11-01", "route": 17, "decision": "accepted", "comment": "передано в депо"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.get("/decisions", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["summary"]["accepted"], 1)
        report = self.client.get("/decisions/report", headers=self.headers)
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["summary"]["accepted"], 1)

    def test_ingest_deduplication(self):
        body = "route;date;hour;boardings\n17;2025-11-02;8;10\n"
        first = self.client.post("/ingest/hourly", headers=self.headers, content=body)
        self.assertEqual(first.status_code, 200, first.text)
        same = self.client.post("/ingest/hourly", headers=self.headers, content=body)
        self.assertEqual(same.status_code, 200, same.text)
        self.assertTrue(same.json()["повтор"])
        conflict = self.client.post("/ingest/hourly", headers=self.headers,
                                    content="route;date;hour;boardings\n17;2025-11-02;8;20\n")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        bad = self.client.post("/ingest/hourly", headers=self.headers,
                               content="route;date;hour;boardings\n17;2025-11-03;8;nan\n")
        self.assertEqual(bad.status_code, 400, bad.text)
        fractional = self.client.post("/ingest/hourly", headers=self.headers,
                                      content="route;date;hour;boardings\n17;2025-11-03;8.5;10\n")
        self.assertEqual(fractional.status_code, 400, fractional.text)

    def test_versioned_publication(self):
        from service.engine import refresher
        class FakeEngine:
            table = pd.DataFrame([{"route": 17, "date": day, "hour": 8, "prediction": 123.0}])
            def refresh(self):
                return {"model_version": "test-next", "data_until": "2025-10-31",
                        "horizon": {"start": "2025-11-01", "end": "2025-11-01"},
                        "computed_at": "2025-10-31T23:00:00Z"}
        old = refresher.OUT
        refresher.OUT = BASE / "state"
        try:
            refresher.run_once(FakeEngine())
            pointer = json.loads((BASE / "state" / "current.json").read_text())
            published = BASE / "state" / "versions" / pointer["version"]
            self.assertTrue((published / "forecast.parquet").exists())
            self.assertTrue((published / "info.json").exists())
            main.FC._checked = 0
            self.assertEqual(main.FC.get().prediction.iloc[0], 123.0)
            self.assertEqual(main.FC.info["model_version"], "test-next")
            self.assertEqual(self.client.get("/ready").status_code, 200)
        finally:
            refresher.OUT = old


if __name__ == "__main__":
    unittest.main()
