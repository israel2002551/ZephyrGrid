#!/usr/bin/env python3
"""Convert the Nigerian 33 kV fault workbook into a traceable research table.

The source records have date serials and time fractions but no documented
timezone, feeder identifier, or asset identifier. This converter preserves
that uncertainty rather than claiming canonical production-quality telemetry.

Usage:
    python scripts/prepare_nigerian_fault_events.py
"""

from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as element_tree
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = WORKSPACE_ROOT / "data" / "raw" / "nigerian_33kv_faults" / "Fault Pattern Dataset with Timestamp.xlsx"
OUTPUT_PATH = WORKSPACE_ROOT / "data" / "processed" / "nigerian_33kv_fault_events.csv"
REPORT_PATH = WORKSPACE_ROOT / "data" / "reports" / "nigerian_fault_preprocessing_report.json"
NAMESPACE = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

CAUSE_COLUMNS = {
    "Ruptured HT Fuse",
    "Tree & Vegetation Fouling",
    "HT JUMPER CUT",
    "DAMAGE CROSS ARM",
    "DAMAGE POLE",
    "DETACHED LINE",
    "MAINLINE(Cut/Twist)",
    "DAMAGE INSULATOR/ISOLATOR",
    "Line Trip with No Fault Found",
    "AMINAL",
    "DOWN DROPPER/UPRISE",
    "Reclose Attempt after E/F",
    "ARRESTER",
    "CABLE FAULT",
    "FURTHER PATROL",
    "Breaker & CT Fault",
    "EQ Burnt, Explosion or Arcing",
}
LOSS_COLUMNS = {"Minimum Losses", "Moderate Losses", "High Losses", "Planned outage/ No Load Loss"}
SEASON_COLUMNS = {"Rainy", "Dry"}
MTTR_COLUMNS = {"Optimal MTTR", "Acceptable MTTR", "Suboptimal MTTR"}


def normalise_header(value: str) -> str:
    return " ".join(value.strip().split())


def spreadsheet_column_index(cell_reference: str) -> int:
    letters = "".join(character for character in cell_reference if character.isalpha())
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter.upper()) - ord("A") + 1
    return result - 1


def cell_value(cell: element_tree.Element, shared_strings: list[str]) -> str:
    value = cell.findtext("x:v", default="", namespaces=NAMESPACE)
    if cell.get("t") == "s" and value:
        return shared_strings[int(value)]
    return value


def read_workbook(path: Path) -> tuple[list[str], list[list[str]]]:
    with zipfile.ZipFile(path) as archive:
        shared_root = element_tree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared_strings = ["".join(item.itertext()) for item in shared_root.findall("x:si", NAMESPACE)]
        worksheet = element_tree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        xml_rows = worksheet.findall(".//x:sheetData/x:row", NAMESPACE)

    parsed_rows: list[list[str]] = []
    for xml_row in xml_rows:
        cells = {
            spreadsheet_column_index(cell.get("r", "A1")): cell_value(cell, shared_strings)
            for cell in xml_row.findall("x:c", NAMESPACE)
        }
        parsed_rows.append([cells.get(index, "") for index in range(max(cells, default=-1) + 1)])

    headers = [normalise_header(value) for value in parsed_rows[0]]
    rows = [row + [""] * (len(headers) - len(row)) for row in parsed_rows[1:]]
    return headers, rows


def active_labels(row: dict[str, str], labels: set[str]) -> list[str]:
    return [label for label in sorted(labels) if row.get(label) == "1"]


def serial_to_local_timestamp(date_value: str, time_value: str) -> str:
    """Convert Excel serial date/time fields while retaining unknown timezone."""
    if not date_value:
        return ""
    try:
        days = float(date_value)
        day_start = datetime(1899, 12, 30)
        timestamp = day_start + timedelta(days=days)
        if time_value:
            timestamp = timestamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=float(time_value))
        return timestamp.replace(microsecond=0).isoformat()
    except ValueError:
        return ""


def main() -> int:
    headers, rows = read_workbook(SOURCE_PATH)
    if len(headers) != 30:
        raise RuntimeError(f"Unexpected workbook schema: expected 30 columns, found {len(headers)}")

    clean_rows: list[dict[str, str]] = []
    missing_reported_timestamp = 0
    missing_restored_timestamp = 0
    multiple_cause_events = 0
    for source_row_number, values in enumerate(rows, start=2):
        source = dict(zip(headers, values, strict=True))
        causes = active_labels(source, CAUSE_COLUMNS)
        loss_categories = active_labels(source, LOSS_COLUMNS)
        seasons = active_labels(source, SEASON_COLUMNS)
        mttr_categories = active_labels(source, MTTR_COLUMNS)
        reported_at_local = serial_to_local_timestamp(source["DATE REPORTED"], source["TIME REPORTED"])
        restored_at_local = serial_to_local_timestamp(source["DATE CLEARED"], source["TIME RESTORED"])
        if not reported_at_local:
            missing_reported_timestamp += 1
        if not restored_at_local:
            missing_restored_timestamp += 1
        if len(causes) > 1:
            multiple_cause_events += 1

        clean_rows.append(
            {
                "source_dataset": "nigerian_33kv_faults_v3",
                "source_row_number": str(source_row_number),
                "event_type": "distribution_fault",
                "reported_at_local": reported_at_local,
                "restored_at_local": restored_at_local,
                "timestamp_timezone": "unknown",
                "fault_causes": ";".join(causes),
                "fault_cause_count": str(len(causes)),
                "load_loss_category": ";".join(loss_categories),
                "season": ";".join(seasons),
                "mttr_category": ";".join(mttr_categories),
                "quality_status": "suspect",
                "quality_reasons": "source_timezone_unknown;asset_and_feeder_identifier_not_supplied",
            }
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(clean_rows[0]))
        writer.writeheader()
        writer.writerows(clean_rows)

    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source": str(SOURCE_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "output": str(OUTPUT_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "records_written": len(clean_rows),
        "source_columns": headers,
        "quality": {
            "missing_reported_timestamp": missing_reported_timestamp,
            "missing_restored_timestamp": missing_restored_timestamp,
            "multi_cause_events": multiple_cause_events,
            "all_rows_marked_suspect": True,
            "reason": "The public dataset does not document timezone, feeder identifier, or asset identifier.",
        },
        "transformations": [
            "Excel serial dates and time fractions converted to timezone-unknown local ISO timestamps.",
            "One-hot cause, loss, seasonal, and MTTR columns converted to semicolon-separated multi-label fields.",
            "Raw workbook preserved unchanged; each output row retains the original Excel row number.",
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(WORKSPACE_ROOT)} ({len(clean_rows)} rows)")
    print(f"Wrote {REPORT_PATH.relative_to(WORKSPACE_ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, zipfile.BadZipFile, element_tree.ParseError) as error:
        print(f"Fault-event preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
