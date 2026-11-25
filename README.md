# ZephyrGrid AI Intelligence Foundation

This workspace implements the first backend intelligence foundation described
in the ZephyrGrid design document. It is intentionally conservative: public
datasets establish reproducible research benchmarks, while field-pilot data
and authorised human review are required before a model or alert is used for
real operations.

## What exists now

| Capability | Implementation | Status |
|---|---|---|
| Data quality and source profiling | `scripts/profile_raw_datasets.py` | Complete for downloaded research sources |
| Canonical telemetry and topology contract | `data/CANONICAL_DATA_CONTRACT.md` | Draft for pilot integration |
| Consumption anomaly benchmark | UCI + Isolation Forest | Benchmark only |
| Theft-classification benchmark | TDD2022 + Random Forest | Benchmark only; labels are synthetic |
| Nigerian fault-restoration benchmark | Chronological Random Forest evaluation | Benchmark only |
| Energy reconciliation | `scripts/reconcile_energy_balance.py` | Ready for pilot measurement and topology CSVs |
| Meter integrity rules | `scripts/detect_meter_integrity.py` | Ready for pilot event CSVs |
| Electrical-condition monitoring | `scripts/monitor_electrical_conditions.py` | Ready for authorised asset-limit CSVs |
| Unified alert feed and field feedback | `compile_investigation_alerts.py`, `validate_field_outcomes.py` | Ready for shadow mode |

## Layout

- `data/raw/` — immutable downloaded source data.
- `data/processed/` — traceable source-specific derived data.
- `data/reports/` — profiles, evaluation metrics, and preprocessing reports.
- `data/outputs/` — runtime pilot outputs; not committed as source data.
- `models/` — serialized benchmark artefacts and the model registry.
- `configs/` — reviewable analytical thresholds; field calibration is required.
- `scripts/` — reproducible data, model, and alert workflows.
- `tests/` — behavioural safety and alert-evidence tests.

## Run checks

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/profile_raw_datasets.py
python scripts/build_model_registry.py
```

## Build benchmarks

```powershell
python scripts/prepare_nigerian_fault_events.py
python scripts/train_tdd2022_benchmark.py
python scripts/train_uci_consumption_anomaly_baseline.py
python scripts/train_fault_restoration_baseline.py
```

## Begin a field pilot

1. Map compatible meter, transformer, feeder, and DCU registers to the
   canonical contract.
2. Obtain versioned `feeder -> transformer -> meter` relationships and
   authorised transformer/feeder operating limits.
3. Ingest data into the documented CSV contracts for shadow mode.
4. Run reconciliation, meter integrity, and electrical-condition workflows.
5. Combine alerts, collect authorised investigation outcomes, and use only
   governed outcome labels for recalibration.

See `data/ENERGY_RECONCILIATION.md`, `data/METER_INTEGRITY.md`,
`data/ELECTRICAL_CONDITION_MONITORING.md`, and `data/FIELD_VALIDATION.md` for
the exact field-pilot inputs.

## Safety boundary

The system produces evidence for investigation. It does not establish theft,
authorise enforcement, control electrical switching, override protection, or
make restoration decisions.
