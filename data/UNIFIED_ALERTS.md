# Unified investigation alerts

Each intelligence component emits a compatible CSV alert file. The alert bundle
command validates and combines those files into a single JSONL feed for the
future dashboard and case-management service.

```text
python scripts/compile_investigation_alerts.py \
  --alert-file data/outputs/reconciliation/reconciliation_alerts.csv \
  --alert-file data/outputs/meter_integrity/meter_integrity_alerts.csv \
  --alert-file data/outputs/electrical_conditions/electrical_condition_alerts.csv
```

The default bundle directory is `data/outputs/unified_alerts/`.

## Required review state

Every incoming alert must carry `alert_state=investigation_required`. The
bundle process rejects auto-action states and preserves an evidence JSON object
and recommended human review action. A future case-management system should
record the review outcome separately; it must not overwrite the source alert.
