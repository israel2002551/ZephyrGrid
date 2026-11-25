#!/usr/bin/env python3
"""Create evidence-backed energy-balance investigation alerts from pilot CSVs.

This is a backend analytics workflow. It does not control protection devices,
switches, restoration, billing, or enforcement actions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = WORKSPACE_ROOT / "configs" / "energy_reconciliation_rules.json"
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "data" / "outputs" / "reconciliation"

MEASUREMENT_COLUMNS = {
    "measurement_id",
    "asset_id",
    "asset_type",
    "measurement_type",
    "measurement_value",
    "measurement_unit",
    "observed_at",
    "quality_status",
    "interval_minutes",
}
TOPOLOGY_COLUMNS = {
    "parent_asset_id",
    "parent_asset_type",
    "child_asset_id",
    "child_asset_type",
    "relationship_type",
    "valid_from",
    "valid_to",
    "source_reference",
}


@dataclass(frozen=True)
class Measurement:
    measurement_id: str
    asset_id: str
    asset_type: str
    value_kwh: float
    observed_at: datetime
    interval_minutes: int


@dataclass(frozen=True)
class Relationship:
    parent_asset_id: str
    parent_asset_type: str
    child_asset_id: str
    child_asset_type: str
    valid_from: datetime
    valid_to: datetime | None


def read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        header = set(reader.fieldnames or [])
        missing = sorted(required_columns - header)
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        return list(reader)


def parse_timestamp(value: str, field_name: str) -> datetime:
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} is not an ISO-8601 timestamp: {value!r}") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"{field_name} must include a UTC offset: {value!r}")
    return timestamp.astimezone(UTC)


def optional_timestamp(value: str, field_name: str) -> datetime | None:
    return parse_timestamp(value, field_name) if value else None


def floor_to_interval(timestamp: datetime, interval_minutes: int) -> datetime:
    seconds = interval_minutes * 60
    epoch_seconds = int(timestamp.timestamp())
    return datetime.fromtimestamp(epoch_seconds - epoch_seconds % seconds, tz=UTC)


def normalise_unit(value: str) -> str:
    return value.strip().lower().replace(" ", "")


def load_measurements(rows: Iterable[dict[str, str]], configured_interval: int) -> tuple[list[Measurement], Counter[str]]:
    valid_measurements: list[Measurement] = []
    rejections: Counter[str] = Counter()
    seen_measurement_ids: set[str] = set()
    for row in rows:
        measurement_id = row["measurement_id"].strip()
        if not measurement_id:
            rejections["missing_measurement_id"] += 1
            continue
        if measurement_id in seen_measurement_ids:
            rejections["duplicate_measurement_id"] += 1
            continue
        seen_measurement_ids.add(measurement_id)
        if row["quality_status"].strip().lower() != "valid":
            rejections["non_valid_quality_status"] += 1
            continue
        if row["measurement_type"].strip().lower() != "energy_import_kwh":
            rejections["unsupported_measurement_type"] += 1
            continue
        if normalise_unit(row["measurement_unit"]) != "kwh":
            rejections["unsupported_measurement_unit"] += 1
            continue
        try:
            value = float(row["measurement_value"])
            interval_minutes = int(row["interval_minutes"])
            timestamp = parse_timestamp(row["observed_at"], "observed_at")
        except ValueError:
            rejections["invalid_numeric_or_timestamp_value"] += 1
            continue
        if not math.isfinite(value) or value < 0:
            rejections["invalid_energy_value"] += 1
            continue
        if interval_minutes != configured_interval:
            rejections["unexpected_interval_minutes"] += 1
            continue
        asset_type = row["asset_type"].strip().lower()
        if asset_type not in {"meter", "transformer"}:
            rejections["unsupported_asset_type"] += 1
            continue
        valid_measurements.append(
            Measurement(
                measurement_id=measurement_id,
                asset_id=row["asset_id"].strip(),
                asset_type=asset_type,
                value_kwh=value,
                observed_at=timestamp,
                interval_minutes=interval_minutes,
            )
        )
    return valid_measurements, rejections


def load_relationships(rows: Iterable[dict[str, str]]) -> list[Relationship]:
    relationships: list[Relationship] = []
    for row in rows:
        parent_type = row["parent_asset_type"].strip().lower()
        child_type = row["child_asset_type"].strip().lower()
        if (parent_type, child_type) not in {("feeder", "transformer"), ("transformer", "meter")}:
            continue
        relationships.append(
            Relationship(
                parent_asset_id=row["parent_asset_id"].strip(),
                parent_asset_type=parent_type,
                child_asset_id=row["child_asset_id"].strip(),
                child_asset_type=child_type,
                valid_from=parse_timestamp(row["valid_from"], "valid_from"),
                valid_to=optional_timestamp(row["valid_to"], "valid_to"),
            )
        )
    return relationships


def active_topology(relationships: Iterable[Relationship], timestamp: datetime) -> tuple[dict[str, str], dict[str, set[str]]]:
    feeder_by_transformer: dict[str, str] = {}
    meters_by_transformer: dict[str, set[str]] = defaultdict(set)
    for relationship in relationships:
        if timestamp < relationship.valid_from or (relationship.valid_to and timestamp >= relationship.valid_to):
            continue
        if relationship.parent_asset_type == "feeder":
            feeder_by_transformer[relationship.child_asset_id] = relationship.parent_asset_id
        else:
            meters_by_transformer[relationship.parent_asset_id].add(relationship.child_asset_id)
    return feeder_by_transformer, meters_by_transformer


def severity(ratio: float, thresholds: dict[str, float]) -> str:
    for level in ("critical", "high", "medium"):
        if ratio >= thresholds[level]:
            return level
    return "medium"


def stable_alert_id(transformer_id: str, period_start: datetime, methodology: str) -> str:
    payload = f"energy_discrepancy|{transformer_id}|{period_start.isoformat()}|{methodology}".encode("utf-8")
    return f"eab_{hashlib.sha256(payload).hexdigest()[:20]}"


def csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reconcile(
    measurements: list[Measurement],
    relationships: list[Relationship],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    interval_minutes = int(rules["interval_minutes"])
    methodology = rules["methodology"]
    records_by_bucket_asset: dict[tuple[datetime, str], list[Measurement]] = defaultdict(list)
    for measurement in measurements:
        bucket = floor_to_interval(measurement.observed_at, interval_minutes)
        records_by_bucket_asset[(bucket, measurement.asset_id)].append(measurement)

    buckets = sorted({bucket for bucket, _ in records_by_bucket_asset})
    balance_rows: list[dict[str, Any]] = []
    alert_rows: list[dict[str, Any]] = []
    for bucket in buckets:
        feeder_by_transformer, meters_by_transformer = active_topology(relationships, bucket)
        upstream_transformers = {
            asset_id
            for (record_bucket, asset_id), records in records_by_bucket_asset.items()
            if record_bucket == bucket and records[0].asset_type == "transformer"
        }
        for transformer_id in sorted(upstream_transformers):
            upstream_records = records_by_bucket_asset[(bucket, transformer_id)]
            upstream_energy = sum(record.value_kwh for record in upstream_records)
            expected_meters = meters_by_transformer.get(transformer_id, set())
            meter_records = {
                meter_id: records_by_bucket_asset.get((bucket, meter_id), []) for meter_id in expected_meters
            }
            observed_meter_ids = {meter_id for meter_id, records in meter_records.items() if records}
            downstream_energy = sum(record.value_kwh for records in meter_records.values() for record in records)
            duplicate_upstream_records = max(0, len(upstream_records) - 1)
            duplicate_meter_records = sum(max(0, len(records) - 1) for records in meter_records.values())
            expected_meter_count = len(expected_meters)
            observed_meter_count = len(observed_meter_ids)
            coverage = observed_meter_count / expected_meter_count if expected_meter_count else 0.0
            expected_loss = upstream_energy * float(rules["expected_technical_loss_rate"])
            unexplained_energy = upstream_energy - downstream_energy - expected_loss
            unexplained_ratio = unexplained_energy / upstream_energy if upstream_energy else 0.0
            quality_reasons: list[str] = []
            if not expected_meter_count:
                quality_reasons.append("no_active_meter_topology")
            if duplicate_upstream_records:
                quality_reasons.append("duplicate_upstream_measurement")
            if duplicate_meter_records:
                quality_reasons.append("duplicate_meter_measurement")
            if coverage < float(rules["minimum_meter_coverage"]):
                quality_reasons.append("insufficient_meter_coverage")
            quality_status = "valid" if not quality_reasons else "suspect"
            period_end = bucket + timedelta(minutes=interval_minutes)
            alert_eligible = (
                quality_status == "valid"
                and upstream_energy >= float(rules["minimum_upstream_energy_kwh"])
                and unexplained_energy >= float(rules["minimum_unexplained_energy_kwh"])
                and unexplained_ratio >= float(rules["minimum_unexplained_energy_ratio"])
            )
            balance_row = {
                "transformer_id": transformer_id,
                "feeder_id": feeder_by_transformer.get(transformer_id, ""),
                "period_start_utc": bucket.isoformat(),
                "period_end_utc": period_end.isoformat(),
                "upstream_energy_kwh": round(upstream_energy, 6),
                "downstream_energy_kwh": round(downstream_energy, 6),
                "expected_technical_loss_kwh": round(expected_loss, 6),
                "unexplained_energy_kwh": round(unexplained_energy, 6),
                "unexplained_energy_ratio": round(unexplained_ratio, 6),
                "expected_meter_count": expected_meter_count,
                "observed_meter_count": observed_meter_count,
                "meter_coverage": round(coverage, 6),
                "duplicate_upstream_records": duplicate_upstream_records,
                "duplicate_meter_records": duplicate_meter_records,
                "quality_status": quality_status,
                "quality_reasons": ";".join(quality_reasons),
                "alert_generated": str(alert_eligible).lower(),
            }
            balance_rows.append(balance_row)
            if alert_eligible:
                evidence = {
                    key: balance_row[key]
                    for key in (
                        "upstream_energy_kwh",
                        "downstream_energy_kwh",
                        "expected_technical_loss_kwh",
                        "unexplained_energy_kwh",
                        "unexplained_energy_ratio",
                        "expected_meter_count",
                        "observed_meter_count",
                        "meter_coverage",
                        "quality_status",
                    )
                }
                alert_rows.append(
                    {
                        "alert_id": stable_alert_id(transformer_id, bucket, methodology),
                        "alert_type": "energy_discrepancy",
                        "alert_state": "investigation_required",
                        "severity": severity(unexplained_ratio, rules["severity_thresholds"]),
                        "asset_id": transformer_id,
                        "feeder_id": feeder_by_transformer.get(transformer_id, "") or None,
                        "period_start_utc": bucket.isoformat(),
                        "period_end_utc": period_end.isoformat(),
                        "methodology": methodology,
                        "confidence": round(coverage, 6),
                        "evidence_json": json.dumps(evidence, sort_keys=True),
                        "recommended_action": "Review topology, data quality, technical-loss assumptions, and field evidence before opening an investigation.",
                    }
                )
    return balance_rows, alert_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    raw_measurements = read_csv(args.measurements, MEASUREMENT_COLUMNS)
    raw_topology = read_csv(args.topology, TOPOLOGY_COLUMNS)
    measurements, rejections = load_measurements(raw_measurements, int(rules["interval_minutes"]))
    relationships = load_relationships(raw_topology)
    balance_rows, alert_rows = reconcile(measurements, relationships, rules)

    output_dir = args.output_dir.resolve()
    csv_write(output_dir / "balance_intervals.csv", balance_rows)
    csv_write(output_dir / "reconciliation_alerts.csv", alert_rows)
    run_report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "methodology": rules["methodology"],
        "inputs": {
            "measurement_rows": len(raw_measurements),
            "accepted_measurements": len(measurements),
            "measurement_rejections": dict(sorted(rejections.items())),
            "topology_rows": len(raw_topology),
            "accepted_relevant_relationships": len(relationships),
        },
        "outputs": {"balance_intervals": len(balance_rows), "investigation_alerts": len(alert_rows)},
        "safety": "Alerts require human investigation. The workflow has no switching, billing, or enforcement action.",
    }
    (output_dir / "reconciliation_run_report.json").write_text(json.dumps(run_report, indent=2), encoding="utf-8")
    print(f"Wrote {output_dir / 'balance_intervals.csv'}")
    print(f"Wrote {output_dir / 'reconciliation_alerts.csv'}")
    print(f"Generated {len(alert_rows)} investigation alerts from {len(balance_rows)} balances.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Energy reconciliation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
