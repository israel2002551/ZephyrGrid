# ZephyrGrid external dataset inventory

Downloaded raw data belongs in `data/raw/`.  Keep it immutable: preprocessing
and train/test splits should be written elsewhere so every experiment can be
traced back to its original source.

This inventory was checked on 25 November 2026.  The UCI, SGCC, TDD2022, and
Nigerian datasets below have passed integrity checks.  PowerBench's small
README is verified, while its 3.4 GB archives are still being retrieved from
Zenodo; do not use either archive until its published MD5 check passes.

| ID | Source and purpose | Downloaded material | Licence / access | Important limitations |
|---|---|---|---|---|
| `ieee_sgcc_theft` | IEEE PES catalogue entry for the SGCC Electricity Theft Detection data.  Real daily electricity-consumption records for 42,372 customers across 1,035 days (2014-01-01 to 2016-10-31). | The upstream three-part archive: `data.zip`, `data.z01`, `data.z02`, plus its README. | Public; the catalogue states no licence.  Cite Zheng et al. (2018) and confirm reuse rights before distribution or commercial use. | It is external, historical Chinese consumption data—not Nigerian field data.  Inspect the archive before treating any field as a theft label. |
| `uci_load_diagrams` | UCI ElectricityLoadDiagrams20112014.  Useful for normal-load baselines and time-series/anomaly experiments. | `electricityloaddiagrams20112014.zip` containing `LD2011_2014.txt`. | CC BY 4.0. | 370 clients; 15-minute kW readings.  Divide by 4 for kWh.  Portuguese timestamps and daylight-saving-hour conventions require careful parsing. |
| `tdd2022` | TDD2022 from Zidi et al., the dataset associated with the supplied Springer article.  A supervised benchmark with normal patterns and six generated theft types. | `df.csv` and the open-access article PDF. | CC BY 4.0. | Fraud classes are synthetically generated from OEDI-origin consumption profiles.  It is a benchmarking dataset, not proof of real-world theft behaviour. |
| `powerbench_part1` | PowerBench Part 1: line-outage detection and state estimation for IEEE 34-bus, 123-bus, and 8500-node feeders. | `README.md` and `Line Outage Dataset.zip` are verified; `State Estimation Dataset.zip` is downloading. | CC BY 4.0, as specified in the publisher README. | 3.4 GB of synthetic OpenDSS scenarios.  Valuable for network/fault research, but not a substitute for DisCo measurements. |
| `nigerian_33kv_faults` | Fault Pattern Dataset for a 33 kV Power Distribution Network in Lagos State: 23 feeders, Apr 2017–Dec 2024, 5,955 transactions and 7,058 fault occurrences. | `Fault Pattern Dataset with Timestamp.xlsx`. | CC BY 4.0. | The closest available local context, but it is a fault-history dataset—not high-frequency meter or SCADA telemetry. |

## Completion status (25 November 2026)

All five requested source datasets and the TDD2022 article are now downloaded
under `data/raw/`. Both PowerBench archives have completed, match the
publisher-provided MD5 values, and pass full 7-Zip archive tests. See
`data/DOWNLOAD_MANIFEST.md` for the final file inventory and verification
record; it supersedes any earlier in-progress wording in this document.

## Official source links

- IEEE catalogue: <https://ieee-pes-data-sharing.org/datasets/detail/663b8e0e-3ace-48f8-b983-4cb59b39fa6f>
- UCI record and documentation: <https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014>
- TDD2022 article: <https://link.springer.com/article/10.1016/j.jksuci.2022.05.007>
- TDD2022 data record: <https://data.mendeley.com/datasets/c3c7329tjj/1>
- PowerBench record: <https://zenodo.org/records/15400564>
- Nigerian 33 kV record: <https://data.mendeley.com/datasets/grkv36gg2t/3>

## Integrity checks

The download log will record hashes for files where the publisher supplies
them.  Before use, verify the SHA-256/MD5 values listed there and retain the
source record version used in each experiment.

Publisher checksums for PowerBench are `0c4cf4c9247e00f66749d9033b1b6737`
for the line-outage archive, `4d4fea4e94f337ef838b6afd0465b69a` for the
state-estimation archive, and `a6e4419a0430938bb2f1baef8bb83a03` for
`README.md` (verified locally).

