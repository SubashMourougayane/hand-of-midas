# 005 — EIA Wednesday Mean Reversion on Brent: Result

**Source:** floor folklore + commodity news-event papers.
**Status:** TRUSTED — clear loser.

## Config
- Wednesdays only
- Release at 14:30 UTC
- Pre-release stdev: 30 M3 bars
- Decision: 6 min after release (14:36)
- Overshoot threshold: 2σ
- SL buffer: 1.5σ beyond spike extreme
- Hold: max 40 bars (2 hours)

## Result on dev window

| Metric | Value |
|---|---:|
| Trades | 87 |
| WR | 35.6 % |
| PF | 0.282 |
| P&L | −$10,033 |
| Max DD | 47 % |

## Year-by-year

| Year | Trades | WR % | P&L |
|---|---:|---:|---:|
| 2019 | 3   | 33 | −$395 |
| 2020 | 14  | 43 | −$1,271 |
| 2021 | 21  | 33 | −$2,234 |
| 2022 | 28  | 39 | −$1,953 |
| 2023 | 21  | 29 | −$2,340 |

## Honest interpretation

Same finding as #002: **mean-reverting Brent on intraday news = wrong-direction.** When EIA creates a 2σ spike, the move tends to CONTINUE for the next ~2 hours, not revert. PF 0.28 means the strategy hits SL nearly 3x more often than TP.

The published "post-news mean reversion" pattern that exists on equity indices around FOMC does NOT replicate on BCO_USD around EIA. Different microstructure: EIA inventories are direct supply data; price moves on it are informational, not technical.

A **continuation** strategy on the same setup (buy the up-spike, sell the down-spike) is the obvious counter-test. Not in this sprint; flag for follow-up.

## Verdict

Not promoted. Mean reversion on Brent at high-z thresholds = systematic loser, second confirmation after #002.

## Safeguards
- Lookahead PASS, random baseline PASS.

## Reproduce
```bash
python Labs/strategies/005_eia_wednesday_meanrev_brent.py
```
