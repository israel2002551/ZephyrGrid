# Download manifest

Verified on 25 November 2026. Paths are relative to the workspace root.

| Dataset | File | Size | SHA-256 | Verification |
|---|---|---:|---|---|
| SGCC theft | `data/raw/ieee_sgcc_theft/data.z01` | 20,971,520 B | `C324DF53C88358A50AA23FD843B1E15AF06E7A20B72D901A98D957C304A52B67` | 7-Zip tested as part of the three-volume archive. |
| SGCC theft | `data/raw/ieee_sgcc_theft/data.z02` | 20,971,520 B | `34A30C8EEA0FDFA77D58E15CD01C5593EA354EAD4CC408A1B87364F6C46D4ED7` | 7-Zip tested as part of the three-volume archive. |
| SGCC theft | `data/raw/ieee_sgcc_theft/data.zip` | 10,527,833 B | `1E06AD5F5E13F56F2A72BEA304864D259E060D6AD95B3B030A4AD050D8DF82D4` | 7-Zip tested; contains `data.csv` (175,194,613 B). |
| UCI load diagrams | `data/raw/uci_load_diagrams/electricityloaddiagrams20112014.zip` | 261,335,609 B | `F6C4D0E0DF12ECDB9EA008DD6EEF3518ADB52C559D04A9BAC2E1B81DCFC8D4E1` | 7-Zip tested; contains `LD2011_2014.txt` (710,998,915 B). |
| TDD2022 | `data/raw/tdd2022/df.csv` | 64,403,651 B | `B10EA864A97FCEB823107AA86065BA4909FC1CB055E2EF40815D93670DCCDFA4` | Matches publisher SHA-256; 560,655 labelled rows. |
| TDD2022 | `data/raw/tdd2022/TDD2022_article.pdf` | 1,231,793 B | `1A1DDA3C45DDB0C4191C243226825905E80421AC693C97269FC12E820430A1FE` | Open-access article PDF. |
| Nigerian 33 kV faults | `data/raw/nigerian_33kv_faults/Fault Pattern Dataset with Timestamp.xlsx` | 673,228 B | `8FF9266D078EF1F9AEE0CA36D6941B310E8A0C9345FC74003061769D64D373EE` | Matches publisher SHA-256; 5,955 data rows and 30 columns. |
| PowerBench | `data/raw/powerbench_part1/Line Outage Dataset.zip` | 1,190,046,547 B | `6CAE5908DD75851D6E68757ED97C7B03702FCEED991B75AFFEA6C68B6F25BA2E` | Publisher MD5 `0c4cf4c9247e00f66749d9033b1b6737` matched; 7-Zip test passed. |
| PowerBench | `data/raw/powerbench_part1/State Estimation Dataset.zip` | 2,223,343,067 B | Not recorded in this manifest | Publisher MD5 `4d4fea4e94f337ef838b6afd0465b69a` matched; 7-Zip test passed. |
| PowerBench | `data/raw/powerbench_part1/README.md` | 2,287 B | `6E794BF84F6D3734F577B1ED10FD57F8F98012D747875A86CDB9C35E39A71F81` | Publisher MD5 `a6e4419a0430938bb2f1baef8bb83a03` matched. |

## Ready for model research

- Revenue-protection benchmarking: SGCC and TDD2022.
- Consumption baselines and anomaly detection: UCI load diagrams.
- Fault/reliability analytics with Nigerian context: 33 kV fault workbook.
- Network outage detection and state estimation: PowerBench.

Do not merge these datasets into one training table. They have different
countries, sampling intervals, labels, and assumptions. Each should power a
separate reproducible experiment until field-pilot data establishes a local
ZephyrGrid training set.
