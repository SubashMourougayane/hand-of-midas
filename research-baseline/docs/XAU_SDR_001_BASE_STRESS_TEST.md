# Sleeve 1 Base Stress Test

Base candidate: `SLEEVE1_XAU_SD_RECLAIM_001` - XAUUSD clean top-3 Supply/Demand reclaim only. No cross-asset add-on, no top-10 stretch.

## Core Numbers

- `full_2019_2026`: 1032 trades, `256.11R`, `32.01R/year`, WR `63.86%`, PF `1.68`, max DD `-12.69R`, positive years `8/8`.
- `oos_2022_2026`: 818 trades, `216.97R`, `43.39R/year`, WR `64.67%`, PF `1.75`, max DD `-12.69R`, positive years `5/5`.
- `early_2019_2022`: 304 trades, `57.87R`, `14.47R/year`, WR `61.18%`, PF `1.50`, max DD `-6.71R`, positive years `4/4`.
- `late_2023_2026`: 728 trades, `198.24R`, `49.56R/year`, WR `64.97%`, PF `1.77`, max DD `-12.69R`, positive years `4/4`.

## Cost Stress

| Extra Cost / Trade | R/year | WR | PF | Positive Years |
|---:|---:|---:|---:|---:|
| 0.000R | 32.01 | 63.86% | 1.68 | 8/8 |
| 0.005R | 31.37 | 63.86% | 1.67 | 8/8 |
| 0.010R | 30.72 | 63.86% | 1.65 | 8/8 |
| 0.020R | 29.43 | 63.86% | 1.62 | 7/8 |
| 0.030R | 28.14 | 63.86% | 1.58 | 7/8 |
| 0.050R | 25.56 | 63.86% | 1.52 | 7/8 |
| 0.075R | 22.34 | 63.86% | 1.44 | 7/8 |
| 0.100R | 19.11 | 63.76% | 1.37 | 7/8 |
| 0.150R | 12.66 | 63.57% | 1.24 | 5/8 |
| 0.200R | 6.21 | 63.47% | 1.11 | 5/8 |

## Decay / Regime

- Early 2019-2022: `14.47R/year`.
- Late 2023-2026: `49.56R/year`.
- Worst 12-month rolling window: `0.87R`.
- Best 12-month rolling window: `116.92R`.

## Monte Carlo / Bootstrap

- Permutation median DD: `-9.21R`; 5% DD `-13.50R`; 1% DD `-16.37R`.
- Bootstrap 5% net: `206.12R`; bootstrap 5% avg/year `25.76R/year`; probability net <= 0: `0.00%`.

## Fragility

| Remove Top Winners | Net R | R/year | PF |
|---:|---:|---:|---:|
| 1 | 255.11 | 31.89 | 1.68 |
| 3 | 253.12 | 31.64 | 1.68 |
| 5 | 251.13 | 31.39 | 1.67 |
| 10 | 246.16 | 30.77 | 1.66 |
| 20 | 236.24 | 29.53 | 1.63 |
| 30 | 226.33 | 28.29 | 1.60 |
| 50 | 206.55 | 25.82 | 1.55 |

## Trade Clustering

- Max consecutive wins: `18`.
- Max consecutive losses: `5`.
- Worst 5-trade window: `-5.18R`; best: `4.96R`.
- Worst 10-trade window: `-5.29R`; best: `9.86R`.
- Worst 20-trade window: `-8.34R`; best: `17.48R`.
- Worst 50-trade window: `-9.47R`; best: `27.36R`.
- Worst 100-trade window: `2.83R`; best: `46.96R`.

## Verdict

Sleeve 1 survives the first stress pack. The main weak point is 2023, where it remains positive but barely (`1.04R`). That means the edge does not vanish, but it is regime-sensitive and should be monitored. It is suitable as the base candidate, with a final causality/source-code certification still recommended before live use.

## Files

- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/base_sleeve1_trades.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/base_sleeve1_summary.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/stress_cost_haircut.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/stress_rolling_windows.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/stress_monte_carlo_summary.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/stress_bootstrap_summary.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/stress_remove_top_winners.csv`
- `/Users/subash/Documents/QUANT/SupplyDemand/base/SLEEVE1_XAU_SD_RECLAIM_001/stress_trade_clustering.csv`