# SDR-002 5k PnL and Lot Sizing Report

Rule: `ema8_aligned + orb_reversal`

Data: `/Users/subash/Documents/QUANT/SupplyDemand/research/l99_m15_filter_edge_sweep/m15_2c_1atr_feature_matrix.csv`

Assumptions:
- Starting capital reset: `$5,000`
- Risk variants: `1%, 2%, 3%, 4%, 5%` of current reset-period equity per trade
- Monthly reset model: equity starts at `$5,000` each month, compounds inside the month, then refreshes next month
- Yearly reset model included for comparison
- XAU lot estimate: `lots = risk_usd / (risk_units * 100)`
- Trade R uses `net_1r_after_cost`, so the existing $0.30 cost model is already included

## R Metrics

| trades | net_r | avg_r | wr | pf | avg_win_r | avg_loss_r | max_dd_r | r_per_year | mar | max_loss_streak | positive_years | years | positive_months | months |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2508 | 850.9198 | 0.3393 | 0.7173 | 2.1000 | 0.9030 | -1.0911 | -12.5966 | 126.6497 | 10.0543 | 7 | 8 | 8 | 80 | 82 |

## 5k Summary by Risk

| risk_pct | risk_usd_start | fixed_r_total_pnl_usd | fixed_r_max_dd_usd | monthly_reset_total_pnl_usd | monthly_reset_positive_months | monthly_reset_months | monthly_reset_worst_month_pnl_usd | monthly_reset_worst_dd_usd | yearly_reset_total_pnl_usd | yearly_reset_positive_years | yearly_reset_years | avg_lot | median_lot | p95_lot | max_lot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1% | 50.00 | 42545.99 | -629.83 | 44843.29 | 80 | 82 | -296.19 | -478.61 | 82367.07 | 8 | 8 | 0.17 | 0.15 | 0.39 | 1.03 |
| 2% | 100.00 | 85091.98 | -1259.66 | 94590.74 | 80 | 82 | -589.51 | -921.62 | 365886.43 | 8 | 8 | 0.36 | 0.32 | 0.82 | 2.13 |
| 3% | 150.00 | 127637.97 | -1889.49 | 149737.23 | 80 | 82 | -878.39 | -1330.56 | 1376268.16 | 8 | 8 | 0.57 | 0.50 | 1.30 | 3.29 |
| 4% | 200.00 | 170183.96 | -2519.32 | 210820.38 | 80 | 82 | -1161.36 | -1706.99 | 5059704.06 | 8 | 8 | 0.81 | 0.70 | 1.84 | 4.52 |
| 5% | 250.00 | 212729.95 | -3149.15 | 278422.92 | 80 | 82 | -1437.11 | -2326.31 | 18653627.05 | 8 | 8 | 1.06 | 0.91 | 2.45 | 5.81 |

## Yearly R Metrics

| year | trades | net_r | wr | pf |
| --- | --- | --- | --- | --- |
| 2019 | 96 | 23.9323 | 0.7188 | 1.7444 |
| 2020 | 359 | 94.1035 | 0.6769 | 1.7456 |
| 2021 | 373 | 100.7691 | 0.6917 | 1.7990 |
| 2022 | 421 | 118.9597 | 0.6983 | 1.8448 |
| 2023 | 355 | 128.5185 | 0.7437 | 2.2477 |
| 2024 | 391 | 139.9933 | 0.7212 | 2.2073 |
| 2025 | 351 | 161.8680 | 0.7550 | 2.7865 |
| 2026 | 162 | 82.7753 | 0.7654 | 3.1388 |

## Yearly Reset PnL by Risk

| year | 1% | 2% | 3% | 4% | 5% |
| --- | --- | --- | --- | --- | --- |
| 2019 | 1325.07 | 2933.62 | 4866.84 | 7166.69 | 9874.42 |
| 2020 | 7598.56 | 25691.23 | 67287.87 | 159619.20 | 357457.20 |
| 2021 | 8464.08 | 30037.53 | 83113.40 | 209138.52 | 497892.85 |
| 2022 | 11113.53 | 44956.68 | 144001.09 | 422542.15 | 1175191.29 |
| 2023 | 12788.61 | 56289.06 | 199512.90 | 655959.39 | 2063979.56 |
| 2024 | 14913.97 | 71523.32 | 278745.33 | 1010323.71 | 3501340.06 |
| 2025 | 19812.39 | 114087.89 | 547925.05 | 2479022.41 | 10794856.67 |
| 2026 | 6350.87 | 20367.11 | 50815.67 | 115931.98 | 253035.00 |

## Worst 10 Monthly Reset Months at 1% Risk

| month | trades | pnl_usd | return_pct | max_dd_usd |
| --- | --- | --- | --- | --- |
| 2021-04 | 33 | -296.19 | -5.92 | -478.61 |
| 2020-03 | 22 | -251.77 | -5.04 | -353.58 |
| 2019-11 | 21 | 67.02 | 1.34 | -227.29 |
| 2023-06 | 26 | 100.43 | 2.01 | -228.17 |
| 2020-01 | 24 | 116.49 | 2.33 | -139.90 |
| 2019-09 | 5 | 124.69 | 2.49 | -55.76 |
| 2024-03 | 28 | 130.05 | 2.60 | -170.63 |
| 2021-03 | 32 | 135.50 | 2.71 | -221.13 |
| 2020-12 | 27 | 204.22 | 4.08 | -188.89 |
| 2021-08 | 26 | 238.36 | 4.77 | -212.32 |

## Lot Distribution

| risk_pct | avg_lot | median_lot | p95_lot | max_lot | min_lot |
| --- | --- | --- | --- | --- | --- |
| 1% | 0.1720 | 0.1515 | 0.3868 | 1.0346 | 0.0033 |
| 2% | 0.3623 | 0.3203 | 0.8201 | 2.1327 | 0.0073 |
| 3% | 0.5728 | 0.5027 | 1.2957 | 3.2947 | 0.0120 |
| 4% | 0.8055 | 0.6981 | 1.8445 | 4.5212 | 0.0177 |
| 5% | 1.0628 | 0.9065 | 2.4518 | 5.8124 | 0.0244 |

## Files

- `/Users/subash/SUBASH/GoldDigger/research-baseline/results/sdr002_5k_pnl_20260629/sdr002_5k_summary.csv`
- `/Users/subash/SUBASH/GoldDigger/research-baseline/results/sdr002_5k_pnl_20260629/sdr002_monthly_reset_by_month.csv`
- `/Users/subash/SUBASH/GoldDigger/research-baseline/results/sdr002_5k_pnl_20260629/sdr002_yearly_reset_by_year.csv`
- `/Users/subash/SUBASH/GoldDigger/research-baseline/results/sdr002_5k_pnl_20260629/sdr002_monthly_reset_trade_lots.csv`
- `/Users/subash/SUBASH/GoldDigger/research-baseline/results/sdr002_5k_pnl_20260629/sdr002_yearly_r_metrics.csv`
- `/Users/subash/SUBASH/GoldDigger/research-baseline/results/sdr002_5k_pnl_20260629/sdr002_trades_r.csv`