# Electrical-condition monitoring

This initial Network Operations and Asset Management component checks valid
voltage and current telemetry against **asset-specific** operating limits. It
produces human-review alerts; it never changes switching, protection, or
restoration state.

## Measurement CSV

Required columns:

```text
measurement_id,asset_id,asset_type,measurement_type,measurement_value,measurement_unit,phase,observed_at,quality_status
```

Supported measurements are `voltage_v` in volts (`v`) and `current_a` in
amperes (`a`). Only `quality_status=valid` records are evaluated.

## Asset-limit CSV

Required columns:

```text
asset_id,asset_type,nominal_voltage_v,min_voltage_pu,max_voltage_pu,max_current_a,source_reference
```

Populate limits from authorised engineering records. Do not use generic values
for assets with different voltage classes, configurations, or ratings.

```text
python scripts/monitor_electrical_conditions.py \
  --measurements path/to/measurements.csv \
  --asset-limits path/to/asset_limits.csv
```

Results are written to `data/outputs/electrical_conditions/` by default.
