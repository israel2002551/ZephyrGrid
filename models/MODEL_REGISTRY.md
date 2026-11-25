# ZephyrGrid model registry

No registered model is production-eligible until it has local field validation, approved governance, model monitoring, and a deployment review.

| Model | Function | Status | Key metrics |
|---|---|---|---|
| tdd2022_random_forest_benchmark_v1 | Revenue Protection Intelligence | benchmark_only | accuracy=0.8225, balanced_accuracy=0.7034, macro_f1=0.6829, weighted_f1=0.8074 |
| uci_isolation_forest_benchmark_v1 | Revenue Protection Intelligence | benchmark_only | anomaly_rate=0.0103 |
| nigerian_fault_restoration_benchmark_v1 | Network Operations / Asset Management Intelligence | benchmark_only | accuracy=0.6616, balanced_accuracy=0.6626, macro_f1=0.6415, weighted_f1=0.6715 |

## Required before promotion

- Pilot data quality and topology validation.
- Shadow-mode evaluation against authorised investigation outcomes.
- Approved feature contract, threshold calibration, model monitoring, and access control.
- Human review remains mandatory for alerts and operational decisions.
