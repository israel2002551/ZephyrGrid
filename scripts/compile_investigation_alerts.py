#!/usr/bin/env python3
"""Validate and combine component alerts into one human-review JSONL feed."""

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
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "data" / "outputs" / "unified_alerts"
REQUIRED_COLUMNS = {
    "alert_id", "alert_type", "alert_state", "severity", "asset_id", "period_start_utc", "period_end_utc",
    "methodology", "confidence", "evidence_json", "recommended_action",
}
VALID_SEVERITIES = {"medium", "high", "critical"}


def parse_timestamp(value: str, name: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} is not ISO-8601: {value!r}") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include a UTC offset")
    return timestamp.astimezone(UTC)


def read_alerts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.read_text(encoding="utf-8-sig").strip():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path} is missing required alert columns: {', '.join(missing)}")
        alerts: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):
            if row["alert_state"] != "investigation_required":
                raise ValueError(f"{path}:{row_number} has forbidden alert_state {row['alert_state']!r}")
            if row["severity"] not in VALID_SEVERITIES:
                raise ValueError(f"{path}:{row_number} has invalid severity {row['severity']!r}")
            try:
                confidence = float(row["confidence"])
            except ValueError as error:
                raise ValueError(f"{path}:{row_number} has invalid confidence") from error
            if not 0 <= confidence <= 1:
                raise ValueError(f"{path}:{row_number} confidence must be between zero and one")
            start = parse_timestamp(row["period_start_utc"], "period_start_utc")
            end = parse_timestamp(row["period_end_utc"], "period_end_utc")
            if end < start:
                raise ValueError(f"{path}:{row_number} ends before it starts")
            try:
                evidence = json.loads(row["evidence_json"])
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{row_number} has invalid evidence_json") from error
            if not isinstance(evidence, dict):
                raise ValueError(f"{path}:{row_number} evidence_json must be an object")
            alerts.append(
                {
                    "alert_id": row["alert_id"],
                    "alert_type": row["alert_type"],
                    "alert_state": row["alert_state"],
                    "severity": row["severity"],
                    "asset_id": row["asset_id"],
                    "feeder_id": row.get("feeder_id") or None,
                    "device_id": row.get("device_id") or None,
                    "period_start_utc": start.isoformat(),
                    "period_end_utc": end.isoformat(),
                    "methodology": row["methodology"],
                    "confidence": confidence,
                    "evidence": evidence,
                    "recommended_action": row["recommended_action"],
                    "source_file": str(path),
                }
            )
        return alerts


def deduplicate(alerts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for alert in alerts:
        alert_id = alert["alert_id"]
        existing = by_id.get(alert_id)
        if existing is None:
            by_id[alert_id] = alert
            continue
        comparable_existing = {key: value for key, value in existing.items() if key != "source_file"}
        comparable_new = {key: value for key, value in alert.items() if key != "source_file"}
        if comparable_existing != comparable_new:
            raise ValueError(f"Conflicting alerts share alert_id {alert_id!r}")
        duplicate_count += 1
    ordered = sorted(by_id.values(), key=lambda item: (item["period_start_utc"], item["severity"], item["alert_id"]))
    return ordered, duplicate_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alert-file", type=Path, action="append", required=True, help="Component CSV alert file; repeat for each source.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    incoming = [alert for path in args.alert_file for alert in read_alerts(path)]
    alerts, duplicate_count = deduplicate(incoming)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    feed_path = output_dir / "investigation_alerts.jsonl"
    with feed_path.open("w", encoding="utf-8") as destination:
        for alert in alerts:
            destination.write(json.dumps(alert, sort_keys=True) + "\n")
    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "input_files": [str(path) for path in args.alert_file],
        "incoming_alerts": len(incoming),
        "duplicate_alerts_removed": duplicate_count,
        "output_alerts": len(alerts),
        "alerts_by_type": dict(sorted(Counter(alert["alert_type"] for alert in alerts).items())),
        "alerts_by_severity": dict(sorted(Counter(alert["severity"] for alert in alerts).items())),
        "safety": "All alerts are investigation_required. This feed performs no billing, enforcement, switching, or restoration action.",
    }
    (output_dir / "unified_alert_run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {feed_path}")
    print(f"Bundled {len(alerts)} investigation alerts from {len(args.alert_file)} source files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"Alert compilation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
