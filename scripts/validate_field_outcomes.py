#!/usr/bin/env python3
"""Validate investigation outcomes against a unified alert feed."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "data" / "outputs" / "field_validation"
REQUIRED_COLUMNS = {
    "review_id", "alert_id", "alert_type", "asset_id", "reviewed_at", "reviewer_id",
    "outcome", "evidence_reference", "training_eligible", "notes",
}
ALLOWED_OUTCOMES = {
    "confirmed_tamper", "confirmed_meter_fault", "confirmed_network_fault", "confirmed_energy_discrepancy",
    "data_quality_issue", "topology_issue", "explained_technical_loss", "no_issue", "inconclusive",
}


def parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"reviewed_at is not ISO-8601: {value!r}") from error
    if timestamp.tzinfo is None:
        raise ValueError("reviewed_at must include a UTC offset")
    return timestamp.astimezone(UTC)


def load_alerts(path: Path) -> dict[str, dict[str, Any]]:
    alerts: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            alert = json.loads(line)
            alert_id = alert.get("alert_id")
            if not alert_id or alert_id in alerts:
                raise ValueError(f"{path}:{line_number} has a missing or duplicate alert_id")
            alerts[alert_id] = alert
    return alerts


def load_and_validate_outcomes(path: Path, alerts: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        outcomes: list[dict[str, Any]] = []
        seen_review_ids: set[str] = set()
        rejected: Counter[str] = Counter()
        for row_number, row in enumerate(reader, start=2):
            review_id = row["review_id"].strip()
            if not review_id or review_id in seen_review_ids:
                rejected["missing_or_duplicate_review_id"] += 1
                continue
            seen_review_ids.add(review_id)
            alert = alerts.get(row["alert_id"].strip())
            if alert is None:
                rejected["unknown_alert_id"] += 1
                continue
            if row["alert_type"].strip() != alert.get("alert_type") or row["asset_id"].strip() != alert.get("asset_id"):
                rejected["alert_type_or_asset_mismatch"] += 1
                continue
            outcome = row["outcome"].strip()
            if outcome not in ALLOWED_OUTCOMES:
                rejected["invalid_outcome"] += 1
                continue
            training_eligible = row["training_eligible"].strip().lower()
            if training_eligible not in {"true", "false"}:
                rejected["invalid_training_eligibility"] += 1
                continue
            if not row["reviewer_id"].strip() or not row["evidence_reference"].strip():
                rejected["missing_reviewer_or_evidence_reference"] += 1
                continue
            try:
                reviewed_at = parse_timestamp(row["reviewed_at"])
            except ValueError:
                rejected["invalid_reviewed_at"] += 1
                continue
            outcomes.append(
                {
                    "review_id": review_id,
                    "alert_id": row["alert_id"].strip(),
                    "alert_type": row["alert_type"].strip(),
                    "asset_id": row["asset_id"].strip(),
                    "reviewed_at": reviewed_at.isoformat(),
                    "reviewer_id": row["reviewer_id"].strip(),
                    "outcome": outcome,
                    "evidence_reference": row["evidence_reference"].strip(),
                    "training_eligible": training_eligible == "true",
                    "notes": row["notes"].strip(),
                    "alert_methodology": alert.get("methodology"),
                    "alert_evidence": alert.get("evidence"),
                }
            )
        return outcomes, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alerts", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    alerts = load_alerts(args.alerts)
    outcomes, rejections = load_and_validate_outcomes(args.outcomes, alerts)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = output_dir / "validated_investigation_outcomes.jsonl"
    with labels_path.open("w", encoding="utf-8") as destination:
        for outcome in outcomes:
            destination.write(json.dumps(outcome, sort_keys=True) + "\n")
    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "input_alert_count": len(alerts),
        "accepted_outcomes": len(outcomes),
        "rejections": dict(sorted(rejections.items())),
        "outcomes_by_type": dict(sorted(Counter(outcome["outcome"] for outcome in outcomes).items())),
        "training_eligible_outcomes": sum(outcome["training_eligible"] for outcome in outcomes),
        "safety": "Outcome labels represent recorded human review, not a legal or enforcement determination made by the system.",
    }
    (output_dir / "field_validation_run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {labels_path}")
    print(f"Validated {len(outcomes)} outcomes against {len(alerts)} alerts.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Field outcome validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
