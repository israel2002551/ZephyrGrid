"""Behavioural test for deterministic Metering Intelligence rules."""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "detect_meter_integrity.py"
FIELDS = ["event_id", "device_id", "asset_id", "observed_at", "event_type", "quality_status"]


class MeterIntegrityTest(unittest.TestCase):
    def test_event_rules_create_investigation_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            events = directory / "events.csv"
            output = directory / "output"
            with events.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows([
                    {"event_id": "tamper-1", "device_id": "D-1", "asset_id": "M-1", "observed_at": "2026-01-01T00:00:00Z", "event_type": "meter_tamper", "quality_status": "valid"},
                    {"event_id": "reset-1", "device_id": "D-2", "asset_id": "M-2", "observed_at": "2026-01-01T00:00:00Z", "event_type": "device_reset", "quality_status": "valid"},
                    {"event_id": "reset-2", "device_id": "D-2", "asset_id": "M-2", "observed_at": "2026-01-01T01:00:00Z", "event_type": "device_reset", "quality_status": "valid"},
                    {"event_id": "reset-3", "device_id": "D-2", "asset_id": "M-2", "observed_at": "2026-01-01T02:00:00Z", "event_type": "device_reset", "quality_status": "valid"},
                    {"event_id": "read-1", "device_id": "D-3", "asset_id": "M-3", "observed_at": "2026-01-01T00:00:00Z", "event_type": "reading_received", "quality_status": "valid"},
                    {"event_id": "read-2", "device_id": "D-3", "asset_id": "M-3", "observed_at": "2026-01-01T01:15:00Z", "event_type": "reading_received", "quality_status": "valid"},
                    {"event_id": "bad-1", "device_id": "D-4", "asset_id": "M-4", "observed_at": "2026-01-01T00:00:00Z", "event_type": "meter_tamper", "quality_status": "invalid"},
                ])
            completed = subprocess.run(["python", str(SCRIPT), "--events", str(events), "--output-dir", str(output)], check=True, capture_output=True, text=True)
            self.assertIn("Generated 3 investigation alerts", completed.stdout)
            with (output / "meter_integrity_alerts.csv").open(encoding="utf-8", newline="") as source:
                alerts = list(csv.DictReader(source))
            report = json.loads((output / "meter_integrity_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual({alert["alert_type"] for alert in alerts}, {"meter_tamper_event", "repeated_device_reset", "meter_communication_gap"})
            self.assertTrue(all(alert["alert_state"] == "investigation_required" for alert in alerts))
            self.assertEqual(report["inputs"]["rejections"]["non_valid_quality_status"], 1)


if __name__ == "__main__":
    unittest.main()
