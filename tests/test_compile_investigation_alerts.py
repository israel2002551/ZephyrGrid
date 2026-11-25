"""Behavioural test for unified investigation-alert feeds."""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compile_investigation_alerts.py"
FIELDS = [
    "alert_id", "alert_type", "alert_state", "severity", "asset_id", "period_start_utc", "period_end_utc",
    "methodology", "confidence", "evidence_json", "recommended_action",
]


class UnifiedAlertsTest(unittest.TestCase):
    def test_combines_distinct_alerts_and_removes_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            first = directory / "first.csv"
            second = directory / "second.csv"
            output = directory / "output"
            alert_one = {
                "alert_id": "alert-1", "alert_type": "energy_discrepancy", "alert_state": "investigation_required",
                "severity": "high", "asset_id": "T-1", "period_start_utc": "2026-01-01T00:00:00+00:00",
                "period_end_utc": "2026-01-01T00:15:00+00:00", "methodology": "energy_balance_rules_v1",
                "confidence": "0.95", "evidence_json": json.dumps({"unexplained_energy_kwh": 20}), "recommended_action": "Review.",
            }
            alert_two = {
                "alert_id": "alert-2", "alert_type": "meter_tamper_event", "alert_state": "investigation_required",
                "severity": "high", "asset_id": "M-1", "period_start_utc": "2026-01-01T01:00:00+00:00",
                "period_end_utc": "2026-01-01T01:00:00+00:00", "methodology": "meter_integrity_rules_v1",
                "confidence": "1.0", "evidence_json": json.dumps({"source_event_ids": ["e-1"]}), "recommended_action": "Review.",
            }
            for path, rows in ((first, [alert_one]), (second, [alert_one, alert_two])):
                with path.open("w", newline="", encoding="utf-8") as destination:
                    writer = csv.DictWriter(destination, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
            completed = subprocess.run(["python", str(SCRIPT), "--alert-file", str(first), "--alert-file", str(second), "--output-dir", str(output)], check=True, capture_output=True, text=True)
            self.assertIn("Bundled 2 investigation alerts", completed.stdout)
            feed = [json.loads(line) for line in (output / "investigation_alerts.jsonl").read_text(encoding="utf-8").splitlines()]
            report = json.loads((output / "unified_alert_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual([alert["alert_id"] for alert in feed], ["alert-1", "alert-2"])
            self.assertEqual(report["duplicate_alerts_removed"], 1)
            self.assertTrue(all(alert["alert_state"] == "investigation_required" for alert in feed))


if __name__ == "__main__":
    unittest.main()
