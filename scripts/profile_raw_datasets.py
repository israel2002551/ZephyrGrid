#!/usr/bin/env python3
"""Create reproducible structural and data-quality profiles of ZephyrGrid raw data.

This program deliberately reads the raw files without changing them. It also
does not deserialize PowerBench pickle files: pickle content should be treated
as executable code until it has been reviewed in a controlled environment.

Usage:
    python scripts/profile_raw_datasets.py
    python scripts/profile_raw_datasets.py --quick
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as element_tree
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_ROOT = WORKSPACE_ROOT / "data" / "raw"
DEFAULT_REPORT_DIR = WORKSPACE_ROOT / "data" / "reports"


def file_metadata(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
    }


def decode(raw: bytes) -> str:
    """Decode source text while preserving a profile if an encoding is unusual."""
    return raw.decode("utf-8-sig", errors="replace").rstrip("\r\n")


def profile_uci(path: Path, quick: bool) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        entry = next(info for info in archive.infolist() if info.filename == "LD2011_2014.txt")
        with archive.open(entry) as source:
            header = decode(source.readline()).split(";")
            expected_columns = len(header)
            record_count = 0
            malformed_records = 0
            blank_cells = 0
            first_timestamp: str | None = None
            last_timestamp: str | None = None
            sample_timestamps: list[str] = []

            for raw_line in source:
                values = decode(raw_line).split(";")
                record_count += 1
                if len(values) != expected_columns:
                    malformed_records += 1
                    continue
                blank_cells += sum(value == "" for value in values)
                if first_timestamp is None:
                    first_timestamp = values[0]
                last_timestamp = values[0]
                if len(sample_timestamps) < 5:
                    sample_timestamps.append(values[0])
                if quick and record_count >= 5_000:
                    break

    return {
        "source": "uci_load_diagrams",
        "profile_mode": "quick" if quick else "full_structural_scan",
        "raw_file": file_metadata(path),
        "archive_entry": {"name": entry.filename, "uncompressed_bytes": entry.file_size},
        "shape": {"records": record_count, "columns": expected_columns, "clients": expected_columns - 1},
        "schema": {"timestamp_column": header[0], "first_client_columns": header[1:6]},
        "quality": {"malformed_records": malformed_records, "blank_cells": blank_cells},
        "time_coverage": {
            "first_timestamp": first_timestamp,
            "last_timestamp": last_timestamp,
            "sample_timestamps": sample_timestamps,
        },
        "notes": [
            "Values are 15-minute power readings in kW; divide by four to derive kWh.",
            "Timestamp and daylight-saving conventions must be normalised before modelling.",
        ],
    }


def profile_tdd2022(path: Path, quick: bool) -> dict[str, Any]:
    with path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source)
        header = next(reader)
        expected_columns = len(header)
        label_index = header.index("theft") if "theft" in header else expected_columns - 1
        labels: Counter[str] = Counter()
        record_count = 0
        malformed_records = 0
        blank_cells = 0

        for row in reader:
            record_count += 1
            if len(row) != expected_columns:
                malformed_records += 1
                continue
            blank_cells += sum(value == "" for value in row)
            labels[row[label_index]] += 1
            if quick and record_count >= 25_000:
                break

    return {
        "source": "tdd2022",
        "profile_mode": "quick" if quick else "full_structural_scan",
        "raw_file": file_metadata(path),
        "shape": {"records": record_count, "columns": expected_columns},
        "schema": {"columns": header, "label_column": header[label_index]},
        "quality": {"malformed_records": malformed_records, "blank_cells": blank_cells},
        "label_distribution": dict(sorted(labels.items())),
        "notes": [
            "The six theft labels are synthetically generated benchmark classes.",
            "Use this source for model comparison, not as evidence of local theft prevalence.",
        ],
    }


def profile_sgcc(path: Path, quick: bool, seven_zip: str) -> dict[str, Any]:
    """Stream the last volume of the multi-part archive through 7-Zip.

    The zip parts remain immutable and no 175 MB intermediate CSV is created.
    """
    command = [seven_zip, "x", "-so", path.name]
    process = subprocess.Popen(
        command,
        cwd=path.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    header = decode(process.stdout.readline()).split(",")
    expected_columns = len(header)
    record_count = 0
    malformed_records = 0
    labels: Counter[str] = Counter()

    for raw_line in process.stdout:
        row = decode(raw_line)
        if not row:
            continue
        record_count += 1
        column_count = row.count(",") + 1
        if column_count != expected_columns:
            malformed_records += 1
        else:
            labels[row.rsplit(",", 1)[-1]] += 1
        if quick and record_count >= 5_000:
            process.terminate()
            break

    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    return_code = process.wait()
    if return_code != 0 and not quick:
        raise RuntimeError(f"7-Zip could not stream {path.name}: {stderr.strip()}")

    return {
        "source": "ieee_sgcc_theft",
        "profile_mode": "quick" if quick else "full_structural_scan",
        "raw_files": [
            file_metadata(path.parent / "data.z01"),
            file_metadata(path.parent / "data.z02"),
            file_metadata(path),
        ],
        "shape": {"records": record_count, "columns": expected_columns},
        "schema": {"first_columns": header[:5], "last_columns": header[-5:]},
        "quality": {"malformed_records": malformed_records},
        "last_field_distribution": dict(sorted(labels.items())),
        "notes": [
            "This is a real-world daily-consumption source; inspect field semantics before creating labels.",
            "No raw archive content has been extracted by this profiler.",
        ],
    }


def spreadsheet_cell_value(cell: element_tree.Element, shared_strings: list[str], namespace: dict[str, str]) -> str:
    value = cell.findtext("x:v", default="", namespaces=namespace)
    if cell.get("t") == "s" and value:
        return shared_strings[int(value)]
    return value


def spreadsheet_column_index(cell_reference: str) -> int:
    """Return a zero-based column index for an Excel cell reference such as AD12."""
    letters = "".join(character for character in cell_reference if character.isalpha())
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter.upper()) - ord("A") + 1)
    return index - 1


def profile_nigerian_faults(path: Path) -> dict[str, Any]:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_root = element_tree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared_strings = ["".join(item.itertext()) for item in shared_root.findall("x:si", namespace)]
        worksheet = element_tree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        dimension = worksheet.find("x:dimension", namespace)
        rows = worksheet.findall(".//x:sheetData/x:row", namespace)

    parsed_rows: list[list[str]] = []
    for row in rows:
        values_by_column = {
            spreadsheet_column_index(cell.get("r", "A1")): spreadsheet_cell_value(cell, shared_strings, namespace)
            for cell in row.findall("x:c", namespace)
        }
        row_width = max(values_by_column, default=-1) + 1
        parsed_rows.append([values_by_column.get(index, "") for index in range(row_width)])
    header = parsed_rows[0]
    data_rows = parsed_rows[1:]
    active_counts = {column: 0 for column in header[4:]}
    blank_cells = 0
    malformed_records = 0
    for row in data_rows:
        if len(row) > len(header):
            malformed_records += 1
            continue
        row = row + [""] * (len(header) - len(row))
        blank_cells += sum(value == "" for value in row)
        for index, value in enumerate(row[4:], start=4):
            if value == "1":
                active_counts[header[index]] += 1

    return {
        "source": "nigerian_33kv_faults",
        "profile_mode": "full_structural_scan",
        "raw_file": file_metadata(path),
        "shape": {"records": len(data_rows), "columns": len(header)},
        "schema": {"columns": header, "worksheet_dimension": dimension.get("ref") if dimension is not None else None},
        "quality": {"malformed_records": malformed_records, "blank_cells": blank_cells},
        "event_indicator_counts": active_counts,
        "notes": [
            "Excel dates and times are serial values and require conversion before modelling.",
            "The fault indicators are multi-label: a record can contain more than one active cause or outcome.",
        ],
    }


def profile_powerbench(raw_root: Path) -> dict[str, Any]:
    archives = [
        raw_root / "Line Outage Dataset.zip",
        raw_root / "State Estimation Dataset.zip",
    ]
    archive_profiles: list[dict[str, Any]] = []
    for path in archives:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            extensions = Counter(Path(entry.filename).suffix.lower() or "[no extension]" for entry in entries if not entry.is_dir())
            top_level_directories = sorted({entry.filename.split("/", 1)[0] for entry in entries})
            archive_profiles.append(
                {
                    **file_metadata(path),
                    "entries": len(entries),
                    "uncompressed_bytes": sum(entry.file_size for entry in entries),
                    "top_level_directories": top_level_directories,
                    "file_extensions": dict(sorted(extensions.items())),
                }
            )
    return {
        "source": "powerbench_part1",
        "profile_mode": "archive_metadata_only",
        "archives": archive_profiles,
        "safety": "Pickle payloads were not deserialized during profiling.",
        "notes": [
            "PowerBench is synthetic OpenDSS data for 34-bus, 123-bus, and 8500-node systems.",
            "Review and isolate pickle deserialization before using scenario payloads in training.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Raw dataset profile summary",
        "",
        f"Generated: {report['generated_at_utc']}",
        "",
        "| Dataset | Records | Columns | Quality finding |",
        "|---|---:|---:|---|",
    ]
    for profile in report["datasets"]:
        shape = profile.get("shape", {})
        quality = profile.get("quality", {})
        finding = f"malformed={quality.get('malformed_records', 'n/a')}; blanks={quality.get('blank_cells', 'n/a')}"
        lines.append(
            f"| {profile['source']} | {shape.get('records', 'archive')} | {shape.get('columns', 'metadata')} | {finding} |"
        )
    lines.extend(
        [
            "",
            "PowerBench is intentionally profiled as archive metadata only; its pickle files are not deserialized.",
            "See `raw_dataset_profiles.json` for full schemas and distributions.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--quick", action="store_true", help="Scan representative record counts instead of every CSV row.")
    parser.add_argument("--seven-zip", default=shutil.which("7z") or shutil.which("7z.exe"))
    args = parser.parse_args()

    raw_root = args.raw_root.resolve()
    report_dir = args.report_dir.resolve()
    if not args.seven_zip:
        raise RuntimeError("7-Zip is required to stream the SGCC multi-volume archive. Pass --seven-zip PATH.")

    profiles = [
        profile_sgcc(raw_root / "ieee_sgcc_theft" / "data.zip", args.quick, args.seven_zip),
        profile_uci(raw_root / "uci_load_diagrams" / "electricityloaddiagrams20112014.zip", args.quick),
        profile_tdd2022(raw_root / "tdd2022" / "df.csv", args.quick),
        profile_nigerian_faults(raw_root / "nigerian_33kv_faults" / "Fault Pattern Dataset with Timestamp.xlsx"),
        profile_powerbench(raw_root / "powerbench_part1"),
    ]
    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "profiler_version": "1.0.0",
        "datasets": profiles,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "raw_dataset_profiles.json"
    markdown_path = report_dir / "raw_dataset_profile_summary.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path.relative_to(WORKSPACE_ROOT)}")
    print(f"Wrote {markdown_path.relative_to(WORKSPACE_ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"Profile generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
