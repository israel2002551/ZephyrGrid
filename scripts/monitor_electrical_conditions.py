#!/usr/bin/env python3
"""Generate investigation-only voltage and current condition alerts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = WORKSPACE_ROOT / "configs" / "electrical_condition_rules.json"
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "data" / "outputs" / "electrical_conditions"
MEASUREMENT_COLUMNS = {
    "measurement_id", "asset_id", "asset_type", "measurement_type", "measurement_value",
    "measurement_unit", "phase", "observed_at", "quality_status",
}
LIMIT_COLUMNS = {
    "asset_id", "asset_type", "nominal_voltage_v", "min_voltage_pu", "max_voltage_pu", "max_current_a", "source_reference",
}


@dataclass(frozen=True)
class AssetLimit:
    asset_id: str
    asset_type: str
    nominal_voltage_v: float
    min_voltage_pu: float
    max_voltage_pu: float
    max_current_a: float
    source_reference: str


@dataclass(frozen=True)
class Measurement:
    measurement_id: str
    asset_id: str
    asset_type: str
    measurement_type: str
    value: float
    phase: str
    observed_at: datetime


def read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = sorted(required_columns - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        return list(reader)


def parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid observed_at timestamp: {value!r}") from error
    if timestamp.tzinfo is None:
        raise ValueError("observed_at must include a UTC offset")
    return timestamp.astimezone(UTC)


def load_asset_limits(rows: list[dict[str, str]]) -> dict[str, AssetLimit]:
    limits: dict[str, AssetLimit] = {}
    for row in rows:
        asset_id = row["asset_id"].strip()
        if not asset_id or asset_id in limits:
            raise ValueError(f"Asset limits require unique, non-empty asset_id values; issue found for {asset_id!r}")
        try:
            limit = AssetLimit(
                asset_id=asset_id,
                asset_type=row["asset_type"].strip().lower(),
                nominal_voltage_v=float(row["nominal_voltage_v"]),
                min_voltage_pu=float(row["min_voltage_pu"]),
                max_voltage_pu=float(row["max_voltage_pu"]),
                max_current_a=float(row["max_current_a"]),
                source_reference=row["source_reference"].strip(),
            )
        except ValueError as error:
            raise ValueError(f"Invalid numeric limit for asset {asset_id}") from error
        if (
            limit.asset_type not in {"transformer", "feeder"}
            or limit.nominal_voltage_v <= 0
            or not 0 < limit.min_voltage_pu < limit.max_voltage_pu
            or limit.max_current_a <= 0
        ):
            raise ValueError(f"Invalid engineering limit range for asset {asset_id}")
        limits[asset_id] = limit
    return limits


def load_measurements(rows: list[dict[str, str]]) -> tuple[list[Measurement], Counter[str]]:
    accepted: list[Measurement] = []
    rejected: Counter[str] = Counter()
    seen_ids: set[str] = set()
    expected_units = {"voltage_v": "v", "current_a": "a"}
    for row in rows:
        measurement_id = row["measurement_id"].strip()
        if not measurement_id:
            rejected["missing_measurement_id"] += 1
            continue
        if measurement_id in seen_ids:
            rejected["duplicate_measurement_id"] += 1
            continue
        seen_ids.add(measurement_id)
        if row["quality_status"].strip().lower() != "valid":
            rejected["non_valid_quality_status"] += 1
            continue
        asset_type = row["asset_type"].strip().lower()
        measurement_type = row["measurement_type"].strip().lower()
        unit = row["measurement_unit"].strip().lower()
        if asset_type not in {"transformer", "feeder"}:
            rejected["unsupported_asset_type"] += 1
            continue
        if measurement_type not in expected_units:
            rejected["unsupported_measurement_type"] += 1
            continue
        if unit != expected_units[measurement_type]:
            rejected["unexpected_measurement_unit"] += 1
            continue
        try:
            value = float(row["measurement_value"])
            timestamp = parse_timestamp(row["observed_at"])
        except ValueError:
            rejected["invalid_numeric_or_timestamp_value"] += 1
            continue
        if not math.isfinite(value) or value < 0:
            rejected["invalid_measurement_value"] += 1
            continue
        accepted.append(
            Measurement(
                measurement_id=measurement_id,
                asset_id=row["asset_id"].strip(),
                asset_type=asset_type,
                measurement_type=measurement_type,
                value=value,
                phase=row["phase"].strip().lower() or "total",
                observed_at=timestamp,
            )
        )
    return accepted, rejected


def stable_alert_id(measurement: Measurement, alert_type: str) -> str:
    payload = f"{alert_type}|{measurement.measurement_id}|{measurement.asset_id}".encode("utf-8")
    return f"eca_{hashlib.sha256(payload).hexdigest()[:20]}"


def condition_alert(
    measurement: Measurement,
    asset_limit: AssetLimit,
    alert_type: str,
    severity: str,
    evidence: dict[str, Any],
) -> dict[str, str]:
    return {
        "alert_id": stable_alert_id(measurement, alert_type),
        "alert_type": alert_type,
        "alert_state": "investigation_required",
        "severity": severity,
        "asset_id": measurement.asset_id,
        "asset_type": measurement.asset_type,
        "phase": measurement.phase,
        "period_start_utc": measurement.observed_at.isoformat(),
        "period_end_utc": measurement.observed_at.isoformat(),
        "methodology": "electrical_condition_rules_v1",
        "confidence": "1.0",
        "evidence_json": json.dumps(
            {"source_measurement_id": measurement.measurement_id, "engineering_limit_source": asset_limit.source_reference, **evidence},
            sort_keys=True,
        ),
        "recommended_action": "Review authorised operating limits, measurement quality, connected assets, and protection-system records. Do not use this alert as a switching command.",
    }


def detect_conditions(measurements: list[Measurement], limits: dict[str, AssetLimit], rules: dict[str, Any]) -> tuple[list[dict[str, str]], Counter[str]]:
    alerts: list[dict[str, str]] = []
    skipped: Counter[str] = Counter()
    for measurement in measurements:
        asset_limit = limits.get(measurement.asset_id)
        if asset_limit is None:
            skipped["missing_asset_limit"] += 1
            continue
        if asset_limit.asset_type != measurement.asset_type:
            skipped["asset_type_limit_mismatch"] += 1
            continue
        if measurement.measurement_type == "voltage_v":
            per_unit = measurement.value / asset_limit.nominal_voltage_v
            if not asset_limit.min_voltage_pu <= per_unit <= asset_limit.max_voltage_pu:
                deviation = abs(1.0 - per_unit)
                severity = "critical" if deviation >= float(rules["voltage_critical_deviation_pu"]) else "high"
                alerts.append(
                    condition_alert(
                        measurement,
                        asset_limit,
                        "voltage_out_of_range",
                        severity,
                        {
                            "measurement_value_v": measurement.value,
                            "per_unit_voltage": per_unit,
                            "minimum_voltage_pu": asset_limit.min_voltage_pu,
                            "maximum_voltage_pu": asset_limit.max_voltage_pu,
                        },
                    )
                )
        else:
            ratio = measurement.value / asset_limit.max_current_a
            if ratio > 1.0:
                severity = "critical" if ratio >= float(rules["current_critical_ratio"]) else "high"
                alerts.append(
                    condition_alert(
                        measurement,
                        asset_limit,
                        "current_overload",
                        severity,
                        {"measurement_value_a": measurement.value, "maximum_current_a": asset_limit.max_current_a, "current_ratio": ratio},
                    )
                )
    return alerts, skipped


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--asset-limits", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    limits = load_asset_limits(read_csv(args.asset_limits, LIMIT_COLUMNS))
    measurements, rejections = load_measurements(read_csv(args.measurements, MEASUREMENT_COLUMNS))
    alerts, skipped = detect_conditions(measurements, limits, rules)
    output_dir = args.output_dir.resolve()
    write_csv(output_dir / "electrical_condition_alerts.csv", alerts)
    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "methodology": rules["methodology"],
        "inputs": {
            "asset_limits": len(limits),
            "accepted_measurements": len(measurements),
            "measurement_rejections": dict(sorted(rejections.items())),
            "measurements_skipped_after_validation": dict(sorted(skipped.items())),
        },
        "outputs": {"investigation_alerts": len(alerts), "alerts_by_type": dict(Counter(alert["alert_type"] for alert in alerts))},
        "safety": "Alerts require human review. This workflow never controls switching, protection, or restoration.",
    }
    (output_dir / "electrical_condition_run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {output_dir / 'electrical_condition_alerts.csv'}")
    print(f"Generated {len(alerts)} investigation alerts from {len(measurements)} validated measurements.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Electrical condition monitoring failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
