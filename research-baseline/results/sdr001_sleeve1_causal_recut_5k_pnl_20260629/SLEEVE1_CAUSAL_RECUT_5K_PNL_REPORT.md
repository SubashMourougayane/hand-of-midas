# Sleeve1 Proper Causal Recut — 5k PnL

Generated: 2026-06-29

Definition: original Sleeve1 trades, but only entries where same-day NY ORB is actually known: `entry_time >= 09:30 America/New_York`.

## R Metrics

- Trades: 720
- Net R: +53.77R
- R/year: +7.66R
- WR: 55.14%
- PF: 1.17
- Avg R/trade: +0.0747R
- Max DD: -15.41R
- MAR: 0.50
- Ulcer Index: 5.27R
- Recovery trades: 227
- Max loss streak: 6 trades (-6.21R)
- Positive years: 6/8
- Positive months: 38/80

## Fixed $5k Account, Fixed Risk Per Trade

| Risk | Risk USD | Net PnL | Max DD | Avg Trade |
|---:|---:|---:|---:|---:|
| 1% | $50.00 | $2,688.47 | $-770.52 | $3.73 |
| 2% | $100.00 | $5,376.94 | $-1,541.05 | $7.47 |
| 3% | $150.00 | $8,065.41 | $-2,311.57 | $11.20 |
| 4% | $200.00 | $10,753.89 | $-3,082.09 | $14.94 |
| 5% | $250.00 | $13,442.36 | $-3,852.62 | $18.67 |

## Monthly $5k Reset, Compounds Inside Month

| Risk | Total PnL | Positive Months | Worst Month | Best Month | Worst Intramonth DD |
|---:|---:|---:|---:|---:|---:|
| 1% | $2,671.38 | 38/80 | $-215.05 | $435.52 | $-305.12 |
| 2% | $5,308.35 | 38/80 | $-425.59 | $900.63 | $-595.39 |
| 3% | $7,910.55 | 37/80 | $-631.44 | $1,396.55 | $-871.31 |
| 4% | $10,477.54 | 37/80 | $-832.43 | $1,924.53 | $-1,133.37 |
| 5% | $13,008.82 | 37/80 | $-1,028.43 | $2,485.77 | $-1,396.18 |

## Yearly $5k Reset, Compounds Inside Year

| Risk | Total PnL | Positive Years | Worst Year | Best Year | Worst Intrayear DD |
|---:|---:|---:|---:|---:|---:|
| 1% | $2,797.08 | 6/8 | $-376.15 | $1,118.42 | $-579.56 |
| 2% | $5,819.07 | 6/8 | $-750.29 | $2,404.36 | $-1,147.40 |
| 3% | $9,071.58 | 6/8 | $-1,118.28 | $3,861.80 | $-1,790.84 |
| 4% | $12,550.05 | 6/8 | $-1,476.42 | $5,489.28 | $-2,910.67 |
| 5% | $16,237.28 | 6/8 | $-1,849.65 | $7,278.92 | $-4,389.94 |

## Year-by-Year R

| Year | Trades | Net R | WR | PF | DD |
|---:|---:|---:|---:|---:|---:|
| 2019 | 12 | +1.59 | 58.3% | 1.31 | -2.28 |
| 2020 | 102 | +8.30 | 55.9% | 1.18 | -8.50 |
| 2021 | 59 | +5.87 | 55.9% | 1.25 | -10.49 |
| 2022 | 78 | +9.24 | 57.7% | 1.29 | -4.23 |
| 2023 | 64 | -7.51 | 46.9% | 0.78 | -11.67 |
| 2024 | 117 | +20.74 | 59.8% | 1.45 | -6.20 |
| 2025 | 174 | -4.87 | 50.0% | 0.95 | -10.40 |
| 2026 | 114 | +20.41 | 59.6% | 1.44 | -6.11 |

## Verdict

This is the real Sleeve1 after removing pre-ORB look-ahead. It is marginal: positive over the full period, but low PF, low MAR, poor monthly stability, and not strong enough for a live base without new causal filters.