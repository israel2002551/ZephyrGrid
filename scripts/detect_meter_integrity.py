#!/usr/bin/env python3
"""Generate investigation-only meter integrity alerts from validated events."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = WORKSPACE_ROOT / "configs" / "meter_integrity_rules.json"
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "data" / "outputs" / "meter_integrity"
REQUIRED_COLUMNS = {"event_id", "device_id", "asset_id", "observed_at", "event_type", "quality_status"}


@dataclass(frozen=True)
class MeterEvent:
    event_id: str
    device_id: str
    asset_id: str
    observed_at: datetime
    event_type: str


def parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"observed_at is not ISO-8601: {value!r}") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"observed_at must include a UTC offset: {value!r}")
    return timestamp.astimezone(UTC)


def read_events(path: Path) -> tuple[list[MeterEvent], Counter[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        accepted: list[MeterEvent] = []
        rejected: Counter[str] = Counter()
        seen_ids: set[str] = set()
        for row in reader:
            event_id = row["event_id"].strip()
            if not event_id:
                rejected["missing_event_id"] += 1
                continue
            if event_id in seen_ids:
                rejected["duplicate_event_id"] += 1
                continue
            seen_ids.add(event_id)
            if row["quality_status"].strip().lower() != "valid":
                rejected["non_valid_quality_status"] += 1
                continue
            if not row["device_id"].strip() or not row["asset_id"].strip():
                rejected["missing_device_or_asset_id"] += 1
                continue
            try:
                observed_at = parse_timestamp(row["observed_at"])
            except ValueError:
                rejected["invalid_timestamp"] += 1
                continue
            accepted.append(
                MeterEvent(
                    event_id=event_id,
                    device_id=row["device_id"].strip(),
                    asset_id=row["asset_id"].strip(),
                    observed_at=observed_at,
                    event_type=row["event_type"].strip().lower(),
                )
            )
    return accepted, rejected


def stable_alert_id(alert_type: str, device_id: str, first_event: datetime, event_ids: list[str]) -> str:
    payload = f"{alert_type}|{device_id}|{first_event.isoformat()}|{'|'.join(event_ids)}".encode("utf-8")
    return f"mai_{hashlib.sha256(payload).hexdigest()[:20]}"


def make_alert(
    *,
    alert_type: str,
    severity: str,
    event: MeterEvent,
    evidence_event_ids: list[str],
    rule: str,
    window_start: datetime,
    window_end: datetime,
    extra_evidence: dict[str, Any] | None = None,
) -> dict[str, str]:
    evidence: dict[str, Any] = {
        "source_event_ids": evidence_event_ids,
        "event_count": len(evidence_event_ids),
        "rule": rule,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": window_end.isoformat(),
    }
    if extra_evidence:
        evidence.update(extra_evidence)
    return {
        "alert_id": stable_alert_id(alert_type, event.device_id, window_start, evidence_event_ids),
        "alert_type": alert_type,
        "alert_state": "investigation_required",
        "severity": severity,
        "device_id": event.device_id,
        "asset_id": event.asset_id,
        "period_start_utc": window_start.isoformat(),
        "period_end_utc": window_end.isoformat(),
        "methodology": "meter_integrity_rules_v1",
        "confidence": "1.0",
        "evidence_json": json.dumps(evidence, sort_keys=True),
        "recommended_action": "Review device diagnostics, communications history, topology, and authorised field evidence before deciding the cause.",
    }


def rolling_threshold_alerts(
    events: list[MeterEvent],
    event_type: str,
    alert_type: str,
    severity: str,
    window_minutes: int,
    minimum_events: int,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    per_device: dict[str, list[MeterEvent]] = defaultdict(list)
    for event in events:
        if event.event_type == event_type:
            per_device[event.device_id].append(event)
    for device_events in per_device.values():
        device_events.sort(key=lambda item: item.observed_at)
        window: deque[MeterEvent] = deque()
        last_alert_end: datetime | None = None
        for event in device_events:
            window.append(event)
            cutoff = event.observed_at - timedelta(minutes=window_minutes)
            while window and window[0].observed_at < cutoff:
                window.popleft()
            if len(window) >= minimum_events and (last_alert_end is None or event.observed_at > last_alert_end):
                event_ids = [item.event_id for item in window]
                alerts.append(
                    make_alert(
                        alert_type=alert_type,
                        severity=severity,
                        event=event,
                        evidence_event_ids=event_ids,
                        rule=f"{minimum_events}+ {event_type} events within {window_minutes} minutes",
                        window_start=window[0].observed_at,
                        window_end=event.observed_at,
                    )
                )
                last_alert_end = event.observed_at
    return alerts


def detect_alerts(events: list[MeterEvent], rules: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    direct_tamper_types = set(rules["direct_tamper_event_types"])
    for event in events:
        if event.event_type in direct_tamper_types:
            alerts.append(
                make_alert(
                    alert_type="meter_tamper_event",
                    severity=rules["direct_tamper_severity"],
                    event=event,
                    evidence_event_ids=[event.event_id],
                    rule=f"direct tamper event: {event.event_type}",
                    window_start=event.observed_at,
                    window_end=event.observed_at,
                )
            )
    alerts.extend(
        rolling_threshold_alerts(
            events,
            "device_reset",
            "repeated_device_reset",
            "medium",
            int(rules["reset_window_minutes"]),
            int(rules["minimum_resets_per_window"]),
        )
    )
    alerts.extend(
        rolling_threshold_alerts(
            events,
            "authentication_failure",
            "repeated_authentication_failure",
            "high",
            int(rules["authentication_window_minutes"]),
            int(rules["minimum_authentication_failures_per_window"]),
        )
    )
    readings_by_device: dict[str, list[MeterEvent]] = defaultdict(list)
    for event in events:
        if event.event_type == "reading_received":
            readings_by_device[event.device_id].append(event)
    minimum_gap = int(rules["minimum_missing_reading_gap_minutes"])
    for device_events in readings_by_device.values():
        device_events.sort(key=lambda item: item.observed_at)
        for previous, current in zip(device_events, device_events[1:]):
            gap_minutes = (current.observed_at - previous.observed_at).total_seconds() / 60
            if gap_minutes >= minimum_gap:
                alerts.append(
                    make_alert(
                        alert_type="meter_communication_gap",
                        severity="medium",
                        event=current,
                        evidence_event_ids=[previous.event_id, current.event_id],
                        rule=f"reading gap >= {minimum_gap} minutes",
                        window_start=previous.observed_at,
                        window_end=current.observed_at,
                        extra_evidence={"gap_minutes": gap_minutes},
                    )
                )
    return sorted(alerts, key=lambda alert: (alert["period_start_utc"], alert["alert_type"], alert["device_id"]))


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
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    events, rejections = read_events(args.events)
    alerts = detect_alerts(events, rules)
    output_dir = args.output_dir.resolve()
    write_csv(output_dir / "meter_integrity_alerts.csv", alerts)
    run_report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "methodology": rules["methodology"],
        "inputs": {"accepted_events": len(events), "rejections": dict(sorted(rejections.items()))},
        "outputs": {"investigation_alerts": len(alerts), "alerts_by_type": dict(Counter(alert["alert_type"] for alert in alerts))},
        "safety": "Alerts require human investigation. The workflow has no billing, enforcement, or electrical-control action.",
    }
    (output_dir / "meter_integrity_run_report.json").write_text(json.dumps(run_report, indent=2), encoding="utf-8")
    print(f"Wrote {output_dir / 'meter_integrity_alerts.csv'}")
    print(f"Generated {len(alerts)} investigation alerts from {len(events)} validated events.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Meter integrity detection failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
