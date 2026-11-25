"""Focused behavioural test for the field-pilot reconciliation workflow."""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_energy_balance.py"


class ReconciliationTest(unittest.TestCase):
    def test_valid_discrepancy_generates_evidence_backed_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            measurements = directory / "measurements.csv"
            topology = directory / "topology.csv"
            output = directory / "output"
            with measurements.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=[
                    "measurement_id", "asset_id", "asset_type", "measurement_type", "measurement_value",
                    "measurement_unit", "observed_at", "quality_status", "interval_minutes",
                ])
                writer.writeheader()
                writer.writerows([
                    {"measurement_id": "tx-1", "asset_id": "T-1", "asset_type": "transformer", "measurement_type": "energy_import_kwh", "measurement_value": "100", "measurement_unit": "kwh", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "valid", "interval_minutes": "15"},
                    {"measurement_id": "m-1", "asset_id": "M-1", "asset_type": "meter", "measurement_type": "energy_import_kwh", "measurement_value": "30", "measurement_unit": "kwh", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "valid", "interval_minutes": "15"},
                    {"measurement_id": "m-2", "asset_id": "M-2", "asset_type": "meter", "measurement_type": "energy_import_kwh", "measurement_value": "40", "measurement_unit": "kwh", "observed_at": "2026-01-01T00:00:00Z", "quality_status": "valid", "interval_minutes": "15"},
                ])
            with topology.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=[
                    "parent_asset_id", "parent_asset_type", "child_asset_id", "child_asset_type",
                    "relationship_type", "valid_from", "valid_to", "source_reference",
                ])
                writer.writeheader()
                writer.writerows([
                    {"parent_asset_id": "F-1", "parent_asset_type": "feeder", "child_asset_id": "T-1", "child_asset_type": "transformer", "relationship_type": "feeds", "valid_from": "2025-01-01T00:00:00Z", "valid_to": "", "source_reference": "test"},
                    {"parent_asset_id": "T-1", "parent_asset_type": "transformer", "child_asset_id": "M-1", "child_asset_type": "meter", "relationship_type": "supplies", "valid_from": "2025-01-01T00:00:00Z", "valid_to": "", "source_reference": "test"},
                    {"parent_asset_id": "T-1", "parent_asset_type": "transformer", "child_asset_id": "M-2", "child_asset_type": "meter", "relationship_type": "supplies", "valid_from": "2025-01-01T00:00:00Z", "valid_to": "", "source_reference": "test"},
                ])
            completed = subprocess.run(
                ["python", str(SCRIPT), "--measurements", str(measurements), "--topology", str(topology), "--output-dir", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("Generated 1 investigation alerts", completed.stdout)
            with (output / "balance_intervals.csv").open(encoding="utf-8", newline="") as source:
                balances = list(csv.DictReader(source))
            with (output / "reconciliation_alerts.csv").open(encoding="utf-8", newline="") as source:
                alerts = list(csv.DictReader(source))
            report = json.loads((output / "reconciliation_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(balances), 1)
            self.assertEqual(balances[0]["unexplained_energy_kwh"], "20.0")
            self.assertEqual(balances[0]["quality_status"], "valid")
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["alert_state"], "investigation_required")
            self.assertEqual(report["outputs"]["investigation_alerts"], 1)


if __name__ == "__main__":
    unittest.main()
