# Parity Audit — Multi-Regime Sample (Live ↔ Backtest)

_Generated: 2026-06-13T13:04:17.618435+00:00_

Sample years chosen to cover different market regimes. Signal extraction delegates to the proven `tests/harness/parity/extractor.py` functions (same code path as `test_22_parity`).

## Per-(system × regime) results

| System | Regime | Description | BT sigs | Live sigs | In both | BT only | Live only | Parity % | Direction agree | Avg entry drift |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Oil Micro | 2008 | GFC / Lehman crisis | 448 | 389 | 331 | 38 | 58 | 85.1% | 100.0% | $0.0012 |
| Oil Micro | 2011 | EU debt crisis / Gold bull peak | 465 | 431 | 353 | 22 | 78 | 81.9% | 100.0% | $0.0013 |
| Oil Micro | 2013 | Gold bear / sideways | 297 | 270 | 240 | 15 | 30 | 88.9% | 100.0% | $0.0013 |
| Oil Micro | 2016 | Brexit + Trump election shock | 239 | 216 | 194 | 16 | 22 | 89.8% | 100.0% | $0.0013 |
| Oil Micro | 2020 | COVID crash + recovery | 323 | 279 | 249 | 25 | 30 | 89.2% | 100.0% | $0.0013 |
| Oil Micro | 2022 | Russia invasion / inflation | 593 | 579 | 436 | 50 | 143 | 75.3% | 100.0% | $0.0012 |
| Oil Micro | 2024 | Normal year (baseline) | 347 | 320 | 271 | 21 | 49 | 84.7% | 100.0% | $0.0012 |
| Oil Micro | 2026YTD | Current regime | 189 | 189 | 145 | 16 | 44 | 76.7% | 100.0% | $0.0013 |

## Per-system aggregate (across regimes)

| System | Regimes | Avg parity % | Avg dir agree % | Avg entry drift | Total BT sigs | Total Live sigs |
|---|---:|---:|---:|---:|---:|---:|
| Oil Micro | 8 | 84.0% | 100.0% | $0.0013 | 2901 | 2673 |

## Per-regime aggregate (across systems)

| Regime | Description | Systems | Avg parity % | Avg dir agree % | Total BT sigs | Total Live sigs |
|---|---|---:|---:|---:|---:|---:|
| 2008 | GFC / Lehman crisis | 1 | 85.1% | 100.0% | 448 | 389 |
| 2011 | EU debt crisis / Gold bull peak | 1 | 81.9% | 100.0% | 465 | 431 |
| 2013 | Gold bear / sideways | 1 | 88.9% | 100.0% | 297 | 270 |
| 2016 | Brexit + Trump election shock | 1 | 89.8% | 100.0% | 239 | 216 |
| 2020 | COVID crash + recovery | 1 | 89.2% | 100.0% | 323 | 279 |
| 2022 | Russia invasion / inflation | 1 | 75.3% | 100.0% | 593 | 579 |
| 2024 | Normal year (baseline) | 1 | 84.7% | 100.0% | 347 | 320 |
| 2026YTD | Current regime | 1 | 76.7% | 100.0% | 189 | 189 |
