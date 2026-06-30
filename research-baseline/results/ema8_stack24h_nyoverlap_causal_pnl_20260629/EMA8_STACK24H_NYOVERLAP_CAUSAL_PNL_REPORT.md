# Causal Candidate PnL Report — EMA8 + Stack24h + NY Main/Overlap

Generated: 2026-06-29

Rule: `ema8_aligned AND intraday_stack_24h AND ny_main_or_overlap`.

This rule does not use `orb_reversal`, `orb_continuation`, or `orb_inside`, so the known same-day ORB look-ahead issue is not part of this rule. It still depends on current matrix feature correctness; `intraday_stack_24h` should be separately audited before live promotion.

## R Metrics

- Trades: 2,936
- Net R: +382.56R
- R/year: +54.35R
- WR: 59.67%
- PF: 1.31
- Avg R/trade: +0.1303R
- Max DD: -18.01R
- MAR: 3.02
- Ulcer Index: 5.23R
- Recovery trades: 181
- Max loss streak: 9 trades (-9.87R)
- Max win streak: 13 trades
- Positive years: 8/8
- Positive months: 63/85

## Fixed $5k Account, Fixed Risk Per Trade

| Risk | Risk USD | Net PnL | Max DD | Avg Trade |
|---:|---:|---:|---:|---:|
| 1% | $50.00 | $19,128.06 | $-900.42 | $6.52 |
| 2% | $100.00 | $38,256.12 | $-1,800.85 | $13.03 |
| 3% | $150.00 | $57,384.18 | $-2,701.27 | $19.55 |
| 4% | $200.00 | $76,512.24 | $-3,601.69 | $26.06 |
| 5% | $250.00 | $95,640.30 | $-4,502.11 | $32.58 |

## Monthly $5k Reset, Compounds Inside Month

| Risk | Total PnL | Positive Months | Worst Month | Best Month | Worst Intramonth DD |
|---:|---:|---:|---:|---:|---:|
| 1% | $19,725.04 | 63/85 | $-426.26 | $1,172.20 | $-598.26 |
| 2% | $40,730.36 | 63/85 | $-835.54 | $2,591.52 | $-1,178.60 |
| 3% | $63,154.55 | 63/85 | $-1,225.87 | $4,303.61 | $-1,738.62 |
| 4% | $87,148.83 | 62/85 | $-1,595.72 | $6,361.12 | $-2,335.06 |
| 5% | $112,877.83 | 59/85 | $-1,943.90 | $8,824.52 | $-3,104.52 |

## Yearly $5k Reset, Compounds Inside Year

| Risk | Total PnL | Positive Years | Worst Year | Best Year | Worst Intrayear DD |
|---:|---:|---:|---:|---:|---:|
| 1% | $25,364.65 | 8/8 | $939.11 | $7,988.27 | $-1,057.61 |
| 2% | $69,970.57 | 8/8 | $1,746.17 | $27,439.58 | $-4,208.72 |
| 3% | $150,992.33 | 8/8 | $2,326.75 | $72,908.65 | $-14,148.92 |
| 4% | $301,829.60 | 8/8 | $2,606.85 | $174,935.40 | $-40,836.99 |
| 5% | $586,351.82 | 8/8 | $2,548.26 | $394,661.05 | $-106,735.98 |

## Year-by-Year R

| Year | Trades | Net R | WR | PF | DD |
|---:|---:|---:|---:|---:|---:|
| 2019 | 161 | +29.31 | 64.0% | 1.47 | -8.32 |
| 2020 | 436 | +47.31 | 58.9% | 1.25 | -18.01 |
| 2021 | 406 | +51.24 | 59.6% | 1.30 | -15.11 |
| 2022 | 433 | +54.14 | 59.8% | 1.29 | -13.71 |
| 2023 | 460 | +19.44 | 56.3% | 1.09 | -14.45 |
| 2024 | 417 | +64.32 | 60.7% | 1.38 | -9.84 |
| 2025 | 404 | +97.43 | 63.9% | 1.65 | -8.90 |
| 2026 | 219 | +19.36 | 55.3% | 1.19 | -9.52 |

## Cost Stress

| Extra Cost / Trade | Net R | PF | DD | Positive Years |
|---:|---:|---:|---:|---:|
| 0.000R | +382.56 | 1.31 | -18.01 | 8/8 |
| 0.025R | +309.16 | 1.24 | -20.46 | 8/8 |
| 0.050R | +235.76 | 1.18 | -23.19 | 7/8 |
| 0.100R | +88.96 | 1.07 | -36.51 | 6/8 |
| 0.150R | -57.84 | 0.96 | -103.99 | 3/8 |
| 0.200R | -204.64 | 0.86 | -213.81 | 1/8 |
| 0.300R | -498.24 | 0.69 | -501.73 | 0/8 |
| 0.400R | -791.84 | 0.54 | -792.88 | 0/8 |
| 0.500R | -1085.44 | 0.41 | -1086.28 | 0/8 |

## Verdict

This is a real improvement over proper Sleeve1, but it is not a high-PF system. It is broad and stable by year, with modest PF and meaningful drawdown. It is research-worthy, not live-base-certified until `intraday_stack_24h` and all source features are causality-audited from raw bars.