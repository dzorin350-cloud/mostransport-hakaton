"""The city export schema and the offline fallback must both remain usable."""
import datetime as dt
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from service.engine import sources


def export_bytes(type_field="TransportType", zipped=True):
    records = [
        {"Year": 2025, "Month": "Октябрь", type_field: "Трамвай", "PassengerTraffic": 123},
        {"Year": 2025, "Month": "Ноябрь", type_field: "Трамвай", "PassengerTraffic": 456},
        {"Year": 2025, "Month": "Октябрь", type_field: "Автобус", "PassengerTraffic": 999},
    ]
    raw = json.dumps(records, ensure_ascii=False).encode("utf-8")
    if not zipped:
        return raw
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("data-62521.json", raw)
    return output.getvalue()


class RidershipSourceTests(unittest.TestCase):
    def test_current_zipped_export_uses_transport_type_and_cutoff(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(sources, "_get", return_value=export_bytes()):
            data, status = sources.fetch_ridership(dt.date(2025, 10, 31), Path(temp))
        self.assertEqual(status["origin"], "live")
        self.assertEqual(status["rows_total"], 2)
        self.assertEqual(data[["year", "month", "pax"]].values.tolist(), [[2025, 10, 123]])

    def test_previous_json_field_still_works(self):
        data = sources._parse_62521(export_bytes(type_field="TypeOfTransport", zipped=False))
        self.assertEqual(data["pax"].tolist(), [123, 456])

    def test_unavailable_export_uses_bundled_copy(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(sources, "_get", side_effect=OSError("offline")):
            data, status = sources.fetch_ridership(dt.date(2025, 10, 31), Path(temp))
        self.assertEqual(status["origin"], "fallback")
        self.assertEqual(len(data), 82)
        self.assertEqual(status["last_month_used"], "2025-10")


if __name__ == "__main__":
    unittest.main()
