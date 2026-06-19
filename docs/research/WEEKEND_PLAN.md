# Weekend Plan — 2026-06-13 (Sat) to 2026-06-15 (Sun)

Markets closed. No live signals. No risk in touching things. Use the time
for verification + filter research that's risky during market hours.

## Three goals (in order)

### 1. Full 21-year parity audit (Live ↔ Backtest)

**Why:** The existing `test_22_parity.py` only validates that BT's
signal-gen agrees with Live's signal-gen on the **last 7 days** of data.
This gives a snapshot but not a P&L-relevant answer. We want the bigger
question: across 21 years, do the two code paths produce comparable
trade counts, win rates, and P&L?

**What to measure (per system):**
- Total signal count (BT vs Live-replay)
- Direction agreement % on overlapping signals
- Entry/SL/TP price drift on overlapping signals
- Trade-level P&L deltas (real `execute_trade` fill model on both)
- Winrate, PF, total P&L (full backtest engine numbers)
- Any catastrophic divergences (signals only in one side)

**Scope:** All 4 systems — Gold Macro, Oil Macro, Gold Micro, Oil Micro.

**Method:**
- Live-replay = the live `_run_micro_sweep_core(dry_run=True)` (or Macro
  equivalent) wrapped to walk historical bars and emit signals.
- Backtest = the production `run_backtest()` engine (with `execute_trade` +
  break-even + DD protection + cooldown + one-at-a-time).
- Both produce signal lists; both run through the same fill model for fair
  P&L comparison.
- Output: per-system table of {N, WR, PF, Total P&L, drift%}.

**Lesson from yesterday's Filter A failure:** any custom replay tool that
skips `execute_trade` will give wrong answers. The real backtest engine
is the only valid arbiter for absolute numbers. So:
- Live-replay generates **signals only** (raw signal-gen output)
- Backtest engine generates **trades** (signals + execution + DD + sizing)
- Comparison is at the **signal layer** (count, direction, prices) AND
  the **trade-outcome layer** (re-run BT-engine on Live-replay's signals
  vs BT's own signals)

**Effort:** 1 script, ~150 LOC. Run takes ~5 min/system × 4 = ~20 min.
Plus parity audit interpretation: ~30 min. **Total ~2 hours.**

### 2. Edge filter sweep — 12 untested filters

**Why:** From `project_edge_filters.md` we have 12 filters that have been
designed but never measured. Each may improve PF or may be a no-op. The
"every gate change runs full 21-yr backtest pre/post" rule applies
literally: each filter goes through the real backtest engine, not a
custom replay tool (we re-learned this with Filter A yesterday).

**Filters to test (12):**

Easy (parameter tweaks — 1-line config or kwarg changes):
- **#5** BE 50% → 35% (calibration)
- **#6** Trailing SL after BE (calibration)
- **#7** Partial TP at 50% (calibration)
- **#16** R:R lower bound 0.8 → 1.5 (parameter)

Logic gates (need real code in signal-gen):
- **#2** First-Sweep-of-Day (skip 2nd same-direction sweep)
- **#3** TP Feasibility (time remaining vs ATR pace)
- **#4** Anti-Trend-Extension (>2× ATR move already → skip)
- **#9** R:R Upper Bound 4.0 (skip distant-TP setups)
- **#10** Spread-Inside SL (Oil Macro sl_buffer < spread)
- **#12** Engulfing-of-doji (no prev-body magnitude check)
- **#13** Engulfing wick-vs-body (no upper-wick on bullish check)
- **#14** prev=sweep-bar pollution (skip_first_bar from idx 2)
- **#15** Cooldown bypass (Macro adds _traded_sweeps AFTER execute)

**Note:** #15 is a code-correctness fix, not a "filter" per se — it
fixes a race window. Will benchmark with same pre/post regardless.

**Method per filter:**
1. Branch off `midas-deploy` as `filter-<n>-<name>`
2. Implement (kwarg-gated, default off — same pattern as Filter A)
3. Run `run_backtest(skip_partial_min=...)` baseline + with-filter
4. Compare: trade count, WR, PF, total P&L, by-strategy breakdown
5. If PF improves materially AND total P&L doesn't crater → ship (merge to midas-deploy)
6. If neutral or worse → stash branch (keep in repo as `archive-filter-<n>`)
7. Document outcome in `docs/WEEKEND_RESULTS.md`

**Decision criteria** (what counts as "ship"):
- ✅ **Ship**: PF improves by ≥5%, total P&L within 95% of baseline
- 🟡 **Maybe**: PF improves but P&L drops 5-10% (capital efficiency tradeoff — flag for user)
- ❌ **No-ship**: PF flat/worse, OR P&L drops >10%

**Effort per filter:** ~1 hour (15 min code + 10 min backtest + 30 min analysis + commit/stash).
**Total:** ~12 hours. Realistic to do across 2 days.

### 3. Friday day postmortem

**Why:** Observability v2 was deployed mid-Friday. Logs cover from
~14:30 UTC onwards. We want a comprehensive day postmortem: every
signal fired/skipped, every trade opened/closed, every gate that
triggered, every error.

**Scope:** All 4 systems. Cross-referenced.

**Output sections:**
- **Header**: date range covered, total log lines per service
- **Trades opened/closed** (we already postmortem'd 3: GD-MI-da28460d, GD-MI-0b973d80, OIL-MI-aba3b668 — link them)
- **Signal counts**: fired-and-taken vs fired-and-skipped per system (with skip reasons histogram)
- **Gate rejection histogram**: for each system, count by GATE category
- **Sweeps detected vs sweeps consumed**
- **Errors**: any ERROR/CRIT level lines, any tracebacks
- **Broker activity**: order_placed / order_filled / order_failed counts, retcode distribution
- **Position monitor**: any EXIT_AMBIGUOUS streaks, any CLOSE_FAILED retries
- **Lifecycle**: service start/stop, scheduler heartbeats, daily recon
- **Anomalies**: anything unexpected (orphan adoptions, DD pause armed, etc.)

**Effort:** ~2 hours (heavy log parsing + writeup).

## Order

1. **Parity audit** (today) — confirms baseline is sane before measuring anything
2. **Friday postmortem** (today) — captures live operational picture from yesterday's deployment
3. **Edge filter sweep** (Sun + Mon) — multi-day work; only safe to start once parity confirms healthy baseline

## What we're NOT doing this weekend

- No production code changes outside the filter feature branches
- No live trading (markets closed anyway)
- No major UI work (separate session per user)
- No deploys to VPS (services running, leave them alone)

## Output artifacts

- `docs/WEEKEND_PLAN.md` (this file)
- `docs/WEEKEND_RESULTS.md` (filled as we go)
- `docs/SESSION_2026_06_13.md` (handoff at end of weekend)
- Per-filter feature branches: `filter-<n>-<name>` (merged or kept as `archive-filter-<n>`)
- Updated `docs/EDGE_FILTERS_RESULTS.md` (extended with new entries)
