# Parity Verification Harness — Implementation Plan

## Context

The Hand of Midas system has live and backtest implementations of the same strategy logic running as **parallel duplicate code**, not shared code. Verified facts from the codebase:

- Live signal-gen: `backend-micro/scanner/scheduler.py:_run_micro_sweep_core()` (lines 166–451), and equivalents in 3 other systems
- Backtest signal-gen: `backend/strategies/micro_alpha_sweep.py:generate_signals()` (lines 95–213) and `backend/strategies/alpha_sweep.py`, called from `backend/backtest/engine.py:run_backtest()` (and the parallel `backend-micro/backtest/engine.py`)
- The two paths duplicate ~450 lines covering: consolidation range, sweep detection, engulfing pattern, bias filter, entry/SL/TP placement
- **5 confirmed drift bugs in the past 3 weeks** (TDB, V1-only bias, schema overflow, BE-ambiguity, OnTradeTransaction dual-instance)
- `docs/LIVE_VS_BACKTEST_PARITY.md` (June 10) is **analytical only** — it explains why drift exists but does not measure it
- `tests/harness/test_12_replay.py` does limited direction-at-hour-granularity comparison for **Gold Micro only**, with tolerant assertions (`if not matching_hours: return`) that hide drift instead of surfacing it

**Why now:** `docs/EDGE_FILTERS.md` proposes 7 strategy enhancements. None can ship safely without a way to verify live and backtest produce the same output for the same input. Without this harness, every filter change is a landmine.

**Goal:** measurable per-signal drift between live and backtest — across all 4 systems — enforced as a **soft CI gate** (catastrophic drift fails the build, nuanced drift reports as warning + JSON artifact).

---

## What this harness IS NOT

- Not a replacement for `test_12_replay.py` (it expands on it; test_12 stays for crash-resistance)
- Not a fix for the duplicate-code problem (~450 lines remain duplicated; this harness measures the consequence)
- Not a guarantee of P&L parity — slippage, latency, fill assumptions remain (see `LIVE_VS_BACKTEST_PARITY.md` Gaps 4–8). It measures **signal-generation** parity only.
- Not a way to run live trades through backtest data — purely a signal-generation comparison

---

## Design

### A. Parity definition

For each (system, date, signal-time) tuple, compare **what live signal-gen produces** vs **what backtest signal-gen produces** for the same input bars.

**Per-side signal record (BT and Live independently):**
```python
@dataclass
class SignalRecord:
    system: str          # "gold_micro" | "oil_micro" | "gold_macro" | "oil_macro"
    timestamp: datetime  # UTC, exact bar timestamp
    direction: str       # "bullish" | "bearish"
    taken: bool
    skip_reason: str     # "" if taken; otherwise the gate's reason code
    entry_price: float | None
    sl_price: float | None
    tp_price: float | None
    sweep_wick: float | None
    sweep_dir: str | None
    bias: str            # "bullish" | "bearish" | "neutral"
    range_high: float
    range_low: float
```

**Per-signal diff record:**
```python
@dataclass
class SignalDiff:
    system: str
    timestamp: datetime
    in_backtest: bool
    in_live: bool
    direction_match: bool
    entry_price_delta: float | None     # live - backtest, None if not in both
    sl_delta: float | None
    tp_delta: float | None
    timestamp_delta_secs: int | None    # 0 if same bar; positive if live later
    bias_match: bool
    skip_reason_match: bool             # both same string OR both empty
    backtest_record: SignalRecord | None
    live_record: SignalRecord | None
    diagnosis_hint: str                 # human-readable root-cause hint
```

### B. Parity score

**Aggregate per (system, date_range):**
```python
@dataclass
class ParityScore:
    system: str
    date_range: tuple[date, date]
    total_signals_backtest: int
    total_signals_live: int
    signals_in_both: int
    signals_only_in_backtest: int
    signals_only_in_live: int
    direction_agreements: int           # of signals_in_both
    direction_disagreements: int
    avg_entry_price_delta: float
    max_entry_price_delta: float
    avg_timestamp_delta_secs: float
    skip_reason_histogram_backtest: dict[str, int]
    skip_reason_histogram_live: dict[str, int]
    parity_pct: float
```

**Parity percentage formula:**
```
parity_pct = (
    0.50 * (signals_in_both / max(total_signals_backtest, total_signals_live, 1))
  + 0.30 * (direction_agreements / max(signals_in_both, 1))
  + 0.20 * (1 - clamped(avg_entry_price_delta / sweep_threshold, 0, 1))
)
```

Weights:
- 50% — does the signal exist on both sides
- 30% — when both have signals, do directions agree
- 20% — entry price drift, normalized to per-system `sweep_threshold`

The formula is published in the harness output so future tuning is explicit, not hidden.

### C. Soft-gate thresholds (hybrid)

| Failure type | Trigger | Effect |
|---|---|---|
| **Catastrophic** | `parity_pct < 0.50` OR `direction_disagreements > 5` OR (`total_signals_live == 0` AND `total_signals_backtest > 5`) | pytest FAILS — CI blocks |
| **Warning** | `parity_pct < 0.85` OR `direction_disagreements > 0` | pytest passes with warning printed; JSON artifact still written |
| **Pass** | none of the above | pytest passes silently |

Defaults are conservative starting points. Tune after first 2–3 real runs reveal real-world numbers per system.

### D. File layout (new files only)

```
tests/harness/
  test_22_parity.py              # pytest entry — 4 parametrized cases
  parity/
    __init__.py
    config.py                    # SYSTEMS dict (per-system module paths, configs, data files)
    extractor.py                 # BT path output → list[SignalRecord]
                                 # Live path replay → list[SignalRecord]
    diff.py                      # two SignalRecord lists → list[SignalDiff]
    score.py                     # list[SignalDiff] → ParityScore + JSON serialization
  parity_reports/                # local-only output dir, gitignored
    .gitkeep
    parity_<utc_date>_<short_sha>_<system>.json
```

### E. Per-system config (the only system-aware part)

```python
SYSTEMS = {
    "gold_micro": {
        "live_module": "backend-micro.scanner.scheduler",
        "live_core_fn": "_run_micro_sweep_core",
        "backtest_module": "backend.strategies.micro_alpha_sweep",
        "backtest_fn": "generate_signals",
        "data_files": ("XAU_USD_H1.csv", "XAU_USD_M3.csv", "XAU_USD_D.csv"),
        "config_module": "backend-micro.config",
        "strategy_config_key": "MICRO_ALPHA_SWEEP",
    },
    "oil_micro": {
        "live_module": "backend-oil-micro.scanner.scheduler",
        "live_core_fn": "_run_micro_sweep_core",
        "backtest_module": "backend.strategies.micro_alpha_sweep",   # shared backtest module, oil config
        "backtest_fn": "generate_signals",
        "data_files": ("BCO_USD_H1.csv", "BCO_USD_M3.csv", "BCO_USD_D.csv"),
        "config_module": "backend-oil-micro.config",
        "strategy_config_key": "MICRO_ALPHA_SWEEP",
    },
    "gold_macro": {
        "live_module": "backend.scanner.scheduler",
        "live_core_fn": "_run_alpha_sweep",      # different name; verify exists with dry_run
        "backtest_module": "backend.strategies.alpha_sweep",
        "backtest_fn": "generate_signals",
        "data_files": ("XAU_USD_H1.csv", "XAU_USD_M3.csv", "XAU_USD_D.csv"),
        "config_module": "backend.config",
        "strategy_config_key": "ALPHA_SWEEP",
    },
    "oil_macro": {
        "live_module": "backend-oil.scanner.scheduler",
        "live_core_fn": "_run_alpha_sweep",
        "backtest_module": "backend.strategies.alpha_sweep",
        "backtest_fn": "generate_signals",
        "data_files": ("BCO_USD_H1.csv", "BCO_USD_M3.csv", "BCO_USD_D.csv"),
        "config_module": "backend-oil.config",
        "strategy_config_key": "ALPHA_SWEEP",
    },
}
```

(Module paths use Python module notation — actual import resolution will be confirmed during Phase 1.)

### F. Per-system flow

```
1. Load CSVs (H1, M3, D) via existing backend/data/cache.py:load_candles()
2. Pick date range (default: last 30 days of data)
3. BACKTEST path:
   a. Call <backtest_module>.generate_signals(h1_df, m3_df, daily_bias)
   b. Convert returned Signal objects → list[SignalRecord]
4. LIVE path (replay):
   a. Reset module-level state (_traded_sweeps, _daily_state, _startup_cooldown_until)
   b. For each M3 bar in date range:
      - Call <live_core_fn>(now=bar_ts, ..., dry_run=True)
      - Extract signals + skip-reason from gd_signals mock
   c. Convert mock-DB signal records → list[SignalRecord]
5. Diff pass:
   a. For each unique (timestamp_floor_to_minute, direction) tuple → look up in BT and Live
   b. Produce list[SignalDiff]
6. Score pass:
   a. Aggregate diffs → ParityScore
7. Output:
   a. JSON artifact: tests/harness/parity_reports/parity_<date>_<sha>_<system>.json
   b. Stdout summary line: "<system>: parity 91.3% (BT=42, Live=39, agreed=37, disagree=2)"
   c. Apply soft-gate thresholds → pytest pass/warn/fail
```

### G. What pytest sees

`tests/harness/test_22_parity.py`:
```python
import pytest
from .parity import run_parity_check, SYSTEMS

@pytest.mark.parametrize("system_key", list(SYSTEMS.keys()))
def test_parity(system_key, capsys):
    score = run_parity_check(system_key, days=30)
    artifact_path = score.write_json()

    summary = (f"{system_key}: parity={score.parity_pct:.1%} "
               f"(BT={score.total_signals_backtest}, Live={score.total_signals_live}, "
               f"agreed={score.direction_agreements}, disagree={score.direction_disagreements})")
    print("\n" + summary)
    print(f"  artifact: {artifact_path}")

    # Catastrophic gate
    catastrophic = (score.parity_pct < 0.50
                    or score.direction_disagreements > 5
                    or (score.total_signals_live == 0 and score.total_signals_backtest > 5))
    if catastrophic:
        pytest.fail(f"CATASTROPHIC parity failure for {system_key}: {summary}")

    # Warning gate (passes but flagged)
    if score.parity_pct < 0.85 or score.direction_disagreements > 0:
        print(f"  WARNING: parity below threshold (target 85%, disagreements should be 0)")
```

Runs as 4 parametrized cases. Total runtime target: **<60s** for the 4-system run on 30 days of data.

### H. JSON artifact shape

`tests/harness/parity_reports/parity_2026-06-11_a45efd3_gold_micro.json`:
```json
{
  "system": "gold_micro",
  "generated_at": "2026-06-11T...Z",
  "git_sha": "a45efd3",
  "date_range": ["2026-05-12", "2026-06-11"],
  "data_files": ["XAU_USD_H1.csv", "XAU_USD_M3.csv", "XAU_USD_D.csv"],
  "parity_score": {
    "parity_pct": 0.913,
    "total_signals_backtest": 42,
    "total_signals_live": 39,
    "signals_in_both": 37,
    "direction_agreements": 37,
    "direction_disagreements": 0,
    "skip_reason_histogram_backtest": {"range_min_too_small": 12, "no_engulfing": 8},
    "skip_reason_histogram_live": {"range_min_too_small": 11, "no_engulfing": 9}
  },
  "diffs": [
    {
      "timestamp": "2026-05-15T11:00:00Z",
      "in_backtest": true,
      "in_live": false,
      "direction": "bearish",
      "backtest_record": { ... full SignalRecord ... },
      "live_record": null,
      "diagnosis_hint": "live_skipped_with_reason_no_engulfing"
    }
  ]
}
```

The `diagnosis_hint` is computed during diffing — heuristics like "live skipped with reason X but backtest didn't" go here, to make root-causing fast.

---

## Critical files

**New (only files to create):**
- `tests/harness/test_22_parity.py` — pytest entry with 4 parametrized cases
- `tests/harness/parity/__init__.py`
- `tests/harness/parity/config.py` — `SYSTEMS` dict
- `tests/harness/parity/extractor.py` — `SignalRecord` extraction from BT and Live
- `tests/harness/parity/diff.py` — `SignalDiff` computation
- `tests/harness/parity/score.py` — `ParityScore` + JSON serialization
- `tests/harness/parity_reports/.gitkeep`
- Append `tests/harness/parity_reports/*.json` to `.gitignore`

**Reused (no edits — read patterns from these):**
- `backend/data/cache.py` — `load_candles()` for CSV inputs
- `tests/harness/test_12_replay.py` — `replay_day()`, `build_candle_dicts()` patterns
- `tests/harness/conftest.py` — `mock_db`, `mock_mt5` fixtures
- `backend-micro/scanner/scheduler.py:_run_micro_sweep_core()` — live entry (already supports `dry_run=True`)
- `backend/strategies/micro_alpha_sweep.py:generate_signals()` — backtest entry
- Equivalents for the 3 other systems (verify exact module paths during Phase 1)

**No edits to production code.** This is purely a measurement harness.

---

## Implementation order (6 phases, each runnable)

### Phase 1 — Skeleton + Gold Micro only
- Create `tests/harness/parity/` directory + skeleton files
- Implement `SystemConfig` for `gold_micro` only
- `extractor.py` for Gold Micro: BT path returns `Signal` objects (already typed); Live path produces dicts via existing `_run_micro_sweep_core(dry_run=True)` + mocked DB; both convert to `SignalRecord`
- Minimal `diff.py` and `score.py`
- `test_22_parity.py` parametrized over `["gold_micro"]` only
- Run on **7 days of data** (the same fixture window `gold_7d_h1` already used by test_12)
- **Acceptance:** test runs in <30s, produces a JSON artifact, prints parity %

### Phase 2 — Soft-gate thresholds + warning behavior
- Add catastrophic + warning thresholds to `test_22_parity.py`
- Verify behavior with intentional drift (e.g. delete a backtest signal in extractor → catastrophic; flip one direction → warning)
- **Acceptance:** harness fails build only on catastrophic conditions

### Phase 3 — Add Oil Micro
- Add `oil_micro` to `SYSTEMS` config
- Reuse same code path; only data files + module names differ
- **Acceptance:** Oil Micro parity reported alongside Gold Micro; test_22 runs both

### Phase 4 — Add both Macro systems (architectural variance)
- Macro live path is `_run_alpha_sweep` (different name, single Asia window not rolling)
- Audit assumption: does `_run_alpha_sweep` accept `dry_run=True`? If not, **before** implementing the harness, add the parameter as a read-only refactor (default False) and verify the existing scheduler tests still pass. This is the only production-code edit allowed in this whole plan, and only if needed
- Adapter logic in `extractor.py` to handle Macro's window-state differences
- **Risk:** Macro might surface assumptions in `extractor.py` that need refactoring. If so, split this phase into 4a (assumption audit) + 4b (impl)
- **Acceptance:** all 4 systems run in <60s total

### Phase 5 — Diagnosis hints
- Implement `diagnosis_hint` field on `SignalDiff` with these initial heuristics:
  1. `live_skipped_with_reason_X_backtest_did_not`
  2. `entry_price_delta_exceeds_X_dollars`
  3. `timestamp_delta_more_than_3min`
  4. `direction_flipped`
  5. `live_signaled_outside_backtest_window`
- **Acceptance:** every diff has a non-empty hint; hints are human-readable

### Phase 6 — Documentation + integration
- Write `docs/PARITY_HARNESS.md` — how to run, how to read reports, when to investigate vs ignore
- Update `docs/EDGE_FILTERS.md` to reference this harness as the now-ready Phase 0 prerequisite
- Update `CLAUDE.md` to mention `test_22_parity.py` exists
- Update `.gitignore` for `tests/harness/parity_reports/*.json`
- Run the harness on production data once and **record the v1 baseline numbers** (one parity_pct per system) in `docs/PARITY_HARNESS.md`. Future regressions are measured against this baseline
- **Acceptance:** Subash can run `pytest tests/harness/test_22_parity.py -v` and understand the result

---

## Verification

### How to verify the harness works end-to-end

1. **Local smoke test (Phase 1 acceptance):**
   ```bash
   cd /Users/subash/SUBASH/GoldDigger
   python3 -m pytest tests/harness/test_22_parity.py -v -k gold_micro
   ```
   Expected: passes in <30s, prints `gold_micro: parity=XX.X% (BT=N, Live=M, ...)`, writes a JSON artifact in `tests/harness/parity_reports/`.

2. **Verify catastrophic gate (Phase 2 acceptance):**
   - Temporarily edit `extractor.py` Gold Micro BT extractor to drop every other signal (force big mismatch)
   - Re-run pytest → must FAIL with `CATASTROPHIC parity failure`
   - Revert edit → must pass again

3. **Verify warning gate (Phase 2 acceptance):**
   - Temporarily edit one direction value in BT extractor output
   - Re-run pytest → must PASS but emit a warning
   - Revert

4. **Full 4-system run (Phase 4 acceptance):**
   ```bash
   python3 -m pytest tests/harness/test_22_parity.py -v
   ```
   Expected: 4 parametrized cases pass in <60s total. JSON artifacts written for all 4 systems.

5. **JSON artifact sanity (Phase 6 acceptance):**
   ```bash
   python3 -m json.tool tests/harness/parity_reports/parity_*_gold_micro.json | less
   ```
   - Verify `diffs` field is populated
   - Verify `diagnosis_hint` is non-empty for each diff
   - Verify `parity_score.signals_in_both` equals the count of diffs where both `in_backtest` and `in_live` are true

6. **Document v1 baseline:**
   - First successful 4-system run produces 4 parity_pct numbers
   - Record those in `docs/PARITY_HARNESS.md` as the **as-of-2026-06-XX baseline**

### What proves the harness is real (not vibes)

- The harness must produce a **different** parity_pct when given **different** input bars (e.g. last 7 days vs last 30 days). If parity is identical for any input, the harness isn't actually measuring anything.
- The harness must produce a **different** parity_pct when one duplicate code path is intentionally edited (e.g. change `sweep_threshold` in live config but not backtest). This is the canary for the harness's own correctness.
- The first run's parity_pct must be **plausible** — between 50% and 95% based on `LIVE_VS_BACKTEST_PARITY.md`'s analytical estimate of ~70-80% post-TDB-fix. A 100% score is suspicious; a sub-30% score is also suspicious. Either suggests a harness bug.

If any of these checks fails, the harness has a bug — not the system under test.

---

## Open questions deferred to implementation

1. Does `_run_alpha_sweep` (Macro) accept `dry_run=True`? If not, Phase 4 starts with adding it (additive, default False).
2. Is `daily_bias` computed identically between live and backtest, or only on the backtest side via `_get_cached_data()`? Phase 1 will surface this.
3. Should the harness run on all 4 systems even when only one changed? Default: yes, but reconsider if total runtime exceeds 90s.
4. Retention policy for `parity_reports/` artifacts: gitignored, kept locally for ~90 days, no long-term archival in this scope.

These get resolved when implementation hits them — not predicted in advance.
