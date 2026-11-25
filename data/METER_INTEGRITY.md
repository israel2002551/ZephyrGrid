# Meter integrity investigation rules

This component creates evidence-backed **investigation** alerts from meter and
retrofit-module events. It does not decide theft, alter billing, disable a
meter, or perform electrical switching.

## Supported event input

Supply a CSV with these columns:

```text
event_id,device_id,asset_id,observed_at,event_type,quality_status
```

`observed_at` must be ISO-8601 with an offset. Only `quality_status=valid`
events are analysed. The initial rules in
`configs/meter_integrity_rules.json` detect:

- explicit tamper events;
- repeated device resets in a rolling 24-hour window;
- repeated authentication failures in a rolling 30-minute window;
- communication gaps between `reading_received` events of 60 minutes or more.

Run it with:

```text
python scripts/detect_meter_integrity.py --events path/to/meter_events.csv
```

By default, the system writes alerts and a run report to
`data/outputs/meter_integrity/`. Each alert includes the source event IDs and
the matching rule. Thresholds are starting points only and must be calibrated
for the supported meter models and actual communications interval.
