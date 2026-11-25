"""Behavioural test for electrical-condition investigation alerts."""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "monitor_electrical_conditions.py"


class ElectricalConditionTest(unittest.TestCase):
    def test_voltage_and_current_breaches_create_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            measurements = directory / "measurements.csv"
            limits = directory / "limits.csv"
            output = directory / "output"
            with limits.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=["asset_id", "asset_type", "nominal_voltage_v", "min_voltage_pu", "max_voltage_pu", "max_current_a", "source_reference"])
                writer.writeheader()
                writer.writerow({"asset_id": "T-1", "asset_type": "transformer", "nominal_voltage_v": "240", "min_voltage_pu": "0.9", "max_voltage_pu": "1.1", "max_current_a": "100", "source_reference": "test-limit"})
            with measurements.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=["measurement_id", "asset_id", "asset_type", "measurement_type", "measurement_value", "measurement_unit", "phase", "observed_at", "quality_status"])
                writer.writeheader()
                writer.writerows([
                    {"measurement_id": "v-low", "asset_id": "T-1", "asset_type": "transformer", "measurement_type": "voltage_v", "measurement_value": "200", "measurement_unit": "v", "phase": "a", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "valid"},
                    {"measurement_id": "i-high", "asset_id": "T-1", "asset_type": "transformer", "measurement_type": "current_a", "measurement_value": "130", "measurement_unit": "a", "phase": "a", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "valid"},
                    {"measurement_id": "v-ok", "asset_id": "T-1", "asset_type": "transformer", "measurement_type": "voltage_v", "measurement_value": "240", "measurement_unit": "v", "phase": "b", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "valid"},
                    {"measurement_id": "bad", "asset_id": "T-1", "asset_type": "transformer", "measurement_type": "current_a", "measurement_value": "200", "measurement_unit": "a", "phase": "a", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "invalid"},
                ])
            completed = subprocess.run(["python", str(SCRIPT), "--measurements", str(measurements), "--asset-limits", str(limits), "--output-dir", str(output)], check=True, capture_output=True, text=True)
            self.assertIn("Generated 2 investigation alerts", completed.stdout)
            with (output / "electrical_condition_alerts.csv").open(encoding="utf-8", newline="") as source:
                alerts = list(csv.DictReader(source))
            report = json.loads((output / "electrical_condition_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual({alert["alert_type"] for alert in alerts}, {"voltage_out_of_range", "current_overload"})
            self.assertEqual({alert["severity"] for alert in alerts}, {"critical"})
            self.assertTrue(all(alert["alert_state"] == "investigation_required" for alert in alerts))
            self.assertEqual(report["inputs"]["measurement_rejections"]["non_valid_quality_status"], 1)


if __name__ == "__main__":
    unittest.main()
