# Phase 0 — Live ↔ BT Signal Parity Baseline

**Date:** 2026-06-19
**Window:** Jun 11-18, 2026
**Data source:** JustMarkets MT5 (`data/raw/{XAU,BCO}_USD_{D,H1,M3}.csv`)
**BIAS_MODE:** neutral (matches live VPS state — `GOLD_MICRO_BIAS_MODE=neutral`, `OIL_MICRO_BIAS_MODE=neutral`)

---

## Scope

Per [DECISION_2026-06-19_DROP_MACROS.md](DECISION_2026-06-19_DROP_MACROS.md): Macros dropped from refactor scope. Phase 0 covers only **Gold Micro + Oil Micro**.

**Insurance walks** (M3 OHLC ground-truth checks) completed for both systems before this baseline:
- Gold Micro Jun 17 02:15 SHORT — reconciled exact (F27 limit + plain SL)
- Oil Micro Jun 17 04:18 SHORT — reconciled exact (F27 + F7 partial + F5 BE_SL)

BT mechanics confirmed genuine. **BT-as-oracle for refactor is sound.**

---

## Method

The plan asked for "BT signals vs live dry_run signals." Initial run mistakenly compared **BT trades (post-execution-loop) vs live signals (pre-execution)** — apples-to-oranges, made live look 2x BT.

Re-ran apples-to-apples: **BT signal universe (`generate_signals` output, pre-execution, deduped by `(timestamp, direction)`) vs live dry_run signals.** This is the real strategy-logic parity test.

- **0.1 BT signals**: called each strategy's `generate_signals(h1_df, m3_df, neutral_bias_dict)` directly. Captured pre-execution-loop signal list. Filtered to Jun 11-18 window. Deduped overlapping-window duplicates by `(ts, dir)` — matches what live's global dedup keying does at the cron layer. Saved as `scripts/output/baseline_bt_signals_<system>.json`.
- **0.2 Live dry_run signals**: replayed Jun 11-18 in 3-min ticks through each scheduler's `_run_micro_sweep_core(..., dry_run=True)`. Mocked the 4 DB call sites (no positions, no recent-signal cooldown, no daily cap, no MT5 lock) so each tick fires fresh. Saved as `scripts/output/baseline_live_signals_<system>.json`.
- **0.3 Diff**: matched by `(timestamp ± 2min, direction)`. 2min tolerance because both sides use M3 bar boundaries — should be exact or off by at most 1 bar. Saved per system as `scripts/output/baseline_parity_<system>.txt`.
- **0.4 Counts**: this document.

**Reproducer scripts:**
- `scripts/phase0_dry_run.py` — runs live `_run_*_core(dry_run=True)` replay
- `scripts/phase0_bt_signal_universe.py` — pulls BT `generate_signals()` output
- `scripts/phase0_signal_diff.py` — apples-to-apples diff

---

## Results — apples-to-apples (signal universe vs live dry_run)

### Gold Micro

| Bucket | Count |
|---|---|
| BT signal universe (raw, with overlap-window duplicates) | 46 |
| BT signal universe (deduped by ts+dir) | **34** |
| Live dry_run signals | **37** |
| Matched (±2min, same direction) | **31** |
| BT-only | 3 |
| Live-only | 6 |

**Match rate (BT view)**: 31/34 = **91.2%**
**Match rate (Live view)**: 31/37 = **83.8%**

#### BT-only (BT fires, live doesn't)
```
2026-06-15 06:36 SHORT entry=4325.76 sl=4333.12
2026-06-17 02:15 SHORT entry=4335.97 sl=4340.97
2026-06-17 09:12 LONG  entry=4329.66 sl=4318.59
```

#### Live-only (live fires, BT doesn't)
```
2026-06-11 03:39 LONG  entry=4073.00 sl=4034.23
2026-06-11 05:18 LONG  entry=4092.16 sl=4050.31
2026-06-12 03:27 SHORT entry=4220.35 sl=4232.50
2026-06-12 21:45 SHORT entry=4225.62 sl=4237.48
2026-06-15 21:36 LONG  entry=4325.81 sl=4316.28
2026-06-16 03:45 LONG  entry=4312.81 sl=4304.99
```

### Oil Micro

| Bucket | Count |
|---|---|
| BT signal universe (raw) | 30 |
| BT signal universe (deduped) | **20** |
| Live dry_run signals | **20** |
| Matched (±2min, same direction) | **18** |
| BT-only | 2 |
| Live-only | 2 |

**Match rate (BT view)**: 18/20 = **90.0%**
**Match rate (Live view)**: 18/20 = **90.0%**

#### BT-only
```
2026-06-15 17:33 LONG  entry=82.1453 sl=81.7050
2026-06-17 04:18 SHORT entry=79.0745 sl=79.5250
```

#### Live-only
```
2026-06-11 04:18 SHORT entry=93.516 sl=94.39
2026-06-15 12:39 LONG  entry=82.664 sl=81.855
```

---

## Trade-level (post-execution-loop) — for context only, not parity test

These numbers were the original "diff" run before the apples-to-apples correction. They compare BT TRADES (post one-at-a-time, daily-cap, F27 fill, DD-pause) vs live signals. They look bad because they're comparing two different layers, but they're useful as a "what happens after gates" reference.

| System | BT trades | Live dry_run signals | Matched (±6min) |
|---|---|---|---|
| Gold Micro | 18 | 37 | 15 |
| Oil Micro | 12 | 20 | 10 |

The 18→34 / 12→20 gap = signals that BT's execution loop drops via cap/cooldown/blocker. NOT a parity bug. After refactor, live's gates will drop the same way.

---

## Interpretation

**Pre-refactor signal-universe parity:**
- Gold Micro: **91% / 84%** (BT-view / Live-view)
- Oil Micro: **90% / 90%**

**~10% gap in both systems.** Cross-references to [MASTER_RCA_LIVE_BT_PARITY.md](MASTER_RCA_LIVE_BT_PARITY.md) smoking guns:

| System | Likely root causes for the 10% gap |
|---|---|
| Gold Micro | D3 (window-iteration cadence: live polls active windows on 3-min cron, BT walks every H1 bar across all 12 windows), D4 (dedup keying: live `(bar_ts, sweep_dir)` global vs BT `(bar_ts, start_hour)` per-window) |
| Oil Micro | D2 (rolling-window iteration), D5 (dedup keying), D9 (hardcoded `range(2, ...)`) |

After Phase 4-5 refactor (live calls BT's `generate_signals` directly):
- D3/D4 (Gold) and D2/D5/D9 (Oil) all collapse — same code path, same dedup, same iteration order.
- Match rate should jump 91% → ~99%. Last 1% = real-time vs historical edge cases (cron tick can catch a sweep mid-bar that BT's at-bar-close walk doesn't).

**This 91/90% baseline is the "before" picture.** Post-refactor harness should report >99% from both views.

---

## Caveats

**1. Dedup keying (BT-side).** BT's raw `generate_signals` output lists the same engulfing multiple times when overlapping rolling windows detect the same sweep (Gold Micro 46→34 = 12 duplicates, Oil 30→20 = 10 duplicates). I deduped by `(ts, dir)` to match what live's global dedup does at the cron layer. Without this dedup, BT would look like it fires more signals than live, which would be a misread.

**2. Mocked DB state in dry_run.** Live dry_run replays with NO open positions, NO recent-signal cooldown, NO daily cap, NO MT5 lock. Real live (with non-empty DB) fires FEWER signals than dry_run. **This is acceptable** because Phase 0 measures strategy-logic divergence, not production-gate effects. Gates wrap the call; they don't replace it.

**3. Tolerance ± 2 minutes.** Both sides use M3 bar boundaries — exact match should be the norm; off-by-one M3 bar (3 min) is the realistic worst case. 6min tolerance from the initial diff was too loose and let cross-bar mismatches slip through as "matched."

**4. Live-only signals are not necessarily real new edge.** Many of the 6 Gold live-only signals look like sweeps detected by live's cron polling at slightly different bar boundaries than BT's bar-close walk. After refactor, these collapse into the matched set.

---

## What "done" looks like post-refactor

The same 3 scripts (`phase0_dry_run.py`, `phase0_bt_signal_universe.py`, `phase0_signal_diff.py`) re-run on the refactored code should produce:

- Gold Micro: 34/34 BT = 34/34 Live = 100% match rate (or 33/34 if 1 signal differs by exactly 1 M3 bar at a window boundary edge case)
- Oil Micro: 20/20 BT = 20/20 Live = 100% match rate

**Phase 0 baseline must be regenerated and committed AFTER each refactor phase** to show drift trending toward zero. If a phase regresses parity (match rate drops vs prior baseline), that phase is not done.

---

## Files generated

```
scripts/output/baseline_bt_signals_gold_micro.json
scripts/output/baseline_bt_signals_oil_micro.json
scripts/output/baseline_live_signals_gold_micro.json
scripts/output/baseline_live_signals_oil_micro.json
scripts/output/baseline_parity_gold_micro.txt
scripts/output/baseline_parity_oil_micro.txt
docs/30-day-challenge/reports/PARITY_BASELINE.md   ← this file
```
