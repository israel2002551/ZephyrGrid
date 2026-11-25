#!/usr/bin/env python3
"""Train a reproducible *benchmark-only* theft-classification baseline.

TDD2022 contains synthetic theft transformations. This script helps validate
the ZephyrGrid training and evaluation workflow, but its performance must not
be presented as expected performance on DisCo customers.

Usage:
    python scripts/train_tdd2022_benchmark.py
    python scripts/train_tdd2022_benchmark.py --max-train-rows 120000 --trees 100
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy
import pandas
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = WORKSPACE_ROOT / "data" / "raw" / "tdd2022" / "df.csv"
MODEL_PATH = WORKSPACE_ROOT / "models" / "tdd2022_random_forest_benchmark.joblib"
REPORT_PATH = WORKSPACE_ROOT / "data" / "reports" / "tdd2022_benchmark_report.json"

IDENTIFIER_COLUMNS = {"0"}
TARGET_COLUMN = "theft"
CATEGORY_COLUMNS = {"Class"}


def stratified_cap(frame: pandas.DataFrame, target: pandas.Series, maximum_rows: int, seed: int) -> tuple[pandas.DataFrame, pandas.Series]:
    """Cap training size while retaining every label's original proportion."""
    if len(frame) <= maximum_rows:
        return frame, target
    sampled_indices, _ = train_test_split(
        frame.index,
        train_size=maximum_rows,
        random_state=seed,
        stratify=target,
    )
    return frame.loc[sampled_indices], target.loc[sampled_indices]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-train-rows", type=int, default=120_000)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--trees", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261125)
    args = parser.parse_args()

    if args.max_train_rows < 1 or args.trees < 1 or not 0 < args.test_size < 1:
        raise ValueError("max-train-rows and trees must be positive; test-size must be between zero and one.")

    data = pandas.read_csv(SOURCE_PATH)
    if TARGET_COLUMN not in data or not CATEGORY_COLUMNS.issubset(data.columns):
        raise RuntimeError("TDD2022 source schema does not match the expected benchmark fields.")

    target = data.pop(TARGET_COLUMN).astype(str)
    identifier_columns = sorted(IDENTIFIER_COLUMNS.intersection(data.columns))
    features = data.drop(columns=identifier_columns)
    numeric_columns = sorted(column for column in features.columns if column not in CATEGORY_COLUMNS)
    categorical_columns = sorted(CATEGORY_COLUMNS.intersection(features.columns))

    for column in numeric_columns:
        features[column] = pandas.to_numeric(features[column], errors="coerce")
    invalid_numeric_values = int(features[numeric_columns].isna().sum().sum())
    if invalid_numeric_values:
        raise RuntimeError(f"TDD2022 contains {invalid_numeric_values} missing or non-numeric numeric feature values.")
    if features[categorical_columns].isna().any().any():
        raise RuntimeError("TDD2022 contains missing categorical feature values.")

    train_features, test_features, train_target, test_target = train_test_split(
        features,
        target,
        test_size=args.test_size,
        random_state=args.seed,
        stratify=target,
    )
    train_features, train_target = stratified_cap(train_features, train_target, args.max_train_rows, args.seed)

    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", numeric_columns),
            ("consumer_class", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_columns),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    classifier = RandomForestClassifier(
        n_estimators=args.trees,
        max_depth=20,
        min_samples_leaf=5,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=args.seed,
    )
    pipeline = Pipeline([("preprocess", preprocessor), ("classifier", classifier)])
    pipeline.fit(train_features, train_target)
    predictions = pipeline.predict(test_features)
    labels = sorted(target.unique())

    report = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "experiment_id": "tdd2022_random_forest_benchmark_v1",
        "purpose": "Pipeline benchmark only; not a field theft-detection model.",
        "source": str(SOURCE_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "model_artifact": str(MODEL_PATH.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "data": {
            "source_rows": int(len(data)),
            "training_rows": int(len(train_features)),
            "test_rows": int(len(test_features)),
            "dropped_identifier_columns": identifier_columns,
            "numeric_feature_columns": numeric_columns,
            "categorical_feature_columns": categorical_columns,
            "class_distribution_source": {label: int(count) for label, count in target.value_counts().sort_index().items()},
            "class_distribution_train": {label: int(count) for label, count in train_target.value_counts().sort_index().items()},
            "class_distribution_test": {label: int(count) for label, count in test_target.value_counts().sort_index().items()},
        },
        "model": {
            "algorithm": "RandomForestClassifier",
            "parameters": classifier.get_params(),
            "random_seed": args.seed,
        },
        "metrics": {
            "accuracy": accuracy_score(test_target, predictions),
            "balanced_accuracy": balanced_accuracy_score(test_target, predictions),
            "macro_f1": f1_score(test_target, predictions, average="macro"),
            "weighted_f1": f1_score(test_target, predictions, average="weighted"),
            "classification_report": classification_report(test_target, predictions, labels=labels, output_dict=True, zero_division=0),
            "confusion_matrix_labels": labels,
            "confusion_matrix": confusion_matrix(test_target, predictions, labels=labels).tolist(),
        },
        "limitations": [
            "Theft classes are synthetic transformations, not verified theft incidents.",
            "The random benchmark split may not represent future, unseen customers or a Nigerian DisCo distribution network.",
            "Do not use this model for enforcement, customer action, or production alerting.",
            "A local field-labelled dataset and topology-aware energy balance evidence are required for a production revenue-protection model.",
        ],
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": pipeline,
            "metadata": {
                "experiment_id": report["experiment_id"],
                "source": report["source"],
                "purpose": report["purpose"],
                "limitations": report["limitations"],
            },
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
        print(f"Benchmark training failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
