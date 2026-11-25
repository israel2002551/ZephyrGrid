# ZephyrGrid canonical data contract — draft 1

This is the shared shape that field-pilot ingestion must produce. Public
datasets are research inputs only; they are **not** transformed into this
contract until their source-specific preprocessing is explicitly defined.

## Telemetry measurement

Every physical or derived measurement must include:

| Field | Type | Requirement |
|---|---|---|
| `event_id` | UUID/string | Required and immutable. |
| `device_id` | string | Required where a device produced the measurement. |
| `asset_id` | string | Required; resolves to a versioned topology asset. |
| `asset_type` | enum | `meter`, `transformer`, `feeder`, `dcu`, or `other`. |
| `measurement_type` | enum/string | E.g. `energy_import_kwh`, `voltage_v`, `active_power_kw`. |
| `measurement_value` | number | Required for a measurement. |
| `measurement_unit` | string | Required, normalised to the approved unit catalogue. |
| `phase` | enum/null | `a`, `b`, `c`, `total`, or null. |
| `observed_at` | ISO-8601 UTC timestamp | Required. Device observation time, not receipt time. |
| `received_at` | ISO-8601 UTC timestamp | Required. Backend receipt time. |
| `data_source` | string | Required. Manufacturer/system and connector identity. |
| `quality_status` | enum | `valid`, `suspect`, `invalid`, or `incomplete`. |
| `quality_reasons` | array[string] | Required when status is not `valid`. |

## Operational event

Events such as tamper alerts, authentication failures, resets, breaker trips,
and outages use the same identity, asset, time, source, and quality fields,
plus `event_type`, `event_severity`, and source payload reference.

## Topology relationship

`relationship_id`, `parent_asset_id`, `child_asset_id`, `relationship_type`,
`valid_from`, `valid_to`, and `source_reference` are required. Relationships
must never be overwritten: switching and network reconfiguration create a new
versioned record.

## Validation gates before feature generation

1. Reject duplicate event identifiers and retain a rejection reason.
2. Flag measurements outside physically credible ranges per asset type.
3. Flag delayed, missing, out-of-order, and unauthenticated data.
4. Require units before any conversion or aggregation.
5. Exclude `invalid` records from training; preserve them for data-quality and
   device-health analytics.

This follows the ZephyrGrid design document's shared measurement fields and
keeps training data, alerts, and audit trails traceable to their source.
