# Large artefacts not stored in Git

The repository tracks all source code, configurations, contracts, reports, and
the downloaded-data manifest needed to reproduce the ZephyrGrid benchmarks.

The following are intentionally excluded from Git because GitHub's normal file
limits cannot safely host them:

- `data/raw/` — 3.53 GiB of public source archives and files;
- `data/processed/` — generated datasets that can be rebuilt from the scripts;
- `models/*.joblib` — generated model binaries; the TDD2022 artefact exceeds
  GitHub's 100 MiB normal-file limit;
- `data/outputs/` — future pilot alert and review outputs, which may contain
  operationally sensitive data.

Recreate processed data and benchmark models using the commands in the root
`README.md`. The exact external sources and checksums are documented in
`data/SOURCES.md` and `data/DOWNLOAD_MANIFEST.md`.
