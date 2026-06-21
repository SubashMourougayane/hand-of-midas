# 001 — ORB on Brent: Result

**Source:** Toby Crabel, "Day Trading with Short-Term Price Patterns and Opening Range Breakout" (1990).

**Status:** TRUSTED (lookahead PASS, random baseline PASS) — but does NOT have edge.

## Config tested

| Param | Value |
|---|---|
| Session open hour (UTC) | 13:00 |
| Range duration | 60 min |
| SL buffer | 10 % of range |
| Reward / risk | 2.0 |
| Max bars hold | 80 (= 4 h) |
| One trade / direction / day | yes |

## Result on dev window (2019-09-26 → 2023-12-31)

| Metric | Value |
|---|---:|
| Signals emitted | 1,099 |
| Trades filled | 1,099 |
| Wins | 386 |
| Losses | 713 |
| **Win rate** | **35.12 %** |
| **Profit factor** | **0.753** |
| **Total P&L** | **−$34,704.42** |
| **Max DD (worst yearly)** | **97.7 %** |

## Year-by-year (yearly $5K reset)

| Year | Trades | Wins | WR % | P&L | DD % |
|---|---:|---:|---:|---:|---:|
| 2019 | 67  | 24 | 35.8 | −$1,992 | 45 |
| 2020 | 259 | 96 | 37.1 | −$3,921 | 81 |
| 2021 | 258 | 79 | 30.6 | −$4,859 | 98 |
| 2022 | 258 | 91 | 35.3 | −$4,170 | 87 |
| 2023 | 257 | 96 | 37.4 | −$2,878 | 81 |

Every full year is red. Pattern is consistent across volatility regimes (2020 COVID, 2022 Russia spike, 2023 normalisation).

## Safeguards

- **Lookahead audit:** PASS (10 samples, 0 mismatches) — after fixing the original `len(scan_df) < 2` bug that was introducing 1-bar lookahead. Recorded: see Labs/strategies/001_orb_brent.py line ~85 comment.
- **Random baseline:** PASS — random LONG/SHORT entries through the same fill model produced PnL/unit = -38.65 (negative, as expected from slippage drag). Fill model is honest.

## Bug found and fixed (Lab #001)

The first version had `if len(scan_df) < 2: continue` which skipped any day where the breakout candle was the only available scan bar. This created a 1-bar future-data dependency (the BT could only emit signals on days with at least 2 post-range bars, which truncated-data audits don't satisfy). Fixed to `< 1`. Lookahead audit now passes.

## Honest interpretation

ORB at these published defaults loses money on Brent 2019-2023. Two interpretations:

1. **The strategy works only at parameter sets we haven't tried.** Maybe 30-min range, RR=1.5 or 3.0, different session hour. Possible but tuning here = curve fitting.
2. **Brent intraday isn't trending enough at the 13:00 UTC session anchor for ORB to capture edge.** Plausible. 13:00 UTC is mid-NY morning; oil's institutional flow is more weighted to OPEC announcements + EIA inventory + futures roll, not session opens.

**Verdict: Not promoted. Move on.**

## Live-reproducibility check

- Range computed from bars in `[open, open+60min]` — all closed by the time the breakout check runs.
- Breakout fires on the FIRST bar after range close where `mid_high > range_high AND mid_close > range_high` (or symmetric short).
- No reference to bars > entry_bar_ts.
- Lookahead audit confirms: same signal at time T whether full or truncated data is fed in.

## Reproduce

```bash
cd /Users/subash/SUBASH/GoldDigger
python Labs/strategies/001_orb_brent.py
```

Deterministic — same numbers every run.
