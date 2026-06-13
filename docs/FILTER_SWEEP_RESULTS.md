# Filter Sweep Results — Live Scoresheet

Companion to `docs/FILTER_SWEEP_PLAN.md`. Filled as each filter completes.

**No fake numbers.** Every BT figure comes from `run_backtest()`; every Live
figure comes from `extract_live_signals` against the actual `_run_*_sweep_core`.

## Decision tracker

| # | Filter | Wave | Status | Branch | BT PF Δ | BT P&L Δ | Live signal Δ | Decision |
|---|---|---|---|---|---|---|---|---|
| 5 | BE 50% → 35% | 1 | _running_ | filter-05-be-pct | — | — | — | — |
| 6 | Trailing SL after BE | 1 | _running_ | filter-06-trail-sl | — | — | — | — |
| 7 | Partial TP at 50% | 1 | _running_ | filter-07-partial-tp | — | — | — | — |
| 16 | R:R lower bound 1.5 | 2 | pending | — | — | — | — | — |
| 2 | First-Sweep-of-Day | 2 | pending | — | — | — | — | — |
| 9 | R:R Upper Bound 4.0 | 2 | pending | — | — | — | — | — |
| 3 | TP Feasibility | 3 | pending | — | — | — | — | — |
| 4 | Anti-Trend-Extension | 3 | pending | — | — | — | — | — |
| 12 | Engulfing-of-doji | 3 | pending | — | — | — | — | — |
| 13 | Engulfing wick-vs-body | 4 | pending | — | — | — | — | — |
| 14 | prev=sweep-bar pollution | 4 | pending | — | — | — | — | — |
| 10 | Spread-Inside SL (Oil Macro) | 4 | pending | — | — | — | — | — |
| 15 | Cooldown bypass race fix | 4 | pending | — | — | — | — | — |

## Per-filter detailed results

(populated after each filter completes)

---

## Wave 1 — pending
## Wave 2 — pending
## Wave 3 — pending
## Wave 4 — pending
