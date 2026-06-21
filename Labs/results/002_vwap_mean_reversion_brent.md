# 002 — VWAP Mean Reversion on Brent: Result

**Source:** institutional VWAP-fade execution literature; QuantStart, Robust Cmdty Trading templates.
**Status:** TRUSTED (lookahead PASS, random baseline PASS) — catastrophic loser.

## Config tested

| Param | Value |
|---|---|
| Session start (UTC) | 00:00 |
| Entry σ threshold | 2.0 |
| SL σ multiplier | 3.0 |
| Min warmup bars | 30 |
| Max bars hold | 80 |
| One trade / day / extreme | yes |

## Result on dev window (2019-09-26 → 2023-12-31)

| Metric | Value |
|---|---:|
| Trades | 1,101 |
| **Win rate** | **13.08 %** |
| **Profit factor** | **0.196** |
| **Total P&L** | **−$252,060.78** |
| **Max DD (worst yearly)** | **100 %** (account blown) |

## Year-by-year

Every year red. Account hit zero in 2020, 2021, 2023.

| Year | Trades | Wins | WR % | P&L | DD % |
|---|---:|---:|---:|---:|---:|
| 2019 | 68  | 7  | 10 | −$4,991 | 99.9 |
| 2020 | 259 | 21 | 8  | −$5,000 | 100  |
| 2021 | 259 | 19 | 7  | −$5,000 | 100  |
| 2022 | 258 | 55 | 21 | −$4,995 | 99.9 |
| 2023 | 257 | 42 | 16 | −$5,000 | 100  |

## Honest interpretation

13% WR on a 2σ-fade is **structurally wrong direction**. When price extends 2σ from VWAP on Brent intraday, it overwhelmingly **continues** rather than reverting. This is a trending-market signature, not a mean-reverting one.

Mean reversion strategies have edge on instruments with strong central-tendency dynamics (some FX pairs, some equity indices). **Brent at M3 is not such an instrument.**

## Bug found and fixed (Lab #002)

`if len(day_df) < cfg.min_warmup_bars + 5: continue` — created a 5-bar future-data dependency. Truncated runs at the moment the strategy could actually fire would skip the day. Fixed to `<= min_warmup_bars`. Lookahead PASS afterwards.

## Verdict

Not promoted. Strategy class is wrong for this instrument at this timeframe. Reverse direction (trend continuation on extension) is more interesting — that's exactly what strategy #4 (Donchian breakout) tests.

## Reproduce

```bash
python Labs/strategies/002_vwap_mean_reversion_brent.py
```
