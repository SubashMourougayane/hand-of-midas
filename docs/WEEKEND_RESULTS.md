# Weekend Results — 2026-06-13

Companion to `docs/WEEKEND_PLAN.md`. Each section gets filled as work
completes. Failed/no-ship filters captured so we have a record of what
was tried and why it didn't work.

## 1. Parity audit (Live ↔ Backtest)

**Status:** in flight (4 parallel processes, ETA ~3 hours).

**365-day calibration result (Gold Micro):**
- BT: 587 signals (run time 2.6s)
- Live: 603 signals (run time 412.5s)
- Parity: 67.5% (407 in both / 88 BT-only / 196 Live-only)
- **Direction agreement on overlap: 100%** ✓
- Avg entry drift: $0.0027  (essentially zero)
- Avg SL drift: $0.0025  (essentially zero)
- Avg TP drift: $4.62 (worth investigating — possibly different TP-method in some edge case)

**Headline:** Live fires more aggressively than BT (196 Live-only vs 88 BT-only). Likely partial-bar fires that BT doesn't see (we explored this yesterday with Filter A, which we rejected). But the 100% direction agreement on overlapping signals confirms strategy alignment is sound.

**Full 21-year run launched.** Will fill table when complete.

**Per-system results (21-year):**

| System | BT signals | Live-replay signals | Direction agree % | Avg entry drift | Verdict |
|---|---:|---:|---:|---:|---|
| Gold Macro | _running_ | — | — | — | — |
| Gold Micro | _running_ | — | — | — | — |
| Oil Macro | _running_ | — | — | — | — |
| Oil Micro | _running_ | — | — | — | — |

## 2. Edge filter sweep

_pending — each filter gets one row as it's evaluated_

| # | Filter | Branch | BT trades Δ | BT WR Δ | BT PF Δ | BT P&L Δ | Decision | Notes |
|---|---|---|---:|---:|---:|---:|---|---|
| 5 | BE 50% → 35% | — | — | — | — | — | — | — |
| 6 | Trailing SL after BE | — | — | — | — | — | — | — |
| 7 | Partial TP at 50% | — | — | — | — | — | — | — |
| 16 | R:R lower bound 0.8 → 1.5 | — | — | — | — | — | — | — |
| 2 | First-Sweep-of-Day | — | — | — | — | — | — | — |
| 3 | TP Feasibility | — | — | — | — | — | — | — |
| 4 | Anti-Trend-Extension | — | — | — | — | — | — | — |
| 9 | R:R Upper Bound 4.0 | — | — | — | — | — | — | — |
| 10 | Spread-Inside SL (Oil Macro) | — | — | — | — | — | — | — |
| 12 | Engulfing-of-doji | — | — | — | — | — | — | — |
| 13 | Engulfing wick-vs-body | — | — | — | — | — | — | — |
| 14 | prev=sweep-bar pollution | — | — | — | — | — | — | — |
| 15 | Cooldown bypass (race fix) | — | — | — | — | — | — | — |

## 3. Friday postmortem

**Status:** ✅ Complete — full report at `docs/FRIDAY_POSTMORTEM.md`.

**Coverage:** 2026-06-12 from observability v2 deployment (~14:30 UTC) until midnight UTC.

### Per-system summary

| Service | Lines | Errors | Sigs fired | Executed | Skipped | Sweeps | Top gate reject |
|---|---:|---:|---:|---:|---:|---:|---|
| Gold Macro | 3,802 | 0 | 0 | 0 | 0 | 196 | bias_block (196) |
| Oil Macro | 3,744 | 0 | 0 | 0 | 0 | 173 | bias_block (173) |
| Gold Micro | 6,126 | 0 | 3 | 2 | 0 | 992 | bias_block (589) |
| Oil Micro | 5,767 | 1 | 1 | 1 | 0 | 573 | sweep_already_traded (378) |

### Key Friday observations
- **Gold Macro & Oil Macro: 0 trades all day.** Every sweep that fired was direction-mismatched with daily bias and got bias_blocked. **The bias filter killed everything.**
- **Gold Micro: 992 sweeps detected, 589 bias_blocked.** Of the 3 fires, 2 executed (the 2 LONG SL trades). The 3rd fired but didn't execute — likely max_trades_per_day=3 cap hit, OR one-at-a-time rule blocked it.
- **Oil Micro: 573 sweeps, 378 dedup'd as already-traded** (normal). 1 fire → 1 trade → MAX_HOLD win.
- **Net Friday P&L: −$269.77** (across 3 closed trades, 1W 2L).
- **Total errors across all 4 services: 1** (Oil Micro). No catastrophic events.
- **Day was bias-dominated**: yesterday's daily was strongly bullish for Gold (closed at 96% of range), strongly bearish for Oil. Both biases ate hundreds of sweeps that didn't match direction.

### Linked trade postmortems
- [GD-MI-da28460d](trades/GD-MI-da28460d.md) — Gold Micro, SL, −$369.74
- [GD-MI-0b973d80](trades/GD-MI-0b973d80.md) — Gold Micro, SL, −$358.83
- [OIL-MI-aba3b668](trades/OIL-MI-aba3b668.md) — Oil Micro, MAX_HOLD win, +$458.80

### Anomalies
- 1 ERROR in oil-micro (not yet investigated, see full report)
- 0 EXIT_AMBIGUOUS streaks (DWX OnTradeTransaction working correctly all day after the recompile)
- 0 CLOSE_FAILED retries (other than the OIL-MI-aba3b668 MAX_HOLD case at 18:55, already documented)

See `docs/FRIDAY_POSTMORTEM.md` for full per-service breakdown.

## Summary

_to be filled at end of weekend with overall conclusions and ship-list_
