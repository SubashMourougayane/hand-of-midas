# Parity Audit — Multi-Regime Sample (Live ↔ Backtest)

_Generated: 2026-06-13T11:51:10.550118+00:00_

Sample years chosen to cover different market regimes. Signal extraction delegates to the proven `tests/harness/parity/extractor.py` functions (same code path as `test_22_parity`).

## Per-(system × regime) results

| System | Regime | Description | BT sigs | Live sigs | In both | BT only | Live only | Parity % | Direction agree | Avg entry drift |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gold Micro | 2024 | Normal year (baseline) | 391 | 360 | 299 | 34 | 61 | 83.1% | 100.0% | $0.0031 |

## Per-system aggregate (across regimes)

| System | Regimes | Avg parity % | Avg dir agree % | Avg entry drift | Total BT sigs | Total Live sigs |
|---|---:|---:|---:|---:|---:|---:|
| Gold Micro | 1 | 83.1% | 100.0% | $0.0031 | 391 | 360 |

## Per-regime aggregate (across systems)

| Regime | Description | Systems | Avg parity % | Avg dir agree % | Total BT sigs | Total Live sigs |
|---|---|---:|---:|---:|---:|---:|
| 2024 | Normal year (baseline) | 1 | 83.1% | 100.0% | 391 | 360 |
