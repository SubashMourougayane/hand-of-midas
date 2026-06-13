# Filter Sweep Plan — Weekend 2026-06-13/14

Companion to `docs/WEEKEND_PLAN.md`. This is the execution plan for Goal #2.

## What we're doing

Test all 12 untested edge filters from `project_edge_filters.md` to decide
which ones to ship. Decision is made on **real backtest engine numbers** plus
**real live signal-gen numbers** — no replay tools, no synthetic fills, no
phantom-fill assumptions.

## Hard rules

1. **No fake numbers.** Every measurement uses production code paths:
   - **Backtest:** `run_backtest()` from each system's `backend(-X)/backtest/engine.py`
     — same engine that powers the dashboard.
   - **Live:** the proven `tests/harness/parity/extractor.py:extract_live_signals`
     wrapping the actual live `_run_micro_sweep_core` / `_run_alpha_sweep_core`
     scheduler functions. NO custom replay tool.

2. **No phantom fills.** Backtest fill goes through `execute_trade()` from
   `backend/execution/fill_model.py` (with break-even, slippage, gap-through,
   per-bar walking). Same fill model live uses for SL/TP detection.

3. **Filter implementation pattern:** kwarg-gated, default off. Live signal-gen
   gets a new `skip_<filter>=False` kwarg in `_run_*_sweep_core`. Backtest
   signal-gen gets the same kwarg in `generate_signals`. Default values keep
   live + dashboard behavior unchanged unless the filter is explicitly merged
   to `midas-deploy`.

4. **Per-filter feature branch.** Each filter ships on its own branch
   `filter-NN-name`. After backtest:
   - **Ship** → user approves → merge to midas-deploy → live picks up next deploy
   - **Stash** → user rejects → branch kept as `archive-filter-NN` for record
   - Default action if user is silent: stash (safe).

5. **Both layers measured.** For each filter:
   - **BT pre/post:** `run_backtest()` 21-yr full history, all 4 systems.
   - **Live pre/post:** `extract_live_signals()` over 3 regime years, all 4 systems.
   - Telegram delta report after each filter completes.

## Filter scope per system

Most filters apply to all 4 systems. Two exceptions per `project_edge_filters.md`:
- **#10 Spread-Inside SL** — Oil Macro only (Oil Macro's sl_buffer was the issue)
- **#15 Cooldown bypass / race fix** — Macros only (Micros don't have the race)

| # | Filter | Scope |
|---|---|---|
| 5 | BE 50% → 35% | All 4 |
| 6 | Trailing SL after BE | All 4 |
| 7 | Partial TP at 50% | All 4 |
| 16 | R:R lower bound 0.8 → 1.5 | All 4 |
| 2 | First-Sweep-of-Day | All 4 |
| 9 | R:R Upper Bound 4.0 | All 4 |
| 3 | TP Feasibility | All 4 |
| 4 | Anti-Trend-Extension | All 4 |
| 12 | Engulfing-of-doji | All 4 |
| 13 | Engulfing wick-vs-body | All 4 |
| 14 | prev=sweep-bar pollution | All 4 |
| 10 | Spread-Inside SL | Oil Macro only |
| 15 | Cooldown bypass race fix | Macros only |

## Regimes

Three calendar years from the parity audit (already validated as healthy
baseline at >78% parity, 100% direction agreement):

- **2008** — GFC / Lehman crisis (extreme volatility crash)
- **2013** — Gold bear / sideways (range-bound, low directional bias)
- **2022** — Russia invasion / inflation surge (sustained trend, boom)

This gives us crash + sideways + boom regime coverage in 3 years.

## Concurrency

**Sequential, one filter at a time** — user requested perfect comparison and
report documents per filter; no parallel waves.

| Order | Filter | Type | Estimated wall-clock |
|---|---|---|---|
| 1 | 5  — BE 50% → 35% | Fill model | ~6 min (BT only) |
| 2 | 6  — Trailing SL after BE | Fill model | ~6 min (BT only) |
| 3 | 7  — Partial TP at 50% | Fill model | ~6 min (BT only) |
| 4 | 16 — R:R lower bound 1.5 | Signal-gen | ~30 min |
| 5 | 2  — First-Sweep-of-Day | Signal-gen | ~30 min |
| 6 | 9  — R:R Upper Bound 4.0 | Signal-gen | ~30 min |
| 7 | 3  — TP Feasibility | Signal-gen | ~30 min |
| 8 | 4  — Anti-Trend-Extension | Signal-gen | ~30 min |
| 9 | 12 — Engulfing-of-doji | Signal-gen | ~30 min |
| 10 | 13 — Engulfing wick-vs-body | Signal-gen | ~30 min |
| 11 | 14 — prev=sweep-bar pollution | Signal-gen | ~30 min |
| 12 | 10 — Spread-Inside SL (Oil Macro only) | Signal-gen | ~10 min |
| 13 | 15 — Cooldown bypass race fix (Macros only) | Signal-gen | ~15 min |

**Total: ~5 hours sequential.** Telegram between every filter with summary
+ report path. Decision required from user before next filter starts.

## Telegram protocol

After every filter completes:

```
🧪 FILTER #N — <name> COMPLETE

BT (21-yr, all 4 systems):
  Gold Macro:  base PF X.XX → filter PF Y.YY  (Δ +Z.ZZ%, $XXX)
  Gold Micro:  base PF X.XX → filter PF Y.YY  (Δ +Z.ZZ%, $XXX)
  Oil Macro:   base PF X.XX → filter PF Y.YY  (Δ +Z.ZZ%, $XXX)
  Oil Micro:   base PF X.XX → filter PF Y.YY  (Δ +Z.ZZ%, $XXX)

Live (3 regimes × 4 systems where applicable):
  Total signal count delta
  Direction split agreement

Verdict: [SHIP / STASH] <reason>
Report: docs/filter_results/FILTER_NN_<name>.md

Reply in Claude Code: "ship N" or "stash N" or "next" (= stash + continue)
```

If user is silent for >1 hour, **default = stash + continue** to keep the
sweep moving. Branches stay as `archive-filter-NN` for later review.

## Default decision criteria

(Same as Filter A standard — yesterday's lesson)

- ✅ **Ship**: PF improves ≥5% AND total P&L stays within 95% of baseline
- 🟡 **Maybe**: PF improves but P&L drops 5-10% (call user judgment)
- ❌ **No-ship**: PF flat/worse OR P&L drops >10%

## Output artifacts

- `docs/FILTER_SWEEP_RESULTS.md` — master scoresheet (one row per filter)
- `docs/filter_results/FILTER_NN_<name>.md` — full per-filter report:
  - hypothesis + implementation summary
  - BT pre table (4 systems × trades/WR/PF/$P&L)
  - BT post table (same shape)
  - BT delta table
  - Live pre table (per system × per regime × signal counts/direction split)
  - Live post table
  - Live delta table
  - my recommendation with reasoning
- `docs/EDGE_FILTERS_RESULTS.md` — extended with new filter outcomes
- Per-filter feature branches: `filter-NN-name` (merged or kept as `archive-filter-NN`)
- Telegram pings via `backend/notify.py` (reuses live trade-notification path)

## Status

Wave 1 launching — filters #5, #6, #7 in parallel branches.
