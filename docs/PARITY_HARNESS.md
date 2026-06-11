# Parity Harness — Operator Guide

A measurement tool that quantifies drift between LIVE signal-generation and BACKTEST signal-generation for each of the 4 trading systems. Without this harness, the project has no way to detect when a code change has caused live and backtest to diverge — a class of bug that has hit production 5 times in 3 weeks.

The harness is a soft CI gate: it runs as part of the test suite, fails on **catastrophic** drift, and warns on **minor** drift while writing a JSON artifact for the next person to read.

For the architectural design and rationale, see [PARITY_HARNESS_PLAN.md](PARITY_HARNESS_PLAN.md). This doc is for running the harness and reading its output.

---

## How to run

```bash
cd /Users/subash/SUBASH/GoldDigger

# All 4 systems
python3 -m pytest tests/harness/test_22_parity.py -v

# Single system (faster while debugging)
python3 -m pytest tests/harness/test_22_parity.py -v -k gold_micro

# Custom replay window (default 7 days)
PARITY_DAYS=30 python3 -m pytest tests/harness/test_22_parity.py -v

# Just the gate-logic and diagnosis-hint unit tests (sub-second)
python3 -m pytest tests/harness/test_22_parity.py::TestGateLogic
python3 -m pytest tests/harness/test_22_parity.py::TestDiagnosisHints
```

Total runtime for the 4-system live run: **~25 seconds**.

---

## Output

Each system run writes a JSON artifact to `tests/harness/parity_reports/`:

```
tests/harness/parity_reports/
  parity_<utc_date>_<short_sha>_<system>.json
```

These files are **gitignored** — they're local-only trend data. Stdout always shows a one-line summary plus the artifact path.

Example summary line (Phase 4 baseline):

```
gold_micro: parity=60.0% (BT=5, Live=15, in_both=3, agree=3, disagree=0)
```

Read as: of 5 backtest signals + 15 live signals over the 7-day window, 3 timestamps overlap. All 3 directions match. Parity score 60% (under the 85% warning threshold).

---

## How to read a parity report

### Top-level: parity_pct

The parity_pct is a single number summarizing structural similarity:

```
parity_pct = 0.50 × coverage_ratio
           + 0.30 × direction_agreement_ratio
           + 0.20 × (1 − clamped(avg_entry_price_delta / sweep_threshold, 0, 1))
```

- **Coverage ratio** (50%): of the larger side's signal count, how many timestamps overlap.
- **Direction agreement** (30%): of overlapping signals, how many have the same direction.
- **Entry price drift** (20%): average per-signal entry-price difference, normalized to the system's sweep_threshold.

Why these weights? Coverage is most important because if the systems disagree on WHEN to signal, nothing else matters. Direction is the strategy-LOGIC check. Entry-price drift is execution-detail (slippage, fill model) — important but not strategy-changing.

### Soft-gate thresholds

| State | Trigger | Effect |
|---|---|---|
| **Clean** | parity_pct ≥ 85% AND no direction disagreements | Silent pass |
| **Warning** | parity_pct < 85% OR direction_disagreements > 0 | Pass with warning + JSON artifact |
| **Catastrophic** | parity_pct < 50% OR direction_disagreements > 5 OR (live=0 AND backtest>5) | **pytest fails** — CI blocks |

These gate logic branches are unit-tested in `TestGateLogic` (9 tests covering each branch + boundary cases).

### diffs[] array

Each entry is one (timestamp_minute, direction) bucket where at least one side produced a signal. Fields:

- `in_backtest`, `in_live`: which side produced a signal.
- `direction_match`: bool — meaningful only when both sides present.
- `entry_price_delta`: live − backtest. Positive = live higher.
- `sl_delta`, `tp_delta`: same convention.
- `timestamp_delta_secs`: live − backtest (within minute bucket).
- `bias_match`, `skip_reason_match`: per-record metadata agreement.
- `diagnosis_hint`: human-readable root-cause hint (see below).

### Diagnosis hints (Phase 5)

Each diff carries a `diagnosis_hint` field. Five canonical shapes:

1. **`direction_flipped:bt=long,live=short`** — strategy LOGIC drift on the same minute. Investigate immediately.
2. **`entry_price_delta_exceeds_1_dollars:+2.50`** — both sides took the signal but entry prices diverge by more than $1. Almost always slippage / fill-model.
3. **`timestamp_delta_more_than_180_secs:+240`** — both took the signal but on different M3 bars. Common; live polls every 3min.
4. **`live_skipped_with_reason_backtest_did_not:<reason>`** (or symmetric BT version) — a skip filter fired asymmetrically.
5. **`live_signaled_outside_backtest_window`** (or symmetric BT version) — most common; one side emitted a signal the other didn't see.

`agreement` is the clean case.

---

## When to investigate

### Pass silently → ignore
Parity ≥ 85%, no disagreements. System is healthy.

### Warning → maybe investigate
Open the JSON, look at the `diagnosis_hint` distribution. If it's mostly `live_signaled_outside_backtest_window`, that's the **expected** drift class (live polls every M3 bar; BT walks bars). No action.

If you see `direction_flipped` even once, investigate. That's strategy logic divergence.

If you see `entry_price_delta_exceeds_1_dollars` repeatedly, look at the slippage model — backtest's fill model may have drifted from production.

### Catastrophic → must fix before deploy
The harness fails the build. Read the artifact's `diffs` field, find the systematic cause, fix it, re-run. If the failure is genuine drift (not a harness bug), the fix is on the live or backtest side — figure out which.

### Suspect the harness itself
If parity_pct is exactly 100% on any system, suspect a harness bug — both Micro paths use ~450 lines of duplicate code that have actually drifted historically. Likewise if parity_pct is below 30% with no direction_flipped, the harness is probably bucketing wrong, not the system.

Two canary checks (also in PARITY_HARNESS_PLAN.md "What proves the harness is real"):

1. Run with PARITY_DAYS=7 vs PARITY_DAYS=30 → numbers should be **different**.
2. Edit one config value live-side only (e.g. `sweep_threshold` in `backend-micro/config.py`), re-run → parity should **drop**. Revert.

If either check produces unchanged numbers, the harness has a bug.

---

## v1 baseline (May 19-26 2026, commit `bd481ab`)

This is the first measured baseline. Future runs should be compared against it.

| System | parity_pct | BT | Live | in_both | direction_agreements | direction_disagreements |
|---|---|---|---|---|---|---|
| Gold Micro | **60.0%** | 5 | 15 | 3 | 3 | 0 |
| Oil Micro | **77.0%** | 11 | 11 | 6 | 6 | 0 |
| Gold Macro | **59.9%** | 1 | 5 | 1 | 1 | 0 |
| Oil Macro | **57.4%** | 1 | 6 | 1 | 1 | 0 |

**Headline finding:** All 4 systems show **0 direction disagreements** on overlapping signals. Strategy LOGIC parity is intact across the duplicate code paths. The drift is exclusively in **which bars trigger** — Live emits more signals than BT because it polls every M3 bar; BT walks H1 bars. This pattern matches the analytical estimate of ~70-80% post-TDB-fix in `LIVE_VS_BACKTEST_PARITY.md`.

**Per-system observations:**
- **Oil Micro is the most aligned** (77%) — same total signal count both sides, twice as many overlaps as Gold Micro.
- **Macro systems** show fewer total BT signals because Macro evaluates one Asia window per day. Their parity_pct is lower because the small denominator amplifies single-signal mismatches in the coverage_ratio component.
- **Direction agreement is 100% across the board.** This is the validation that all four duplicate code paths produce equivalent signals when they trigger.

---

## v1.1 baseline (post Phase-0, commit `a5dc3e1` — 2026-06-12)

After shipping Filter #17 (Oil Macro live `risk<0.01` → `risk<0.3` to match backtest). Adversarial canaries also passed.

### Canary results (validating the harness itself)

| Canary | Setup | Expected | Observed | Status |
|---|---|---|---|---|
| **1** PARITY_DAYS sensitivity | 7d vs 30d, gold_micro | Different parity, different signal counts | 60.0% (BT=5, Live=15) vs 59.5% (BT=24, Live=47) | ✅ Pass |
| **2A** Live-only drift, modest | sweep_threshold 2.0 → 3.0 in `backend-micro/config.py` only | Parity drops | 60.0% (unchanged — perturbation insufficient) | ⚠️ Insensitive |
| **2B** Live-only drift, aggressive | sweep_threshold 2.0 → 50.0 in `backend-micro/config.py` only | Parity drops to catastrophic | 60.0% → 20.0%, Live signals 15 → 0 | ✅ Pass |
| **2C** Revert | Restore sweep_threshold = 2.0 | Parity recovers to 60.0% | 60.0% (recovered) | ✅ Pass |

**Canary 2A finding:** All 15 live sweeps had ≥$3 wick extension on the Gold Micro 7d window, so 2.0 → 3.0 didn't filter any. Future drift checks should use perturbations large enough to reach the data distribution.

### Filter #17 effect (oil_macro)

| Window | Pre-fix (`risk<0.01`) | Post-fix (`risk<0.3`) | Δ |
|---|---|---|---|
| 7-day | 57.4% (BT=1, Live=6, in_both=1) | 59.0% (BT=1, Live=5, in_both=1) | +1.6pp, Live -1 |
| 30-day | 64.0% (BT=13, Live=24, in_both=7) | 64.6% (BT=13, Live=23, in_both=7) | +0.6pp, Live -1 |

Direction agreement remained 100% on overlaps both pre and post. The fix removes a trade class that was live-only (10c-30c risk Oil trades) — backtest never simulated those.

### Full v1.1 baseline (7-day, all systems, post Filter #17)

| System | parity_pct | BT | Live | in_both | agree | disagree | Δ vs v1 |
|---|---|---|---|---|---|---|---|
| Gold Micro | 60.0% | 5 | 15 | 3 | 3 | 0 | unchanged |
| Oil Micro | 77.0% | 11 | 11 | 6 | 6 | 0 | unchanged |
| Gold Macro | 59.9% | 1 | 5 | 1 | 1 | 0 | unchanged |
| Oil Macro | **59.0%** | 1 | 5 | 1 | 1 | 0 | **+1.6pp (Filter #17)** |

All systems: 100% direction agreement on overlaps. Build status: passing (with parity-below-85% warnings on all 4 systems — expected, see headline finding above).

### Filter #11 status: deferred

Empirical run-to-run noise on gold_micro was measured at three back-to-back runs:
```
parity=0.599078  avg_delta=0.0092
parity=0.599364  avg_delta=0.0064
parity=0.599710  avg_delta=0.0029
```
~0.07pp noise — invisible at 1-decimal display. The "1-3pp noise" claim from `PARITY_HARNESS_EXPLAINED.md` was overstated. Filter #11 (deterministic slippage) is no longer Phase-0 critical; it moves to Phase 1 where backtest PF comparisons will need higher precision.

---

## What this harness does NOT measure

- **P&L parity.** Slippage, latency, broker rejection, broker-side SL/TP execution differences remain. See `LIVE_VS_BACKTEST_PARITY.md` Gaps 4-8.
- **Order fill timing or fill price.** That's a downstream concern — once the signal exists, this harness considers it produced.
- **Fill-model accuracy.** `tests/harness/test_03_fill_parity.py` covers that.
- **Per-trade P&L outcomes.** `tests/harness/test_12_replay.py` covers replay correctness; we add per-signal precision but stop short of P&L tracking.

---

## How EDGE_FILTERS uses this

The Phase 0 prerequisite for shipping any of the 7 EDGE_FILTERS proposals (`docs/EDGE_FILTERS.md`) is this harness. Workflow:

1. Modify the live signal-gen path to add a new filter (e.g., range-exhaustion).
2. Run the parity harness. Record which signals the new filter caused to skip.
3. Add the same filter to the backtest signal-gen path.
4. Re-run the parity harness. Confirm parity_pct **does not drop** below the v1 baseline — the filter must skip the same signals on both sides.
5. Catastrophic gate failure on this step = the filter is implemented differently in live vs backtest. Fix before shipping.

This is the only way to safely add a filter that touches both code paths.

---

## Implementation files

```
tests/harness/test_22_parity.py    → pytest entry, gate + hint unit tests
tests/harness/parity/
  __init__.py                       → public API
  config.py                         → SYSTEMS dict, per-system metadata
  extractor.py                      → SignalRecord + BT/Live signal extraction
  diff.py                           → SignalDiff + diagnosis_hint
  score.py                          → ParityScore + JSON output
  runner.py                         → run_parity_check() top-level
tests/harness/parity_reports/       → JSON output dir (gitignored)

backend/scanner/scheduler.py        → _run_alpha_sweep_core (Phase 4 add)
backend-oil/scanner/scheduler.py    → _run_alpha_sweep_core (Phase 4 add)
backend-micro/scanner/scheduler.py  → _run_micro_sweep_core (already existed)
backend-oil-micro/scanner/scheduler.py → _run_micro_sweep_core (already existed)
```

The two Macro `_run_alpha_sweep_core` functions are the only production-code edits in the harness work, and they're additive (the existing `_run_alpha_sweep` wrappers preserve the original zero-arg signature).

---

## When to update this doc

- New system added (BTC? Equity?) → add to baseline table.
- Threshold tuning → update Soft-gate section.
- New diagnosis hint shape → add to Diagnosis hints list.
- v2 baseline measured → append a new section, don't overwrite v1.
