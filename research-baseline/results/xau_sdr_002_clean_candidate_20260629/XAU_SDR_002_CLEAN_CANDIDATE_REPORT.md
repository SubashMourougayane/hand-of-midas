# XAU-SDR-002 Clean Candidate

Generated: 2026-06-29

## Status

This is a new clean candidate built inside the `bt_engine` SDR architecture. It is not the old Sleeve1 baseline and it does not use ORB features.

The old 736-trade boundary-EMA candidate is not promoted. On review, M15 bars are left-labelled, so an entry at `10:15` cannot use the M15 candle stamped `10:15`; that candle has just opened. This candidate uses only the previous fully closed M15 candle.

## Rule

Take an `m15_2c_1atr` SDR reclaim trade only when all flags are true:

1. `closed_m15_ema8_aligned`
   - Uses the last M15 candle with `m15_timestamp < entry_timestamp`.
   - Demand requires previous closed M15 close above EMA8.
   - Supply requires previous closed M15 close below EMA8.
2. `intraday_stack_24h`
   - At least one same-direction intraday S/D zone overlaps the current zone.
   - Only zones with `created_timestamp <= entry_timestamp` and within the prior 24h are counted.
   - The current zone itself is excluded.
3. `ny_main_or_overlap`
   - Entry time is in London/NY overlap or NY main session.
   - This is derived only from the entry timestamp.
4. `cost_le_0p05`
   - Fixed XAU cost model cost is <= 0.05R.
5. `body_ge_45`
   - Confirmation candle body is at least 45% of the candle range.
6. `base_body_low`
   - Base candle body is <= 35% of the base candle range.

Registered engine strategy: `sdr002_clean`

Fixed forward rule:

```text
closed_m15_ema8_aligned
intraday_stack_24h
ny_main_or_overlap
cost_le_0p05
body_ge_45
base_body_low
```

## Causality Rules

- No ORB flags are used.
- ORB forward flags are blocked in live validation.
- No same-bar M15 EMA is used.
- M15 EMA context is strictly previous closed M15 only.
- Intraday stack zones must be created before or at entry time.
- Future stack zones are not counted.
- The current event zone is excluded from the stack count.
- Event generation still follows the raw M1 -> M5/M15 pipeline.

## Backtest Metrics

Source: `bt_engine` raw replay from MT5 M1 data, 2019-01-01 through 2026-06-18.

| Metric | Value |
|---|---:|
| Trades | 296 |
| Net R | +51.6867R |
| Win Rate | 60.81% |
| Profit Factor | 1.439 |
| Max DD | -7.638R |
| MAR | 0.846 |
| Positive Years | 8 / 8 |
| Positive Months | 41 / 74 |

## Yearly R

| Year | Trades | Net R |
|---:|---:|---:|
| 2019 | 15 | +0.4802 |
| 2020 | 40 | +12.5209 |
| 2021 | 21 | +1.5272 |
| 2022 | 35 | +2.4301 |
| 2023 | 25 | +0.5255 |
| 2024 | 39 | +2.0463 |
| 2025 | 66 | +24.0506 |
| 2026 | 55 | +8.1059 |

## Extra Cost Stress

| Extra Cost / Trade | Net R | PF | Max DD | Positive Years |
|---:|---:|---:|---:|---:|
| 0.000R | +51.69 | 1.44 | -7.64 | 8 / 8 |
| 0.025R | +44.29 | 1.37 | -8.06 | 7 / 8 |
| 0.050R | +36.89 | 1.30 | -8.49 | 6 / 8 |
| 0.075R | +29.49 | 1.23 | -9.34 | 3 / 8 |
| 0.100R | +22.09 | 1.17 | -10.72 | 3 / 8 |
| 0.150R | +7.29 | 1.05 | -17.02 | 2 / 8 |
| 0.200R | -7.51 | 0.95 | -23.82 | 2 / 8 |

## Bootstrap

5,000 trade-order bootstrap samples:

| Metric | Value |
|---|---:|
| p01 Net R | +13.10R |
| p05 Net R | +24.52R |
| p50 Net R | +51.92R |
| p95 Net R | +78.62R |
| P(Net < 0) | 0.10% |

## Files

- `bt_engine_xau_sdr_002_clean_trades.csv`
- `bt_engine_generated_events_with_clean_flags.csv`
- `xau_sdr_002_clean_summary.json`
- `xau_sdr_002_clean_cost_stress.csv`
- `xau_sdr_002_clean_yearly.csv`
- `xau_sdr_002_clean_monthly.csv`
- `clean_causal_flag_sweep.csv`
- `clean_causal_flag_sweep_shortlist.csv`

## Verdict

Promote as a clean research/live-candidate only, not as a production-money strategy yet.

The edge is modest but causally defensible. It survives bootstrap, but it is cost-sensitive and depends materially on 2025. Next gate should be paper-live replay with real DWX spread sampling during NY hours.
