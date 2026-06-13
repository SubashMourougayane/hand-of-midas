# Weekend Results — 2026-06-13

Companion to `docs/WEEKEND_PLAN.md`. Each section gets filled as work
completes. Failed/no-ship filters captured so we have a record of what
was tried and why it didn't work.

## 1. Parity audit (Live ↔ Backtest)

_pending — to be filled after run_

**Per-system results (21-year):**

| System | BT signals | Live-replay signals | Direction agree % | Avg entry drift | BT P&L | Live-replay P&L | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| Gold Macro | — | — | — | — | — | — | — |
| Gold Micro | — | — | — | — | — | — | — |
| Oil Macro | — | — | — | — | — | — | — |
| Oil Micro | — | — | — | — | — | — | — |

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

_pending — full day analysis from observability logs_

**Coverage:** ~2026-06-12 14:30 UTC onward (observability v2 deploy)

### Trades summary
- Trades closed: 3 (postmortems linked below)

### Per-system stats (TBD)
- Gold Macro: ?
- Gold Micro: ?
- Oil Macro: ?
- Oil Micro: ?

### Linked postmortems
- [GD-MI-da28460d](trades/GD-MI-da28460d.md) — Gold Micro, SL, −$369.74
- [GD-MI-0b973d80](trades/GD-MI-0b973d80.md) — Gold Micro, SL, −$358.83
- [OIL-MI-aba3b668](trades/OIL-MI-aba3b668.md) — Oil Micro, MAX_HOLD win, +$458.80

**Net Friday P&L: −$269.77** (across 3 closed trades)

### Anomalies (TBD)
- ?

## Summary

_to be filled at end of weekend with overall conclusions and ship-list_
