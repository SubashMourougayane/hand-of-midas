# Parity Audit — Multi-Regime Sample (Live ↔ Backtest)

_Generated: 2026-06-13T12:42:22.799540+00:00_

Sample years chosen to cover different market regimes. Signal extraction delegates to the proven `tests/harness/parity/extractor.py` functions (same code path as `test_22_parity`).

## Per-(system × regime) results

| System | Regime | Description | BT sigs | Live sigs | In both | BT only | Live only | Parity % | Direction agree | Avg entry drift |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gold Macro | 2008 | GFC / Lehman crisis | 86 | 93 | 86 | 0 | 7 | 92.5% | 100.0% | $0.0029 |
| Gold Macro | 2011 | EU debt crisis / Gold bull peak | 111 | 123 | 111 | 0 | 12 | 90.2% | 100.0% | $0.0025 |
| Gold Macro | 2013 | Gold bear / sideways | 75 | 80 | 75 | 0 | 5 | 93.8% | 100.0% | $0.0026 |
| Gold Macro | 2016 | Brexit + Trump election shock | 68 | 68 | 68 | 0 | 0 | 100.0% | 100.0% | $0.0025 |
| Gold Macro | 2020 | COVID crash + recovery | 115 | 119 | 115 | 0 | 4 | 96.6% | 100.0% | $0.0026 |
| Gold Macro | 2022 | Russia invasion / inflation | 97 | 98 | 97 | 0 | 1 | 99.0% | 100.0% | $0.0027 |
| Gold Macro | 2024 | Normal year (baseline) | 144 | 145 | 144 | 0 | 1 | 99.3% | 100.0% | $0.0031 |
| Gold Macro | 2026YTD | Current regime | 102 | 108 | 102 | 0 | 6 | 94.4% | 100.0% | $0.0025 |

## Per-system aggregate (across regimes)

| System | Regimes | Avg parity % | Avg dir agree % | Avg entry drift | Total BT sigs | Total Live sigs |
|---|---:|---:|---:|---:|---:|---:|
| Gold Macro | 8 | 95.7% | 100.0% | $0.0027 | 798 | 834 |

## Per-regime aggregate (across systems)

| Regime | Description | Systems | Avg parity % | Avg dir agree % | Total BT sigs | Total Live sigs |
|---|---|---:|---:|---:|---:|---:|
| 2008 | GFC / Lehman crisis | 1 | 92.5% | 100.0% | 86 | 93 |
| 2011 | EU debt crisis / Gold bull peak | 1 | 90.2% | 100.0% | 111 | 123 |
| 2013 | Gold bear / sideways | 1 | 93.8% | 100.0% | 75 | 80 |
| 2016 | Brexit + Trump election shock | 1 | 100.0% | 100.0% | 68 | 68 |
| 2020 | COVID crash + recovery | 1 | 96.6% | 100.0% | 115 | 119 |
| 2022 | Russia invasion / inflation | 1 | 99.0% | 100.0% | 97 | 98 |
| 2024 | Normal year (baseline) | 1 | 99.3% | 100.0% | 144 | 145 |
| 2026YTD | Current regime | 1 | 94.4% | 100.0% | 102 | 108 |
