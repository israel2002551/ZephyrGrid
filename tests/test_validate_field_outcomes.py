"""Behavioural test for field-validation labels."""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_field_outcomes.py"
FIELDS = ["review_id", "alert_id", "alert_type", "asset_id", "reviewed_at", "reviewer_id", "outcome", "evidence_reference", "training_eligible", "notes"]


class FieldOutcomeValidationTest(unittest.TestCase):
    def test_links_human_review_to_existing_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            alerts = directory / "alerts.jsonl"
            outcomes = directory / "outcomes.csv"
            output = directory / "output"
            alerts.write_text(json.dumps({"alert_id": "a-1", "alert_type": "meter_tamper_event", "asset_id": "M-1", "methodology": "meter_integrity_rules_v1", "evidence": {"source_event_ids": ["e-1"]}}) + "\n", encoding="utf-8")
            with outcomes.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows([
                    {"review_id": "r-1", "alert_id": "a-1", "alert_type": "meter_tamper_event", "asset_id": "M-1", "reviewed_at": "2026-01-02T00:00:00Z", "reviewer_id": "reviewer-1", "outcome": "confirmed_tamper", "evidence_reference": "case-1", "training_eligible": "true", "notes": "Field inspection completed."},
                    {"review_id": "r-bad", "alert_id": "unknown", "alert_type": "meter_tamper_event", "asset_id": "M-1", "reviewed_at": "2026-01-02T00:00:00Z", "reviewer_id": "reviewer-1", "outcome": "confirmed_tamper", "evidence_reference": "case-2", "training_eligible": "true", "notes": "Ignored."},
                ])
            completed = subprocess.run(["python", str(SCRIPT), "--alerts", str(alerts), "--outcomes", str(outcomes), "--output-dir", str(output)], check=True, capture_output=True, text=True)
            self.assertIn("Validated 1 outcomes", completed.stdout)
            labels = [json.loads(line) for line in (output / "validated_investigation_outcomes.jsonl").read_text(encoding="utf-8").splitlines()]
            report = json.loads((output / "field_validation_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual(labels[0]["outcome"], "confirmed_tamper")
            self.assertTrue(labels[0]["training_eligible"])
            self.assertEqual(report["rejections"]["unknown_alert_id"], 1)


if __name__ == "__main__":
    unittest.main()
