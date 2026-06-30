# EMA8 Boundary Causality Audit — Stack24h NY/Overlap Candidate

Generated: 2026-06-29

Rule under audit: `ema8_aligned + intraday_stack_24h + ny_main_or_overlap`.

Issue tested: `ema8_aligned` can be leaky when entry occurs inside an M15 bar but the EMA8 value comes from that M15 bar close. Clean conservative proxy: keep only entries exactly on M15 boundaries (`minute % 15 == 0`).

## Segment Results

| Segment | Trades | Net R | R/yr | WR | PF | DD | MAR | Years | Months |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `full_rule` | 2,936 | +382.56 | +54.35 | 59.67% | 1.31 | -18.01 | 3.02 | 8/8 | 63/85 |
| `m15_boundary_only` | 736 | +164.63 | +23.39 | 64.40% | 1.60 | -10.43 | 2.24 | 8/8 | 62/85 |
| `inside_m15` | 2,200 | +217.93 | +32.41 | 58.09% | 1.23 | -21.45 | 1.51 | 7/8 | 51/82 |

## Clean Boundary Version — Fixed $5k Risk

| Risk | Risk USD | Net PnL | Max DD | Avg Trade |
|---:|---:|---:|---:|---:|
| 1% | $50.00 | $8,231.65 | $-521.37 | $11.18 |
| 2% | $100.00 | $16,463.30 | $-1,042.75 | $22.37 |
| 3% | $150.00 | $24,694.94 | $-1,564.12 | $33.55 |
| 4% | $200.00 | $32,926.59 | $-2,085.50 | $44.74 |
| 5% | $250.00 | $41,158.24 | $-2,606.87 | $55.92 |

## Clean Boundary Version — Monthly $5k Reset

| Risk | Total PnL | Positive Months | Worst Month | Best Month | Worst DD |
|---:|---:|---:|---:|---:|---:|
| 1% | $8,302.30 | 62/85 | $-227.71 | $516.34 | $-318.81 |
| 2% | $16,750.19 | 62/85 | $-450.72 | $1,077.97 | $-628.23 |
| 3% | $25,350.37 | 62/85 | $-668.76 | $1,688.02 | $-928.22 |
| 4% | $34,110.05 | 62/85 | $-881.59 | $2,349.81 | $-1,218.82 |
| 5% | $43,036.92 | 62/85 | $-1,089.00 | $3,066.75 | $-1,500.05 |

## Cost Stress — Clean Boundary Version

| Extra Cost / Trade | Net R | PF | DD | Years |
|---:|---:|---:|---:|---:|
| 0.000R | +164.63 | 1.60 | -10.43 | 8/8 |
| 0.025R | +146.23 | 1.52 | -10.90 | 8/8 |
| 0.050R | +127.83 | 1.44 | -11.38 | 8/8 |
| 0.075R | +109.43 | 1.37 | -11.85 | 8/8 |
| 0.100R | +91.03 | 1.30 | -12.34 | 8/8 |
| 0.150R | +54.23 | 1.17 | -15.55 | 7/8 |
| 0.200R | +17.43 | 1.05 | -19.00 | 6/8 |
| 0.300R | -56.17 | 0.84 | -61.07 | 0/8 |

## Bootstrap — Clean Boundary Version

- p05 net: +122.58R
- p01 net: +105.16R
- p50 net: +164.44R
- p05 PF: 1.41
- P(net < 0): 0.00%

## Year-by-Year Clean Boundary R

| Year | Trades | Net R | WR | PF | DD |
|---:|---:|---:|---:|---:|---:|
| 2019 | 74 | +16.14 | 64.9% | 1.58 | -5.20 |
| 2020 | 110 | +26.98 | 65.5% | 1.67 | -10.43 |
| 2021 | 73 | +21.42 | 68.5% | 1.86 | -3.20 |
| 2022 | 108 | +26.02 | 65.7% | 1.68 | -3.38 |
| 2023 | 104 | +26.74 | 67.3% | 1.72 | -4.32 |
| 2024 | 104 | +21.48 | 63.5% | 1.53 | -6.47 |
| 2025 | 112 | +19.68 | 60.7% | 1.43 | -8.37 |
| 2026 | 51 | +6.17 | 56.9% | 1.28 | -3.15 |

## Verdict

Claude is correct. The full 2,936-trade rule includes many inside-M15 entries where `ema8_aligned` can see the not-yet-closed M15 bar. The conservative clean candidate is the M15-boundary subset.

This clean version is smaller but stronger quality: fewer trades, higher PF, all years positive. It is the best honest candidate so far, pending full raw-bar replay parity.