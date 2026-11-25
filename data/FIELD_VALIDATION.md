# Field-validation outcome workflow

Shadow-mode alerts become valuable training evidence only after an authorised
reviewer records what an investigation found. This workflow links a review to
an immutable alert; it never changes the alert or assumes an anomaly is theft.

## Review-outcome CSV

Required columns:

```text
review_id,alert_id,alert_type,asset_id,reviewed_at,reviewer_id,outcome,evidence_reference,training_eligible,notes
```

Permitted `outcome` values:

- `confirmed_tamper`
- `confirmed_meter_fault`
- `confirmed_network_fault`
- `confirmed_energy_discrepancy`
- `data_quality_issue`
- `topology_issue`
- `explained_technical_loss`
- `no_issue`
- `inconclusive`

`training_eligible` must be `true` or `false`; it is an explicit governance
decision, not a conclusion made by the software. A confirmed tamper outcome
must not be silently interpreted as legal proof of electricity theft.

Run:

```text
python scripts/validate_field_outcomes.py \
  --alerts data/outputs/unified_alerts/investigation_alerts.jsonl \
  --outcomes path/to/review_outcomes.csv
```

The output is a validated, immutable label queue for later controlled model
training and recalibration.
