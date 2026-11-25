#!/usr/bin/env python3
"""Build a concise, versioned registry from ZephyrGrid benchmark reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = WORKSPACE_ROOT / "models"
REPORT_ROOT = WORKSPACE_ROOT / "data" / "reports"
SPECS = [
    {
        "report": "tdd2022_benchmark_report.json",
        "status": "benchmark_only",
        "operational_function": "Revenue Protection Intelligence",
        "display_name": "TDD2022 Random Forest theft-classification benchmark",
        "metric_keys": ["accuracy", "balanced_accuracy", "macro_f1", "weighted_f1"],
    },
    {
        "report": "uci_anomaly_benchmark_report.json",
        "status": "benchmark_only",
        "operational_function": "Revenue Protection Intelligence",
        "display_name": "UCI per-client Isolation Forest anomaly benchmark",
        "metric_keys": ["anomaly_rate"],
    },
    {
        "report": "nigerian_fault_restoration_benchmark_report.json",
        "status": "benchmark_only",
        "operational_function": "Network Operations / Asset Management Intelligence",
        "display_name": "Nigerian 33 kV fault-restoration benchmark",
        "metric_keys": ["accuracy", "balanced_accuracy", "macro_f1", "weighted_f1"],
    },
]


def nested_metrics(report: dict[str, Any], metric_keys: list[str]) -> dict[str, float]:
    candidate_sections = [report.get("metrics", {}), report.get("results", {})]
    metrics: dict[str, float] = {}
    for key in metric_keys:
        for section in candidate_sections:
            if key in section:
                metrics[key] = section[key]
                break
    return metrics


def main() -> int:
    records: list[dict[str, Any]] = []
    for spec in SPECS:
        report_path = REPORT_ROOT / spec["report"]
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        records.append(
            {
                "experiment_id": report["experiment_id"],
                "display_name": spec["display_name"],
                "status": spec["status"],
                "operational_function": spec["operational_function"],
                "created_at_utc": report["generated_at_utc"],
                "purpose": report["purpose"],
                "source": report["source"],
                "artifact": report["model_artifact"],
                "report": str(report_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "metrics": nested_metrics(report, spec["metric_keys"]),
                "limitations": report["limitations"],
            }
        )
    registry = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "production_policy": "No registered model is production-eligible until it has local field validation, approved governance, model monitoring, and a deployment review.",
        "models": records,
    }
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    json_path = MODEL_ROOT / "MODEL_REGISTRY.json"
    json_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    markdown_lines = ["# ZephyrGrid model registry", "", registry["production_policy"], ""]
    markdown_lines.extend(["| Model | Function | Status | Key metrics |", "|---|---|---|---|"])
    for record in records:
        metrics = ", ".join(f"{key}={value:.4f}" for key, value in record["metrics"].items()) or "n/a"
        markdown_lines.append(f"| {record['experiment_id']} | {record['operational_function']} | {record['status']} | {metrics} |")
    markdown_lines.extend(["", "## Required before promotion", "", "- Pilot data quality and topology validation.", "- Shadow-mode evaluation against authorised investigation outcomes.", "- Approved feature contract, threshold calibration, model monitoring, and access control.", "- Human review remains mandatory for alerts and operational decisions.", ""])
    markdown_path = MODEL_ROOT / "MODEL_REGISTRY.md"
    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")
    print(f"Wrote {json_path.relative_to(WORKSPACE_ROOT)}")
    print(f"Wrote {markdown_path.relative_to(WORKSPACE_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
