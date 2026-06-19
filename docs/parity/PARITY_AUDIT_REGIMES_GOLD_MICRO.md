# Parity Audit — Multi-Regime Sample (Live ↔ Backtest)

_Generated: 2026-06-13T13:13:34.771481+00:00_

Sample years chosen to cover different market regimes. Signal extraction delegates to the proven `tests/harness/parity/extractor.py` functions (same code path as `test_22_parity`).

## Per-(system × regime) results

| System | Regime | Description | BT sigs | Live sigs | In both | BT only | Live only | Parity % | Direction agree | Avg entry drift |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gold Micro | 2008 | GFC / Lehman crisis | 230 | 223 | 177 | 17 | 46 | 79.4% | 100.0% | $0.0029 |
| Gold Micro | 2011 | EU debt crisis / Gold bull peak | 295 | 272 | 211 | 23 | 61 | 77.6% | 100.0% | $0.0027 |
| Gold Micro | 2013 | Gold bear / sideways | 237 | 229 | 182 | 19 | 47 | 79.5% | 100.0% | $0.0024 |
| Gold Micro | 2016 | Brexit + Trump election shock | 147 | 135 | 111 | 9 | 24 | 82.2% | 100.0% | $0.0025 |
| Gold Micro | 2020 | COVID crash + recovery | 368 | 356 | 261 | 34 | 95 | 73.3% | 100.0% | $0.0026 |
| Gold Micro | 2022 | Russia invasion / inflation | 268 | 246 | 211 | 14 | 35 | 85.8% | 100.0% | $0.0025 |
| Gold Micro | 2024 | Normal year (baseline) | 391 | 360 | 299 | 34 | 61 | 83.1% | 100.0% | $0.0031 |
| Gold Micro | 2026YTD | Current regime | 259 | 259 | 172 | 44 | 87 | 66.4% | 100.0% | $0.0025 |

## Per-system aggregate (across regimes)

| System | Regimes | Avg parity % | Avg dir agree % | Avg entry drift | Total BT sigs | Total Live sigs |
|---|---:|---:|---:|---:|---:|---:|
| Gold Micro | 8 | 78.4% | 100.0% | $0.0026 | 2195 | 2080 |

## Per-regime aggregate (across systems)

| Regime | Description | Systems | Avg parity % | Avg dir agree % | Total BT sigs | Total Live sigs |
|---|---|---:|---:|---:|---:|---:|
| 2008 | GFC / Lehman crisis | 1 | 79.4% | 100.0% | 230 | 223 |
| 2011 | EU debt crisis / Gold bull peak | 1 | 77.6% | 100.0% | 295 | 272 |
| 2013 | Gold bear / sideways | 1 | 79.5% | 100.0% | 237 | 229 |
| 2016 | Brexit + Trump election shock | 1 | 82.2% | 100.0% | 147 | 135 |
| 2020 | COVID crash + recovery | 1 | 73.3% | 100.0% | 368 | 356 |
| 2022 | Russia invasion / inflation | 1 | 85.8% | 100.0% | 268 | 246 |
| 2024 | Normal year (baseline) | 1 | 83.1% | 100.0% | 391 | 360 |
| 2026YTD | Current regime | 1 | 66.4% | 100.0% | 259 | 259 |
