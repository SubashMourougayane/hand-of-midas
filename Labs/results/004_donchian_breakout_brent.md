# 004 — Donchian Breakout on Brent: Result

**Source:** Donchian (1949) channel system; Turtle Traders 20/10 codification.
**Status:** TRUSTED — modest loser, consistent across years.

## Config
- 20 H1-bar breakout high/low (lookback ~20 hours)
- 10 H1-bar opposite-channel for SL placement
- RR = 2.0
- Max hold = 240 M3 bars (12 hours)
- One trade per day

## Result on dev window

| Metric | Value |
|---|---:|
| Trades | 958 |
| WR | 45.3 % |
| PF | 0.882 |
| P&L | −$7,563 |
| Max DD | 59.4 % |

## Year-by-year

| Year | Trades | WR % | P&L | DD % |
|---|---:|---:|---:|---:|
| 2019 | 56  | 37 | −$2,204 | 44 |
| 2020 | 221 | 46 | +$406  | 35 |
| 2021 | 225 | 48 | −$1,166 | 47 |
| 2022 | 225 | 46 | −$1,615 | 47 |
| 2023 | 231 | 43 | −$2,824 | 59 |

## Honest interpretation

20-bar (≈ 20 hours) breakouts on Brent intraday produce too many false signals at the 1-hour-bar timeframe. By the time price clears the 20-bar high, the move has often already played out. The fixed 2R target rarely reaches before the 10-bar opposite extreme (SL) gets touched.

2020 marginally positive is the COVID-period strong-trend bias. Every other year shows the strategy bleeds.

## Verdict

Not promoted. Tested at the source-cited defaults; tuning here would be curve-fitting.

## Safeguards
- Lookahead PASS, random baseline PASS.

## Reproduce
```bash
python Labs/strategies/004_donchian_breakout_brent.py
```
