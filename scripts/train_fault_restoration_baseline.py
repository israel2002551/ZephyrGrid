#!/usr/bin/env python3
"""Train a chronological benchmark for 33 kV fault-restoration categories.

The public Nigerian source lacks feeder, asset, and timezone details. This is
therefore a decision-support research benchmark, not an outage-management or
restoration authority model.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import MultiLabelBinarizer


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = WORKSPACE_ROOT / "data" / "processed" / "nigerian_33kv_fault_events.csv"
MODEL_PATH = WORKSPACE_ROOT / "models" / "nigerian_fault_restoration_benchmark.joblib"
REPORT_PATH = WORKSPACE_ROOT / "data" / "reports" / "nigerian_fault_restoration_benchmark_report.json"
TARGET_COLUMN = "mttr_category"


def split_labels(value: str) -> list[str]:
    if pandas.isna(value):
        return []
    return [label for label in value.split(";") if label]


def feature_frame(data: pandas.DataFrame, cause_encoder: MultiLabelBinarizer | None = None) -> tuple[pandas.DataFrame, MultiLabelBinarizer]:
    timestamps = pandas.to_datetime(data["reported_at_local"], errors="coerce")
    base = pandas.DataFrame(
        {
            "month": timestamps.dt.month,
            "day_of_week": timestamps.dt.dayofweek,
            "hour": timestamps.dt.hour,
            "is_rainy": data["season"].eq("Rainy").astype(int),
            "fault_cause_count": pandas.to_numeric(data["fault_cause_count"], errors="coerce"),
        },
        index=data.index,
    )
    causes = data["fault_causes"].map(split_labels)
    encoder = cause_encoder or MultiLabelBinarizer()
    encoded = encoder.fit_transform(causes) if cause_encoder is None else encoder.transform(causes)
    cause_columns = pandas.DataFrame(encoded, columns=[f"cause__{label}" for label in encoder.classes_], index=data.index)
    return pandas.concat([base, cause_columns], axis=1), encoder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trees", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--train-fraction", type=float, default=0.80)
    args = parser.parse_args()
    if args.trees < 1 or not 0.5 <= args.train_fraction < 1:
        raise ValueError("trees must be positive and train-fraction must be at least 0.5 and less than one.")

    data = pandas.read_csv(SOURCE_PATH)
    timestamps = pandas.to_datetime(data["reported_at_local"], errors="coerce")
    labels = data[TARGET_COLUMN].map(split_labels)
    usable = data.loc[(timestamps.notna()) & (labels.map(len) == 1)].copy()
    usable["_reported_at"] = pandas.to_datetime(usable["reported_at_local"])
    usable["_target"] = usable[TARGET_COLUMN].map(lambda value: split_labels(value)[0])
    usable = usable.sort_values("_reported_at").reset_index(drop=True)
    cutoff = int(len(usable) * args.train_fraction)
    train_data = usable.iloc[:cutoff].copy()
    test_data = usable.iloc[cutoff:].copy()
    if train_data["_target"].nunique() < 2 or test_data.empty:
        raise RuntimeError("Chronological split does not contain sufficient target variation.")

    train_features, cause_encoder = feature_frame(train_data)
    test_features, _ = feature_frame(test_data, cause_encoder)
    if train_features.isna().any().any() or test_features.isna().any().any():
        raise RuntimeError("Feature construction produced missing values.")
    classifier = RandomForestClassifier(
        n_estimators=args.trees,
        max_depth=14,
        min_samples_leaf=5,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=args.seed,
        n_jobs=-1,
    )
    classifier.fit(train_features, train_data["_target"])
    predictions = classifier.predict(test_features)
    labels_order = sorted(usable["_target"].unique())
    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "experiment_id": "nigerian_fault_restoration_benchmark_v1",
        "purpose": "Chronological decision-support benchmark only; not outage control or restoration authority.",
        "source": str(SOURCE_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "model_artifact": str(MODEL_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "split": {
            "method": "chronological 80/20 holdout",
            "train_rows": int(len(train_data)),
            "test_rows": int(len(test_data)),
            "train_last_reported_at": train_data["_reported_at"].max().isoformat(),
            "test_first_reported_at": test_data["_reported_at"].min().isoformat(),
        },
        "features": {
            "columns": list(train_features.columns),
            "included": "initially reported fault causes, timestamp-derived calendar fields, and season; records without a recorded cause use an all-zero cause vector",
            "excluded": "restoration time/date, MTTR target, and load-loss category to avoid direct outcome leakage",
        },
        "metrics": {
            "accuracy": accuracy_score(test_data["_target"], predictions),
            "balanced_accuracy": balanced_accuracy_score(test_data["_target"], predictions),
            "macro_f1": f1_score(test_data["_target"], predictions, average="macro"),
            "weighted_f1": f1_score(test_data["_target"], predictions, average="weighted"),
            "classification_report": classification_report(test_data["_target"], predictions, labels=labels_order, output_dict=True, zero_division=0),
            "confusion_matrix_labels": labels_order,
            "confusion_matrix": confusion_matrix(test_data["_target"], predictions, labels=labels_order).tolist(),
        },
        "limitations": [
            "The public source has no feeder, asset, crew, weather, switching, or documented timezone data.",
            "Some records have no listed fault cause, so the benchmark represents them with no active cause indicator.",
            "The MTTR category is derived from historical restoration outcome and does not establish causality.",
            "Predictions may support investigation and resource planning only; authorised personnel and protection procedures govern restoration decisions.",
        ],
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "classifier": classifier,
            "cause_encoder": cause_encoder,
            "feature_columns": list(train_features.columns),
            "metadata": {"experiment_id": report["experiment_id"], "limitations": report["limitations"]},
        },
        MODEL_PATH,
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved benchmark model: {MODEL_PATH.relative_to(WORKSPACE_ROOT)}")
    print(f"Saved evaluation report: {REPORT_PATH.relative_to(WORKSPACE_ROOT)}")
    print(f"Balanced accuracy: {report['metrics']['balanced_accuracy']:.4f}")
    print(f"Macro F1: {report['metrics']['macro_f1']:.4f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, pandas.errors.ParserError) as error:
        print(f"Fault-restoration benchmark training failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
