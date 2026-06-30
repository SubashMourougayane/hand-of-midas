# Causal ORB Candidate Rerun

Generated: 2026-06-29

No code was changed. This is an analysis-only rerun where `orb_reversal`, `orb_continuation`, and `orb_inside` are forced to `False` before same-day NY ORB is actually known.

Primary guard used: `entry time >= 09:30 America/New_York`.

## Candidate Rerun

| Rule | Version | Trades | Net R | R/yr | WR | PF | DD | MAR | Years |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ema8_aligned + orb_reversal` | `original` | 2,508 | +850.92 | +126.60 | 71.7% | 2.10 | -12.60 | 10.05 | 8/8 |
| `ema8_aligned + orb_reversal` | `causal_0930` | 1,085 | +56.52 | +8.41 | 57.1% | 1.11 | -40.96 | 0.21 | 6/8 |
| `ema8_aligned + orb_reversal` | `causal_1000` | 1,084 | +57.63 | +8.57 | 57.2% | 1.11 | -40.96 | 0.21 | 6/8 |
| `ema8_aligned + orb_reversal + avoid_after_hours` | `original` | 1,802 | +842.95 | +125.57 | 77.7% | 2.96 | -7.71 | 16.29 | 8/8 |
| `ema8_aligned + orb_reversal + avoid_after_hours` | `causal_0930` | 379 | +48.55 | +7.23 | 58.3% | 1.30 | -13.83 | 0.52 | 6/8 |
| `ema8_aligned + orb_reversal + avoid_after_hours` | `causal_1000` | 378 | +49.66 | +7.40 | 58.5% | 1.31 | -13.83 | 0.53 | 6/8 |
| `ema8_aligned + intraday_stack_24h + orb_reversal` | `original` | 2,017 | +719.17 | +107.00 | 72.6% | 2.19 | -8.34 | 12.83 | 8/8 |
| `ema8_aligned + intraday_stack_24h + orb_reversal` | `causal_0930` | 829 | +52.03 | +7.74 | 57.7% | 1.14 | -31.30 | 0.25 | 6/8 |
| `ema8_aligned + intraday_stack_24h + orb_reversal` | `causal_1000` | 828 | +53.14 | +7.91 | 57.7% | 1.14 | -31.30 | 0.25 | 6/8 |
| `ema8_aligned + intraday_stack_7d + orb_reversal` | `original` | 2,309 | +809.30 | +120.41 | 72.3% | 2.16 | -9.57 | 12.58 | 8/8 |
| `ema8_aligned + intraday_stack_7d + orb_reversal` | `causal_0930` | 980 | +66.24 | +9.85 | 58.0% | 1.15 | -34.74 | 0.28 | 6/8 |
| `ema8_aligned + intraday_stack_7d + orb_reversal` | `causal_1000` | 979 | +67.35 | +10.02 | 58.0% | 1.15 | -34.74 | 0.29 | 6/8 |
| `ema8_aligned + stack_7d30d_score3 + orb_reversal` | `original` | 2,219 | +752.43 | +111.95 | 71.8% | 2.10 | -10.66 | 10.51 | 8/8 |
| `ema8_aligned + stack_7d30d_score3 + orb_reversal` | `causal_0930` | 944 | +52.54 | +7.82 | 57.4% | 1.12 | -36.91 | 0.21 | 6/8 |
| `ema8_aligned + stack_7d30d_score3 + orb_reversal` | `causal_1000` | 943 | +53.65 | +7.98 | 57.5% | 1.12 | -36.91 | 0.22 | 6/8 |
| `ema8_aligned + orb_reversal + asia_post_session` | `original` | 1,362 | +760.44 | +113.32 | 82.9% | 3.93 | -5.20 | 21.79 | 8/8 |
| `ema8_aligned + orb_reversal + asia_post_session` | `causal_0930` | 0 | +0.00 | +0.00 | 0.0% | 0.00 | 0.00 | inf | 0/0 |
| `ema8_aligned + orb_reversal + asia_post_session` | `causal_1000` | 0 | +0.00 | +0.00 | 0.0% | 0.00 | 0.00 | inf | 0/0 |

## Best Causal Rules Found

Strict rules with `n>=500`, `PF>=1.5`, and all years positive: **0**.

| Rule | Trades | Net R | R/yr | WR | PF | DD | MAR | Years |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ema8_aligned + intraday_stack_24h + ny_main_or_overlap` | 2,936 | +382.56 | +54.35 | 59.7% | 1.31 | -18.01 | 3.02 | 8/8 |
| `ema8_aligned + trend_aligned + ny_main_or_overlap` | 1,914 | +293.53 | +41.70 | 60.8% | 1.37 | -13.83 | 3.02 | 8/8 |
| `ema8_aligned + ny_main_or_overlap + opposite_fvg_20` | 2,814 | +382.85 | +54.39 | 59.9% | 1.32 | -18.37 | 2.96 | 8/8 |
| `ema8_aligned + intraday_stack_24h + opposite_fvg_20` | 6,040 | +585.76 | +81.07 | 59.2% | 1.22 | -28.25 | 2.87 | 8/8 |
| `ema8_aligned + zone_fvg_overlap_100 + opposite_fvg_20` | 6,483 | +565.21 | +77.38 | 58.7% | 1.20 | -27.53 | 2.81 | 8/8 |
| `ema8_aligned + avoid_after_hours + opposite_fvg_20` | 5,662 | +547.73 | +77.81 | 58.8% | 1.22 | -29.20 | 2.67 | 8/8 |
| `ema8_aligned + intraday_stack_7d + ny_main_or_overlap` | 3,267 | +399.69 | +56.78 | 59.3% | 1.29 | -21.95 | 2.59 | 8/8 |
| `ema8_aligned + ny_main_or_overlap + avoid_after_hours` | 3,516 | +411.37 | +58.44 | 59.0% | 1.27 | -22.76 | 2.57 | 8/8 |
| `ema8_aligned + ny_main_or_overlap` | 3,516 | +411.37 | +58.44 | 59.0% | 1.27 | -22.76 | 2.57 | 8/8 |
| `cost_le_0p05 + ema8_aligned + avoid_after_hours` | 2,238 | +308.12 | +43.81 | 58.4% | 1.33 | -17.12 | 2.56 | 8/8 |

## Sleeve1 Recut

| Version | Trades | Net R | WR | PF | DD | Years | Months |
|---|---:|---:|---:|---:|---:|---:|---:|
| `all` | 1,032 | +256.11 | 63.9% | 1.68 | -12.69 | 8/8 | 53/80 |
| `causal_0930` | 720 | +53.77 | 55.1% | 1.17 | -15.41 | 6/8 | 38/80 |
| `causal_1000` | 706 | +54.23 | 55.2% | 1.17 | -12.86 | 7/8 | 40/80 |
| `pre_0930` | 312 | +202.34 | 84.0% | 4.92 | -3.09 | 7/7 | 49/54 |

## Verdict

Claude is directionally correct. Once ORB flags are made time-available, the ORB-based candidates collapse. The old Sleeve1 and SDR-002 sweep results should be treated as contaminated research artifacts, not live baselines.

The best causal sweep result is positive but modest, not production-grade by our previous standard. The next real task is to rebuild the feature matrix from raw bars with causal ORB semantics and audit every other selection flag for time availability before searching again.