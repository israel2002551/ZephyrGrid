# Energy reconciliation and alert evidence

The first revenue-protection workflow compares interval energy measured at a
transformer with the energy reported by the customer meters mapped to that
transformer at the same point in time.

`unexplained energy = upstream energy - downstream meter energy - expected technical loss`

An unexplained discrepancy creates an `investigation_required` alert only if
the configured coverage and quality thresholds are met. It does **not** prove
electricity theft; possible causes include topology errors, communication
gaps, meter configuration, technical loss, and physical bypass.

## Field-pilot input files

The command requires two CSV files:

### Measurements

Required columns:

```text
measurement_id,asset_id,asset_type,measurement_type,measurement_value,measurement_unit,observed_at,quality_status,interval_minutes
```

- Use interval energy, not cumulative meter-register values.
- `measurement_type` must be `energy_import_kwh`.
- `measurement_unit` must be `kwh`.
- `observed_at` must be an ISO-8601 timestamp with a UTC offset.
- Only `quality_status=valid` measurements contribute to a reconciled balance.

### Versioned topology

Required columns:

```text
parent_asset_id,parent_asset_type,child_asset_id,child_asset_type,relationship_type,valid_from,valid_to,source_reference
```

Provide `feeder -> transformer` and `transformer -> meter` relationships.
Use a blank `valid_to` for an open-ended active relationship. The pipeline
selects mappings that were valid during each reconciliation interval.

## Run

```text
python scripts/reconcile_energy_balance.py \
  --measurements path/to/measurements.csv \
  --topology path/to/topology.csv
```

It creates `balance_intervals.csv`, `reconciliation_alerts.csv`, and a
`reconciliation_run_report.json` in `data/outputs/reconciliation/` by default.
Thresholds live in `configs/energy_reconciliation_rules.json` and must be
calibrated against local technical-loss studies and investigation results.
