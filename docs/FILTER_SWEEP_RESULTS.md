# Filter Sweep Results — Live Scoresheet

Companion to `docs/FILTER_SWEEP_PLAN.md`. Filled as each filter completes.

**No fake numbers.** Every BT figure comes from `run_backtest()`; every Live
figure comes from `extract_live_signals` against the actual `_run_*_sweep_core`.

## Decision tracker

| # | Filter | Wave | Status | Branch | BT PF Δ | BT P&L Δ | Live signal Δ | Decision |
|---|---|---|---|---|---|---|---|---|
| 5 | BE 50% → 35% | 1 | ✅ SHIPPED (3/4) | filter-05-be-pct | +0.31 avg (3 sys) | +$179k (3 sys) | n/a (fill-side) | SHIP — Gold Micro, Oil Macro, Oil Micro. Excluded Gold Macro (-$5k). |
| 6 | Trailing SL after BE | 1 | ✅ SHIPPED (1/4) | filter-06-trail-after-be | +0.03 (Oil Macro) | +$80,245 (Oil Macro) | n/a (fill-side) | SHIP — Oil Macro only. Gold Macro / Gold Micro / Oil Micro EXCLUDED. |
| 7 | Partial TP at 50% | 1 | ✅ SHIPPED (4/4) | filter-07-partial-tp | +1.79 avg | +$1,261,109 | n/a (fill-side) | SHIP — Variant A on all 4 systems. No regressions. |
| 16 | R:R lower bound | 2 | ❌ STASHED | archive-filter-16 | varies | -$701k @ 1.5 / -$37k @ 1.0 | n/a (drift-fixed at impl) | STASH — sweep across 0.8/1.0/1.2/1.5 all net negative. Sub-1.5R trades profitable. |
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

## Wave 1 — in progress

### Filter #5 — BE 50% → 35% — ✅ SHIPPED (3 of 4)

Full report: [`filter_results/FILTER_05_BE_PCT.md`](filter_results/FILTER_05_BE_PCT.md)

| System | Decision | Baseline (0.50) | Filter (0.35) | Δ P&L |
|---|---|---|---|---:|
| Gold Macro | **EXCLUDED** | PF 2.56, $346k | PF 2.78, $341k | -$4.9k |
| Gold Micro | ✅ SHIP | PF 2.42, $240k | PF 2.77, $252k | **+$12.0k** |
| Oil Macro | ✅ SHIP | PF 2.66, $646k | PF 2.94, $698k | **+$52.4k** |
| Oil Micro | ✅ SHIP | PF 2.69, $2.01M | PF 3.10, $2.13M | **+$115.0k** |

**Aggregate impact (3 ship systems): +$179,373 / 21 yrs (+$8.5k/yr).**

### Filter #6 — Trailing SL after BE — ✅ SHIPPED (1 of 4)

Full report: [`filter_results/FILTER_06_TRAIL_AFTER_BE.md`](filter_results/FILTER_06_TRAIL_AFTER_BE.md)

| System | Decision | Baseline (no trail) | Filter (trail=0.5) | Δ P&L |
|---|---|---|---|---:|
| Gold Macro | **EXCLUDED** | PF 2.56, $346k | PF 2.54, $341k | -$5.3k |
| Gold Micro | **EXCLUDED** | PF 2.77, $252k | PF 2.70, $249k | -$3.5k |
| Oil Macro | ✅ SHIP | PF 2.93, $701k | PF 2.96, $781k | **+$80.2k** |
| Oil Micro | **EXCLUDED** | PF 3.10, $2.13M | PF 2.87, $2.13M | +$1.9k (PF↓) |

**Aggregate impact (Oil Macro only): +$80,245 / 21 yrs (+$3.8k/yr).**

### Filter #7 — Partial TP at 50% — ✅ SHIPPED (4 of 4)

Full report: [`filter_results/FILTER_07_PARTIAL_TP.md`](filter_results/FILTER_07_PARTIAL_TP.md)

| System | Decision | Baseline | Variant A (partial only) | Δ P&L |
|---|---|---|---|---:|
| Gold Macro | ✅ SHIP | PF 2.56, $346k | PF 3.53, $428k | **+$81.5k (+23.5%)** |
| Gold Micro | ✅ SHIP | PF 2.77, $252k | PF 4.40, $335k | **+$82.4k (+32.7%)** |
| Oil Macro | ✅ SHIP | PF 2.96, $781k | PF 4.70, $826k | **+$45.1k (+5.8%)** |
| Oil Micro | ✅ SHIP | PF 3.10, $2.13M | PF 5.76, $3.18M | **+$1,052k (+49.5%)** |

**Aggregate impact (all 4 systems): +$1,261,109 / 21 yrs (+$60.1k/yr).**

This is the strongest filter result of the sweep. Variant B (partial + BE-arms-on-partial) was tied or marginally worse on 3 of 4 systems; Variant A is the cleaner default. Live wiring (DWX EA partial-close + DB schema migration) is a separate work block — backtest validates the model.

**Cumulative shipped impact (Filters #5 + #6 + #7): +$1,520,727 / 21 yrs (+$72.4k/yr).**


## Wave 2

### Filter #16 — R:R lower bound — ❌ STASHED

Audit-discovered: current floor of 0.8 lets through trades needing ~80% WR to break even.

Sweep across thresholds (21yr × 4 systems × 4 thresholds, total 16 BTs):

| System | rr=0.8 (baseline) | rr=1.0 | rr=1.2 | rr=1.5 |
|---|---|---|---|---|
| Gold Macro | $428k (PF 3.53) | $423k −1.0% (PF 3.57) | $415k −3.1% (PF 3.69) | $363k −15.1% (PF 3.73) |
| Gold Micro | $335k (PF 4.40) | $331k −1.1% (PF 4.45) | $326k −2.8% (PF 4.62) | $279k −16.7% (PF 4.36) |
| Oil Macro | $826k (PF 4.70) | $826k 0% (no-op) | $826k 0% (no-op) | $826k 0% (no-op) |
| Oil Micro | $3.18M (PF 5.76) | $3.15M −0.9% (PF 5.98) | $3.00M −5.7% (PF 6.26) | $2.60M −18.3% (PF 6.62) |
| **Total** | **$4.77M** | $4.73M (−0.8%) | $4.56M (−4.2%) | $4.06M (−14.7%) |

**Decision: STASH all variants.** Hypothesis disproven — sub-1.5R trades are profitable in this strategy. Even rr=1.0 (the marginal case) costs P&L for small PF improvement.

**Oil Macro is structurally immune** — its TP buffer geometry produces ≥1.5R always. Filter is a true no-op there.

Branch archived as `archive-filter-16` (no merge, no live impact).

## Wave 2 (continued) — pending
## Wave 3 — pending
## Wave 4 — pending
