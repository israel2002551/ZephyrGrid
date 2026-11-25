#!/usr/bin/env python3
"""Train a benchmark-only per-client Isolation Forest on UCI load profiles.

This builds daily features from 15-minute UCI load readings without extracting
the raw archive. It flags statistically unusual days, not electricity theft.
The resulting model is a pipeline benchmark for ZephyrGrid's revenue-
protection workflow and is not valid for customer enforcement or production.

Usage:
    python scripts/train_uci_consumption_anomaly_baseline.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy
import pandas
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = WORKSPACE_ROOT / "data" / "raw" / "uci_load_diagrams" / "electricityloaddiagrams20112014.zip"
PROFILE_PATH = WORKSPACE_ROOT / "data" / "processed" / "uci_daily_profiles_benchmark.csv"
MODEL_PATH = WORKSPACE_ROOT / "models" / "uci_isolation_forest_benchmark.joblib"
REPORT_PATH = WORKSPACE_ROOT / "data" / "reports" / "uci_anomaly_benchmark_report.json"
FEATURE_COLUMNS = [
    "daily_energy_kwh",
    "peak_kw",
    "mean_kw",
    "load_factor",
    "zero_interval_ratio",
    "overnight_energy_share",
]


def to_float(value: str) -> float:
    """UCI may encode decimals with either a full stop or a comma."""
    return float(value.replace(",", "."))


def build_daily_profiles(max_clients: int) -> tuple[pandas.DataFrame, dict[str, int]]:
    """Aggregate UCI 15-minute readings into one feature vector per client-day."""
    profiles: list[dict[str, float | int | str]] = []
    invalid_values = 0
    incomplete_client_days = 0

    with zipfile.ZipFile(SOURCE_PATH) as archive:
        entry = next(item for item in archive.infolist() if item.filename == "LD2011_2014.txt")
        with archive.open(entry) as binary_source:
            text_source = (line.decode("utf-8-sig", errors="replace") for line in binary_source)
            reader = csv.reader(text_source, delimiter=";")
            header = next(reader)
            client_ids = header[1 : max_clients + 1]
            if not client_ids:
                raise RuntimeError("No UCI client columns were found.")

            current_day: str | None = None
            interval_count = 0
            total_kw = numpy.zeros(len(client_ids), dtype=float)
            peak_kw = numpy.full(len(client_ids), -numpy.inf, dtype=float)
            zero_count = numpy.zeros(len(client_ids), dtype=int)
            overnight_kw = numpy.zeros(len(client_ids), dtype=float)

            def flush_day() -> None:
                nonlocal incomplete_client_days
                if current_day is None:
                    return
                if interval_count != 96:
                    incomplete_client_days += len(client_ids)
                    return
                mean_kw = total_kw / interval_count
                daily_kwh = total_kw / 4.0
                with numpy.errstate(divide="ignore", invalid="ignore"):
                    load_factor = numpy.divide(mean_kw, peak_kw, out=numpy.zeros_like(mean_kw), where=peak_kw > 0)
                    overnight_share = numpy.divide(
                        overnight_kw,
                        total_kw,
                        out=numpy.zeros_like(overnight_kw),
                        where=total_kw > 0,
                    )
                for index, client_id in enumerate(client_ids):
                    profiles.append(
                        {
                            "client_id": client_id,
                            "date": current_day,
                            "daily_energy_kwh": float(daily_kwh[index]),
                            "peak_kw": float(peak_kw[index]),
                            "mean_kw": float(mean_kw[index]),
                            "load_factor": float(load_factor[index]),
                            "zero_interval_ratio": float(zero_count[index] / interval_count),
                            "overnight_energy_share": float(overnight_share[index]),
                        }
                    )

            for row in reader:
                if len(row) < max_clients + 1:
                    raise RuntimeError(f"UCI row has {len(row)} columns; expected at least {max_clients + 1}.")
                timestamp = row[0]
                day = timestamp[:10]
                hour = int(timestamp[11:13])
                if current_day is not None and day != current_day:
                    flush_day()
                    interval_count = 0
                    total_kw.fill(0.0)
                    peak_kw.fill(-numpy.inf)
                    zero_count.fill(0)
                    overnight_kw.fill(0.0)
                current_day = day
                values = numpy.empty(len(client_ids), dtype=float)
                for index, value in enumerate(row[1 : max_clients + 1]):
                    try:
                        values[index] = to_float(value)
                    except ValueError:
                        invalid_values += 1
                        values[index] = numpy.nan
                if numpy.isnan(values).any():
                    raise RuntimeError("UCI contains an invalid numeric value in the selected client range.")
                total_kw += values
                peak_kw = numpy.maximum(peak_kw, values)
                zero_count += values == 0.0
                if hour < 6:
                    overnight_kw += values
                interval_count += 1
            flush_day()

    return pandas.DataFrame(profiles), {
        "clients": len(client_ids),
        "invalid_numeric_values": invalid_values,
        "incomplete_client_days_skipped": incomplete_client_days,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-clients", type=int, default=50)
    parser.add_argument("--trees", type=int, default=100)
    parser.add_argument("--contamination", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=20261125)
    args = parser.parse_args()
    if not 1 <= args.max_clients <= 370:
        raise ValueError("max-clients must be between 1 and 370.")
    if args.trees < 1 or not 0 < args.contamination < 0.5:
        raise ValueError("trees must be positive and contamination must be between zero and 0.5.")

    profiles, input_quality = build_daily_profiles(args.max_clients)
    if profiles.empty:
        raise RuntimeError("No complete client-day profiles were produced.")

    models: dict[str, dict[str, object]] = {}
    scored_profiles: list[pandas.DataFrame] = []
    for client_number, (client_id, client_profiles) in enumerate(profiles.groupby("client_id", sort=True)):
        ordered = client_profiles.sort_values("date").copy()
        if len(ordered) < 365:
            continue
        scaler = StandardScaler()
        matrix = scaler.fit_transform(ordered[FEATURE_COLUMNS])
        model = IsolationForest(
            n_estimators=args.trees,
            contamination=args.contamination,
            random_state=args.seed + client_number,
            n_jobs=-1,
        )
        model.fit(matrix)
        ordered["anomaly_score"] = -model.score_samples(matrix)
        ordered["is_anomalous"] = model.predict(matrix) == -1
        scored_profiles.append(ordered)
        models[str(client_id)] = {"scaler": scaler, "model": model}

    scored = pandas.concat(scored_profiles, ignore_index=True)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(PROFILE_PATH, index=False)
    joblib.dump(
        {
            "models": models,
            "feature_columns": FEATURE_COLUMNS,
            "metadata": {
                "experiment_id": "uci_isolation_forest_benchmark_v1",
                "purpose": "Unsupervised consumption anomaly benchmark only; not theft detection.",
                "source": str(SOURCE_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "limitations": [
                    "UCI records are not Nigerian DisCo data and include no verified theft labels.",
                    "The model is fitted retrospectively over each client's full history; it is not a prospective field evaluation.",
                    "An anomaly is an investigation signal, never proof of theft.",
                ],
            },
        },
        MODEL_PATH,
    )
    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "experiment_id": "uci_isolation_forest_benchmark_v1",
        "purpose": "Unsupervised consumption anomaly benchmark only; not theft detection.",
        "source": str(SOURCE_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "output_profiles": str(PROFILE_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "model_artifact": str(MODEL_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "data": {
            "client_count": int(scored["client_id"].nunique()),
            "daily_profile_count": int(len(scored)),
            "date_range": {"from": str(scored["date"].min()), "to": str(scored["date"].max())},
            "feature_columns": FEATURE_COLUMNS,
            "input_quality": input_quality,
        },
        "model": {
            "algorithm": "IsolationForest per client",
            "trees_per_client": args.trees,
            "contamination": args.contamination,
            "random_seed": args.seed,
        },
        "results": {
            "anomalies_flagged": int(scored["is_anomalous"].sum()),
            "anomaly_rate": float(scored["is_anomalous"].mean()),
            "anomalies_by_client": {
                client: int(count)
                for client, count in scored.loc[scored["is_anomalous"]].groupby("client_id").size().sort_index().items()
            },
        },
        "limitations": [
            "UCI records are not Nigerian DisCo data and include no verified theft labels.",
            "The model is fitted retrospectively over each client's full history; it is not a prospective field evaluation.",
            "An anomaly is an investigation signal, never proof of theft.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved daily profiles: {PROFILE_PATH.relative_to(WORKSPACE_ROOT)}")
    print(f"Saved benchmark model: {MODEL_PATH.relative_to(WORKSPACE_ROOT)}")
    print(f"Saved evaluation report: {REPORT_PATH.relative_to(WORKSPACE_ROOT)}")
    print(f"Anomaly rate: {report['results']['anomaly_rate']:.4f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        print(f"Anomaly benchmark training failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
