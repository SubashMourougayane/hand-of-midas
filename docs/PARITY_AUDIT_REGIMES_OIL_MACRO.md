# Parity Audit — Multi-Regime Sample (Live ↔ Backtest)

_Generated: 2026-06-13T12:39:19.577253+00:00_

Sample years chosen to cover different market regimes. Signal extraction delegates to the proven `tests/harness/parity/extractor.py` functions (same code path as `test_22_parity`).

## Per-(system × regime) results

| System | Regime | Description | BT sigs | Live sigs | In both | BT only | Live only | Parity % | Direction agree | Avg entry drift |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Oil Macro | 2008 | GFC / Lehman crisis | 156 | 179 | 143 | 11 | 32 | 81.7% | 100.0% | $0.0000 |
| Oil Macro | 2011 | EU debt crisis / Gold bull peak | 145 | 150 | 135 | 8 | 11 | 92.5% | 100.0% | $0.0000 |
| Oil Macro | 2013 | Gold bear / sideways | 54 | 58 | 51 | 3 | 7 | 87.9% | 100.0% | $0.0000 |
| Oil Macro | 2016 | Brexit + Trump election shock | 50 | 48 | 46 | 3 | 1 | 93.9% | 100.0% | $0.0000 |
| Oil Macro | 2020 | COVID crash + recovery | 68 | 68 | 64 | 4 | 4 | 94.1% | 100.0% | $0.0000 |
| Oil Macro | 2022 | Russia invasion / inflation | 229 | 242 | 219 | 10 | 22 | 90.9% | 100.0% | $0.0000 |
| Oil Macro | 2024 | Normal year (baseline) | 95 | 95 | 91 | 4 | 4 | 95.8% | 100.0% | $0.0000 |
| Oil Macro | 2026YTD | Current regime | 66 | 71 | 63 | 2 | 7 | 90.0% | 100.0% | $0.0000 |

## Per-system aggregate (across regimes)

| System | Regimes | Avg parity % | Avg dir agree % | Avg entry drift | Total BT sigs | Total Live sigs |
|---|---:|---:|---:|---:|---:|---:|
| Oil Macro | 8 | 90.8% | 100.0% | $0.0000 | 863 | 911 |

## Per-regime aggregate (across systems)

| Regime | Description | Systems | Avg parity % | Avg dir agree % | Total BT sigs | Total Live sigs |
|---|---|---:|---:|---:|---:|---:|
| 2008 | GFC / Lehman crisis | 1 | 81.7% | 100.0% | 156 | 179 |
| 2011 | EU debt crisis / Gold bull peak | 1 | 92.5% | 100.0% | 145 | 150 |
| 2013 | Gold bear / sideways | 1 | 87.9% | 100.0% | 54 | 58 |
| 2016 | Brexit + Trump election shock | 1 | 93.9% | 100.0% | 50 | 48 |
| 2020 | COVID crash + recovery | 1 | 94.1% | 100.0% | 68 | 68 |
| 2022 | Russia invasion / inflation | 1 | 90.9% | 100.0% | 229 | 242 |
| 2024 | Normal year (baseline) | 1 | 95.8% | 100.0% | 95 | 95 |
| 2026YTD | Current regime | 1 | 90.0% | 100.0% | 66 | 71 |
