# Filter #28 — Vigilant Audit Backlog

**Audit date:** 2026-06-18
**Auditor:** Sherlock-mode code audit (general-purpose agent)
**Scope:** Filter #28 (`bias_mode` kill switch) shipped to `midas-deploy` at `6728f46` — config layer, scheduler logic, BT engines, routes, frontend, parity harness.
**Branch state at audit:** `midas-deploy` includes 5 F28 commits: `a4eb076` (Path A) → `60222e3` (Path B) → `17ecaa8` (multi-seed) → `99e3632` (DD/Sharpe/MC) → `6728f46` (Phase 3 live wiring).
**Live state at audit:** All 4 services on VPS pulled F28 code. Default `BIAS_MODE="production"`. **No system flipped to neutral yet.** Audit blocks first flip.

---

## Framework — VERIFY → RCA → FIX → TEST

(Same framework as `[[feedback-bug-fix-framework]]` used for F27 audit. Each item has 4 sections to fill in as it's worked.)

```
1. VERIFY:  Confirm 100% the issue is real. Reproduce or grep for evidence.
2. RCA:     Root-cause why it exists. Be vigilant — sometimes audit framing is wrong.
3. FIX:     Implement; show diff before commit.
4. TEST:    Add structural + runtime tests; full suite green; explain coverage.
```

Lifecycle markers used in this doc:
- ⏸ pending
- 🟡 in progress
- ✅ done (with date + commit SHA)
- ❌ not shipped (rejected after VERIFY/RCA)

---

## Severity Distribution

| Tier | Count | Description |
|---|---|---|
| **CRITICAL** | 1 | Blocks ship. Frontend kill-switch is invisible, contradicting F28's safety guarantee. |
| **HIGH** | 4 | Should fix before flipping any system to neutral. Each creates a "live trades but I can't tell" risk. |
| **MEDIUM** | 5 | Should fix before second system flips. Operational/observability gaps. |
| **LOW** | 4 | Cosmetic / style / future-maintainability. Fix in cleanup window. |
| **INFO** | 3 | Documentation / test-coverage observations. No code change strictly required, but worth noting. |
| **TOTAL** | **17** | |

---

## Filter #28 lifecycle reminder

```
✅ Path A — discovery (+$3.58M / 21yr)
✅ Path B — shippable kwarg (matches Path A exactly)
✅ Multi-seed (5 seeds × 4 systems × 21yr) — CV 0.9%, 419/420 yearly cells positive
✅ DD stress + Sharpe + Monte Carlo — all 4 systems pass
✅ Phase 3 — live wiring (env var + heavy logs + state endpoint + UI badge)
✅ Merged to midas-deploy + pushed
✅ VPS deploy verified DORMANT (default = production, no behavior change)
🟡 Audit backlog (this doc) — 17 items
⏸ Per-system live flip (one at a time, 5-7 days observation each)
```

---

# CRITICAL (1)

### C1 — Stream endpoints don't surface `bias_mode`; frontend badge invisible for Gold Macro + Oil Macro ✅ (2026-06-18)

**Files:**
- `backend/routes/stream.py:159-231` (Gold Macro)
- `backend-oil/routes/stream.py:156-226` (Oil Macro)

**Audit finding:**
The frontend Live page consumes the SSE stream (`useLiveStream`) which calls a separate `_build_state()` for Gold Macro and Oil Macro services. **`bias_mode` is NOT in either `_build_state()` return dict** — only the REST `/state` route adds it. (Gold Micro and Oil Micro stream.py call `routes.state.get_state()` directly so they are fine.)

**Why this is CRITICAL:**
Operator opens the dashboard, sees no F28 badge — but env var may be set on VPS and live trading is in neutral mode. **Direct contradiction of F28's "kill switch is observable" guarantee.** This is the "live trades but I can't tell" failure mode that F28 was built to prevent.

**VERIFY:** ✅
Confirmed `grep "bias_mode" backend/routes/stream.py backend-oil/routes/stream.py` returned ZERO matches before fix. Found Macro stream.py files have own `_build_state()` implementations (lines 159, 156). Confirmed Micro/Oil-Micro `stream.py` correctly delegate to `routes.state:get_state()` so they inherit the Phase 3 fix and need NO patch.

**RCA:** ✅
Phase 3 wiring (commit 6728f46) touched `backend/routes/state.py` and 3 system mirrors for the REST `/state` endpoint. **`backend/routes/stream.py` and `backend-oil/routes/stream.py` are SEPARATE SSE-stream code paths with their own `_build_state()` functions** — duplicate code that drifted. Same class of bug as `[[bug-dwx-ea-dual-source]]` — duplicate code paths drift unless both are touched together. The Micro variants escaped because they delegate via `from routes.state import get_state`.

**FIX:** ✅ (commit pending)
- `backend/routes/stream.py:222-247` — Added `"bias_mode": _get_bias_mode_safe()` to return dict + new `_get_bias_mode_safe()` helper that wraps `from backend.config import BIAS_MODE` in try/except, defaulting to "production" on failure
- `backend-oil/routes/stream.py:225-247` — Same pattern, but `from config import BIAS_MODE` (service-relative path)

**TEST:** ✅ — `tests/test_filter_28_audit.py` (10 tests pass)
- `test_c1_macro_stream_includes_bias_mode_in_return_dict` (×2 Macro systems) — return dict has `"bias_mode"` key
- `test_c1_macro_stream_has_get_bias_mode_safe_helper` (×2 Macro systems) — helper defined + defaults to "production"
- `test_c1_micro_stream_delegates_to_state_get_state` (×2 Micro systems) — REGRESSION GUARD: if anyone duplicates build-state logic into Micro stream.py, this fails and forces them to add explicit bias_mode handling
- `test_c1_state_includes_bias_mode_in_return_dict` (×4 systems) — verifies Phase 3 fix hasn't regressed

---

# HIGH (4)

### H1 — `BIAS_MODE` env var whitespace/case-fragile (regression of LIMIT_DRY_RUN H1 lesson) ✅ (2026-06-18)

**Files:** All 4 configs + scheduler override blocks
- `backend/config.py:28`, scheduler.py:553
- `backend-micro/config.py:21`, scheduler.py:241
- `backend-oil/config.py:25`, scheduler.py:239
- `backend-oil-micro/config.py:21`, scheduler.py:203

**Audit finding:**
Raw string-equality check `if _bias_mode_cfg == "neutral":`. Silently ignores all of: trailing space, `"NEUTRAL"`, `"Neutral"`, `"true"`, `"1"`, `"yes"`. Env var with whitespace → silent fall-through to production.

**Why this is HIGH:**
**Identical regression to F27 audit's H1 bug** (`backend/execution/limit_price.py:35-108` — that file has `parse_dry_run_env()` for exactly this reason). F28 didn't reuse the lesson. Operator wires `GOLD_MACRO_BIAS_MODE=neutral ` (trailing space, copy-paste from chat). Service starts. F28 silently never activates. The journal logs `mode=production` so even SQL forensics will agree with the misleading state.

**VERIFY:** ✅
Reproduced bug locally: `os.environ['GOLD_MACRO_BIAS_MODE'] = 'neutral '` (trailing space) → raw `os.getenv()` returns `'neutral '` → `val == "neutral"` is False → silent fall-through to production. Same for `'NEUTRAL'` (uppercase). Confirmed all 4 configs used raw `os.getenv()`. Reference pattern confirmed: `backend/execution/limit_price.py:47-108` has `parse_dry_run_env()` for the LIMIT_DRY_RUN H1 fix from F27.

**RCA:** ✅
Phase B already had `resolve_bias_mode()` in `backend/backtest/neutral_bias.py:53-70` — handles `None`/"production"/"neutral" correctly and raises on typos (BT-kwarg path). **Phase 3 wiring (commit 6728f46) didn't reuse that helper** — used raw `os.getenv()` in 4 configs. Same exact regression class as F27 audit's H1 (LIMIT_DRY_RUN). Lesson didn't propagate — every new env-var-driven config knob must use a normalizing parser.

**Why fail-open (warn + default), not fail-closed (raise) for env-var path:** service startup must not crash on a misspelled `.env` line. Default = "production" = the safe state. If user types `NEUTRAL` (case), normalize. If they type `neutrol` (typo), warn loudly and keep production.

**FIX:** ✅ (commit pending)
- `backend/backtest/neutral_bias.py:73-129` — Added `parse_bias_mode_env(env_var_name, default)`:
  - Strips whitespace, lowers case
  - Matches against `_VALID_BIAS_MODE_VALUES = {"production", "neutral"}`
  - Returns `default` for: unset / empty / whitespace-only / unrecognized
  - **Logs WARNING via `logging.warning()` for unrecognized values** so operator sees the problem in service logs
  - Raises `ValueError` if **caller** passes invalid `default` (function-author bug, not env-var bug)
- 4 configs updated to use `parse_bias_mode_env(env_var_name, default="production")` instead of raw `os.getenv()`. All 4 configs verified to load successfully and default to "production".

**TEST:** ✅ — `tests/test_filter_28_audit.py` (19 H1 tests pass)
- `test_h1_parse_bias_mode_env_helper_exists` — function importable
- `test_h1_parse_handles_trailing_whitespace` — `"neutral "` → "neutral"
- `test_h1_parse_handles_leading_whitespace` — `" neutral"` → "neutral"
- `test_h1_parse_handles_case_variants` (×7 parametrized) — `NEUTRAL/Neutral/nEuTrAl/PRODUCTION/Production/neutral/production` all normalize correctly
- `test_h1_parse_typo_falls_back_to_default` — `"neutrol"` → "production" + WARNING log captured
- `test_h1_parse_unrelated_string_falls_back` (×8 values) — `"true", "false", "yes", "1", "0", "no", "on", "off"` all fall back
- `test_h1_parse_empty_string_uses_default` — empty + whitespace-only → default
- `test_h1_parse_unset_var_uses_default` — unset env → default
- `test_h1_parse_invalid_default_raises` — ValueError if caller passes bogus default like "Production"
- `test_h1_all_configs_use_parse_bias_mode_env` (×4 systems) — STRUCTURAL: every config.py uses the helper AND has no raw `os.getenv("..._BIAS_MODE", ...)` patterns left. Catches future regressions.

---

### H2 — F28 logs use `_log_journal` (raises on DB blip) instead of `_log_journal_safe` ✅ (2026-06-18)

**Files:**
- `backend/scanner/scheduler.py:573`
- `backend-micro/scanner/scheduler.py:266`
- `backend-oil/scanner/scheduler.py:264`
- `backend-oil-micro/scanner/scheduler.py:228`

**Audit finding:**
F28 emits `_log_journal(...)` on every scan tick. `_log_journal` (vs `_log_journal_safe`) raises on DB failure. The outer scheduler try/except catches it but **aborts the entire scan tick** for that system. So a transient DB blip during F28 logging now cancels the sweep evaluation that would otherwise have run.

**Why this is HIGH:**
**F28 is supposed to be observability — it must not introduce a new failure mode.** Pre-F28, the same DB blip would not have aborted the sweep step (the bias filter doesn't write to DB; SWEEP_DETECTED writes happen later). Today, a DB hiccup at the wrong instant would cause a missed signal, blamed on F28 rather than the DB.

**VERIFY:** ✅
Confirmed all 4 schedulers used `_log_journal(` (not `_log_journal_safe(`) in F28 override block. F28_BIAS_RESOLVED journal event lines verified at:
- `backend/scanner/scheduler.py:573`
- `backend-micro/scanner/scheduler.py:262`
- `backend-oil/scanner/scheduler.py:260`
- `backend-oil-micro/scanner/scheduler.py:224`
All 4 already had `_log_journal_safe` imported — fix is one-line replacement per file.

**RCA:** ✅
Phase 3 ship copied the canonical pattern from sibling code (`SWEEP_DETECTED`, `SIGNAL_FIRED` writes use `_log_journal`). Those events MUST persist for postmortem audit trail — that's why they raise on DB failure. **F28_BIAS_RESOLVED is observability-only** — never consulted by postmortem. Wrong helper choice. F28 was supposed to be strict add-only safety net; the `_log_journal` choice introduced a new failure mode (DB blip during F28 logging → `psycopg2.OperationalError` propagates → outer try/except in `position_monitor_job` aborts entire scan tick → missed signal). Pre-F28, the same blip wouldn't have aborted the bias compute step.

**FIX:** ✅ (commit pending)
Replaced `_log_journal(` with `_log_journal_safe(` in all 4 F28 override blocks (1 line per file × 4 files). Added comment in each block explaining the choice (observability-only event vs canonical audit-trail event).

**TEST:** ✅ — `tests/test_filter_28_audit.py` (8 H2 tests pass)
- `test_h2_f28_block_uses_log_journal_safe_not_log_journal` (×4 schedulers) — STRUCTURAL: uses regex to scan back from `F28_BIAS_RESOLVED` and asserts the immediately-preceding journal call is `_log_journal_safe(`, not `_log_journal(`. Catches future regressions where someone "fixes" the helper choice the wrong way.
- `test_h2_log_journal_safe_imported` (×4 schedulers) — confirms helper imported (otherwise the H2 fix would be NameError at runtime).
- Full F28 suite: 37 green. F27 audit suite: 261 still green. No regressions.

---

### H3 — Parity harness has zero F28 awareness; will false-positive after first flip ✅ (2026-06-18)

**Files:**
- `tests/harness/parity/runner.py:83-120, 145`
- `tests/harness/test_22_parity.py`

**Audit finding:**
`runner.py:_build_daily_bias()` always computes V1+V2. When user sets `BIAS_MODE=neutral` on a system, the live core fn returns extra signals (bias-blocked sweeps now fire), but the BT side keeps blocking them. **Parity report will show drift, not because either side has a bug, but because the harness ignores F28.**

**Why this is HIGH:**
The parity harness is one of the project's hard-won safety nets ([[project-parity-harness]]). Once a system is flipped to neutral, the harness will report a false-positive drift on every run. **Either it gets disabled (loss of safety net) or every drift alarm has to be hand-investigated.**

**VERIFY:** ✅
Confirmed `tests/harness/parity/runner.py` had ZERO F28 awareness — `_build_daily_bias()` always built V1+V2 regardless of system's BIAS_MODE config. Once a system is flipped to neutral, BT side would block signals that live fires → false drift on every run.

**RCA:** ✅
Phase 3 ship was scoped to "make F28 toggleable in live." `tests/harness/parity/` is a separate test infrastructure with its own `_build_daily_bias()` — update was missed because the harness wasn't run as part of F28 ship gate. Per `[[project-parity-harness]]`, harness is a hard-won safety net; F28 must mirror the live state into BT side or the safety net becomes useless after first flip.

**FIX:** ✅ (commit pending)
- `tests/harness/parity/runner.py` — Added `_resolve_system_bias_mode(cfg)` helper that imports each system's config module via `cfg.config_module_path` and reads `BIAS_MODE`. Defaults to "production" on any error (harness must not break on F28 issues).
- In `run_parity_check()` after `_build_daily_bias()`: if resolved mode is "neutral", swap `daily_bias` for `NeutralBiasDict()` BEFORE passing to extractors. Print line shows which mode was used. ImportError of `NeutralBiasDict` falls back to V1+V2 with WARNING (older-branch safety).

**TEST:** ✅ — `tests/test_filter_28_audit.py` (4 H3 tests pass)
- `test_h3_parity_runner_has_resolve_system_bias_mode_helper` — STRUCTURAL: helper defined + defaults to production on error
- `test_h3_parity_runner_swaps_daily_bias_when_neutral` — STRUCTURAL: NeutralBiasDict swap happens BEFORE extract_backtest_signals (positional check via .find())
- `test_h3_parity_runner_handles_neutral_bias_import_failure_gracefully` — STRUCTURAL: ImportError wrapped + fallback warning logged
- `test_h3_parity_harness_full_suite_still_passes` — RUNTIME: full `tests/harness/test_22_parity.py` runs in subprocess and exits 0 (22 parity tests pass with 25s wall-clock). Catches any breaking refactor.

---

### H4 — `BIAS_MODE` cached at process start; mid-day env flip without restart = silent no-op ⏸

**Files:**
- `backend/scanner/scheduler.py:550`
- `backend-micro/scanner/scheduler.py:241`
- `backend-oil/scanner/scheduler.py:239`
- `backend-oil-micro/scanner/scheduler.py:203`

**Audit finding:**
Function-local `from backend.config import BIAS_MODE as _bias_mode_cfg` (or service-relative variants). Python caches this on first import — **the bias-mode value is fixed at process start.** Mid-day env-flip without service restart is a silent no-op. Nothing in the deploy notes or Telegram path warns the operator if this happens.

**Why this is HIGH:**
User reads "set env var on VPS .env to flip" in deploy doc. They edit .env, don't restart, expect the system to flip. **It won't.** There is no signal in /state, no warning in stream — it just keeps trading in production mode. Subtle and invisible.

**VERIFY:**
<!-- Reproduce: start service with BIAS_MODE=production; touch .env and set BIAS_MODE=neutral; without restarting, verify /state.bias_mode still returns "production" and scheduler logs still say mode=production. -->
_pending_

**RCA:**
<!-- Python module-level constant. config.py executes load_dotenv() + os.getenv() at import time. The constant is a string, copied into BIAS_MODE. Any later env var changes don't affect the in-memory string. Cached forever. -->
_pending_

**FIX (3 options, pick one):**
<!-- (a) Document the restart requirement explicitly in F28 ship doc (cheapest).
     (b) Re-read via os.environ.get(...) inside the override function so it's truly dynamic.
     (c) Expose /admin/reload-bias-mode endpoint that re-reads env.
     Recommend (a) for now; (b) if operators repeatedly miss step. -->
_pending_

**TEST:**
<!-- (a): doc-only, no test. (b): runtime test — patch os.environ, call _run_alpha_sweep_core, verify new value used. -->
_pending_

---

# MEDIUM (5)

### M1 — Frontend "Run Backtest" doesn't pipe `BIAS_MODE` ⏸

**Files:**
- `backend/routes/backtest.py:77-83`
- `backend-micro/routes/backtest.py:40+`
- `backend-oil/routes/backtest.py:25+`
- `backend-oil-micro/routes/backtest.py:40+`

**Audit finding:**
Frontend "Run Backtest" calls `run_backtest(...)` without passing `bias_mode`. So even when the live system is in `BIAS_MODE=neutral`, the dashboard's BT defaults to `bias_mode=None` (production). User-comparing live to BT will see structurally different signal counts.

**Why this matters:**
Per `[[feedback-replay-vs-real-backtest]]`, the BT engine is the only source of truth. **If a user clicks "Run BT" expecting it to replicate today's live behavior, they'll get a different result.** Easy to mistake for a parity bug.

**VERIFY:**
<!-- Inspect backtest.py routes; confirm run_backtest is called without bias_mode. -->
_pending_

**RCA:**
<!-- Phase 3 wiring was strict-minimal. Backtest route is a different code path; BT kwarg landed in run_backtest but the dashboard's HTTP route wasn't updated. -->
_pending_

**FIX:**
<!-- Pipe BIAS_MODE into the BT route for each of the 4 systems:
     `result = run_backtest(..., bias_mode=BIAS_MODE if BIAS_MODE != "production" else None)`
     Or expose `bias_mode` as a request query param so the frontend can pick. Recommend the latter — operator wants to A/B compare live's mode against the alternative. -->
_pending_

**TEST:**
<!-- Structural × 4 backtest routes: run_backtest must be called with bias_mode parameter (or accept it from request). Plus runtime: assert BT result trade count matches expected for each mode. -->
_pending_

---

### M2 — F28 logs per scan tick → ~526k journal rows/year ⏸

**Files:**
- `backend/scanner/scheduler.py:556-586` (and parallel blocks in 3 other schedulers)

**Audit finding:**
F28 emits log + journal per scan tick — every 3 minutes for 12h on Macro, 24h on Micro. Aggregate ≈ 1,440 F28 rows/day across 4 systems = **~526k rows/year of pure observability data** in `gd_journal`. JSONB context column will dominate the table. **No retention policy referenced anywhere.**

**Why this matters:**
gd_journal is queried by postmortem scripts and the daily reconciler. Adding 0.5M F28 rows/year balloons table size and can slow the queries used during incident response. Probably not a problem in month 1; will be a problem in month 6.

**VERIFY:**
<!-- After 1 week of live F28 logging, query gd_journal: SELECT date, count(*) FROM gd_journal WHERE event_type = 'F28_BIAS_RESOLVED' GROUP BY date. Confirm volume matches estimate. -->
_pending_

**RCA:**
<!-- Phase 3 prioritized observability over volume. Per-tick log was simpler than state-change-only log. -->
_pending_

**FIX (3 options, pick one):**
<!-- (a) Log F28 only on bias-CHANGE (state machine — first scan of day, or when computed/effective transitions). Drops volume from per-tick to ~1/day/system = 1,460 rows/year (-99.7%).
     (b) Add retention policy / vacuum cron on F28_BIAS_RESOLVED rows older than 30 days.
     (c) Drop the `_log_journal_safe` call entirely — `_log.info` + stdout already cover the audit trail.
     Recommend (a) — cleanest semantically. -->
_pending_

**TEST:**
<!-- (a) only logs on first-of-day or when bias state changes. Test: simulate 480 scan ticks across 1 day with same bias; assert exactly 1 F28_BIAS_RESOLVED row. -->
_pending_

---

### M3 — Override fires before all early-exit gates → noise volume ⏸

**Files:** All 4 schedulers (F28 override block placement)

**Audit finding:**
The override fires inside every `_run_*_sweep_core` invocation **even when no scan is going to happen** (e.g. cooldown will block, max_trades_today reached, asia bars insufficient). It's correctly placed AFTER the early-returns for missing-data conditions in some schedulers, but it executes before the cooldown / max-trades check fires for others (e.g. the 5-min cooldown post-bias-compute branch in Gold Micro). **Net: heavy log-volume on idle scans where no signal would fire anyway.**

**Why this matters:**
Mostly cosmetic — adds noise to journal without information. **Combined with M2 above, this compounds the table-bloat.**

**VERIFY:**
<!-- Read each scheduler's flow ordering. Map: at the moment the F28 override block fires, which gates have already been checked? -->
_pending_

**RCA:**
<!-- Override placement chosen for "after bias compute" — didn't account for downstream gates that would discard the signal anyway. -->
_pending_

**FIX:**
<!-- Move the F28 override block to fire only when a sweep is actually being evaluated (immediately before the `if bias != "neutral":` check), not after bias compute. Combine with M2 fix (a) for max effect. -->
_pending_

**TEST:**
<!-- Runtime: simulate scan tick where cooldown is active. Assert F28_BIAS_RESOLVED is NOT logged (because override didn't fire — was deferred to after cooldown gate). -->
_pending_

---

### M4 — `NeutralBiasDict` only partial dict-API override ⏸

**File:** `backend/backtest/neutral_bias.py:23-50`

**Audit finding:**
`NeutralBiasDict` overrides `__getitem__`, `__setitem__`, `get`, `update`, `__contains__` — **but inherits `__iter__`, `__len__`, `keys()`, `values()`, `items()`, `pop()`, `popitem()`, `setdefault()`, `__eq__`, `__or__`, `copy()`, `clear()` from dict.** Today no production code uses these methods on `daily_bias` (verified via grep), but the contract is "any dict-API access returns neutral semantics" — and the class doesn't enforce that.

**Why this matters:**
**Subclassing dict with partial method overrides is a known Python anti-pattern.** Any future reader who adds `for d in daily_bias:` or `len(daily_bias)` gets the empty-dict view (since `__setitem__` is a no-op, the underlying dict stays empty), creating a silent edge case.

**VERIFY:**
<!-- grep production code for dict methods on daily_bias other than .get() and []. Confirm only .get() is used. -->
_pending_

**RCA:**
<!-- Phase B's NeutralBiasDict was implemented to support the existing access pattern (.get + []). Future-proofing was deprioritized. -->
_pending_

**FIX:**
<!-- (a) Document the contract more explicitly in docstring (currently fine).
     (b) Add a sanity test like test_neutral_bias_dict_iteration_returns_nothing() so the assumption is regression-tested.
     (c) Switch to collections.abc.Mapping with explicit raises on unimplemented methods.
     Recommend (b) — minimal cost, catches future drift. -->
_pending_

**TEST:**
<!-- Unit test exercising every dict mutation method on a NeutralBiasDict. Assert behavior is neutral or raises. -->
_pending_

---

### M5 — Multi-seed shows 1/420 yearly loss; commit messages claim "84W/0L" without seed disclosure ⏸

**Files:**
- `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md`
- F28 commit messages (Path A, Path B)
- `scripts/output/filter_28_multiseed_console.txt:248`

**Audit finding:**
Multi-seed sweep flagged `gold-micro seed=99 lost in 2006` (1 yearly slice out of 84). The Path A summary (84W/0L) and Path B summary (84W/0L) are seed=42 single-seed. **The "84/84" framing in research docs / Path B commit message overstates robustness — under multi-seed, the perfect record breaks at one tile.**

**Why this matters:**
Doesn't change ship decision (1/420 is still robust), but **the language in commit messages and `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md` should not claim 84/84 without seed disclosure.** Per `[[feedback-eval-findings]]` — never cite IS without OOS, and never cite a single-seed number as ground truth in an audit document.

**VERIFY:**
<!-- Grep docs and commit messages for "84W" or "84/84" claims. Confirm absence of "single-seed" qualifier. -->
_pending_

**RCA:**
<!-- Single-seed and multi-seed work was done in different sessions; framing language carried over without consistency check. -->
_pending_

**FIX:**
<!-- Update docs/FILTER_28_BIAS_DISABLE_RESEARCH.md Path A / B sections to add "(single-seed=42)" qualifier on the 84W/0L line. Multi-seed section already correctly says "419/420 = 99.76% across multi-seed". -->
_pending_

**TEST:**
<!-- Doc-only — no automated test. -->
_pending_

---

# LOW (4)

### L1 — `print()` duplicates `_log.info` in F28 override ⏸

**Files:** All 4 schedulers (F28 override block)

**Audit finding:**
F28 prints to stdout via `print()` AND logs via `_log.info` — same content. Every other live event in the codebase uses `_log` for structured logs and `print()` for human-readable terminal output, but never both for the same message.

**Why this matters:**
Stylistic only. Not a bug. Slight stdout/log duplication adds marginal noise to terminal output.

**VERIFY:**
<!-- Confirm all 4 schedulers have both `_log.info("F28-BIAS", ...)` and `print(f"  [F28-BIAS] ...")`. -->
_pending_

**RCA:**
<!-- Operator originally requested logs visible in terminal. Both path were added defensively. -->
_pending_

**FIX:**
<!-- Remove the print() since _log.info already covers it (the journal call is independent — needed for DB persistence, but print is redundant with _log.info). -->
_pending_

**TEST:**
<!-- Optional: check that print is NOT called from F28 override block. -->
_pending_

---

### L2 — Bare `except` in `_get_bias_mode_safe()` swallows all errors ⏸

**Files:**
- `backend/routes/state.py:128`
- `backend-micro/routes/state.py`
- `backend-oil/routes/state.py`
- `backend-oil-micro/routes/state.py`

**Audit finding:**
`try: from … import BIAS_MODE / except Exception: return "production"`. **The bare `except` swallows ImportError, AttributeError, syntax errors in config.py — anything.** If the config module itself is broken, the dashboard happily reports "production" without surfacing the underlying problem.

**Why this matters:**
Diagnostic fog — operators staring at "production" badge while the config is broken would have a hard time figuring out why settings aren't taking effect.

**VERIFY:**
<!-- Reproduce: introduce a syntax error in config.py; restart service; check /state.bias_mode — should still return "production" silently with no warning. -->
_pending_

**RCA:**
<!-- Phase 3 wiring used broad `except Exception` to be defensive; didn't add logging on the failure path. -->
_pending_

**FIX:**
<!-- Tighten to `except (ImportError, AttributeError):` and add `_log.warning(...)` on the path so the failure is observable. -->
_pending_

**TEST:**
<!-- Unit: patch config import to raise; assert _log.warning is called and "production" is returned. -->
_pending_

---

### L3 — Frontend exact-string match couples layers ⏸

**File:** `frontend/app/live/page.tsx:97`

**Audit finding:**
Conditional render `state?.bias_mode === "neutral" ? ... : null`. **If a future revision uses lowercase variants (`"NEUTRAL"`, etc.), badge silently disappears.** Tightly coupled to backend's exact string.

**Why this matters:**
Coupling between layers; if backend lowercase normalization drifts, frontend silently breaks.

**VERIFY:**
<!-- Inspect frontend; confirm exact-match check. -->
_pending_

**RCA:**
<!-- Phase 3 wiring kept the simplest possible TS check. Defensive normalization wasn't added. -->
_pending_

**FIX:**
<!-- Use a constant like `BIAS_MODE_NEUTRAL = "neutral"` shared via a TS type, or do `state?.bias_mode?.toLowerCase() === "neutral"` defensively. -->
_pending_

**TEST:**
<!-- Frontend test: render with bias_mode = "neutral", "NEUTRAL", "Neutral" — badge should appear in all cases (after fix). -->
_pending_

---

### L4 — Computed-neutral days log misleadingly when production mode ⏸

**Files:** All 4 schedulers (F28 override block)

**Audit finding:**
When computed bias is already "neutral" and `BIAS_MODE=production`, the F28 row says `mode=production effective=neutral filter_active=False` — technically correct but slightly misleading. **A naïve operator scanning logs may think F28 is active when it isn't (since `filter_active=False`).**

**Why this matters:**
Cosmetic — the row content is internally consistent. **But it makes `WHERE filter_active=False` queries imprecise:** they include both genuine F28-neutral days and production-neutral days.

**VERIFY:**
<!-- Reproduce: simulate scan tick with V1+V2 computing neutral while BIAS_MODE=production. Confirm log line is misleading. -->
_pending_

**RCA:**
<!-- Field naming: `filter_active` reflects whether the filter is gating signals, not whether F28 itself is active. The two concepts are conflated. -->
_pending_

**FIX:**
<!-- Add a third boolean `f28_active` (= `_bias_mode_cfg == "neutral"`) to the journal context so SQL queries can distinguish:
       SELECT ... WHERE f28_active = TRUE  -- only F28-flipped systems
       SELECT ... WHERE filter_active = FALSE  -- bias not gating signals (could be either reason) -->
_pending_

**TEST:**
<!-- Structural × 4 schedulers: F28 override block must include f28_active in journal context. -->
_pending_

---

# INFO (3)

### I1 — Config import not wrapped in try/except in scheduler override ⏸

**Files:** All 4 schedulers (F28 override block)

**Audit finding:**
None of the schedulers wrap the override-block import (`from backend.config import BIAS_MODE as _bias_mode_cfg`) in try/except. **If the config module ever breaks at the BIAS_MODE line, the entire `_run_alpha_sweep_core` will start raising ImportError every tick.** That's caught by the outer try/except (no scheduler crash), but live trading is dead until config is fixed.

**Why this matters:**
Defensive — config is unlikely to break, but if it does, F28 takes down all scans, not just the kill-switch logic.

**VERIFY:**
<!-- Reproduce: introduce syntax error in BIAS_MODE line; restart service; observe scheduler aborting every tick. -->
_pending_

**RCA:**
<!-- Phase 3 wiring assumed config.py is reliable. Doesn't account for malformed env vars or human error during VPS .env edit. -->
_pending_

**FIX:**
<!-- Wrap the import with try/except defaulting to "production" and `_log.exception("F28-BIAS", "config_import_failed", ...)` so the scheduler keeps running and the failure is loud in logs. -->
_pending_

**TEST:**
<!-- Unit: patch config import to raise; assert scheduler tick completes (with default "production" behavior) and logs F28-BIAS config_import_failed. -->
_pending_

---

### I2 — No tests cover F28 ⏸

**Files:** `tests/` directory

**Audit finding:**
**`tests/` has zero references to `BIAS_MODE`, `bias_mode`, `NeutralBiasDict`, or `resolve_bias_mode`.** Path A/B numerical agreement was the validation, but no regression test guards against future drift.

**Why this matters:**
**If someone refactors `_run_alpha_sweep_core` and accidentally moves the F28 override block above `if len(daily_candles) < 2`, the change won't be caught.**

**VERIFY:**
<!-- grep tests/ for F28 / BIAS_MODE / NeutralBiasDict — confirm zero matches. -->
_pending_

**RCA:**
<!-- F28 was validated via 21yr BT runs (real numbers). No unit-test layer added because BT was the gold standard. But BT can't catch all refactor regressions. -->
_pending_

**FIX:**
<!-- (a) tests/unit/test_neutral_bias.py covering NeutralBiasDict + resolve_bias_mode (rejects typos, handles None/empty/space).
     (b) tests/harness/test_23_f28_kill_switch.py running each system's _run_*_sweep_core twice — once with BIAS_MODE patched to "neutral", once "production" — and asserting the strategy-output signal count differs in the expected direction. -->
_pending_

**TEST:**
<!-- (Self-referential — adding the tests IS the fix.) -->
_pending_

---

### I3 — Doc claims "+$233k for Gold Macro" without seed/range qualifier ⏸

**File:** `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md` and config comments in 4 config.py files

**Audit finding:**
Doc says "21yr BT proves +$233k for Gold Macro" in config comments — but the multi-seed result for Gold Macro is **mean=$+233.2k, std=$+117, range $+233.0k–$+233.3k**, very narrow. **Doc could include the ±std and the 1/84 break in seed=99/Gold-Micro/2006 for honesty.**

**Why this matters:**
Per `[[feedback-eval-findings]]` — never cite IS without OOS, and never cite a single-seed number as ground truth in an audit document.

**VERIFY:**
<!-- grep config files + docs for the +$233k claim. Confirm absence of std/range qualifier. -->
_pending_

**RCA:**
<!-- Single-seed numbers were locked in early; multi-seed validation came later but config comments weren't backfilled. -->
_pending_

**FIX:**
<!-- Update docs/FILTER_28_BIAS_DISABLE_RESEARCH.md and 4 config.py BIAS_MODE comments to include multi-seed mean ± std and the one yearly-slice loss. -->
_pending_

**TEST:**
<!-- Doc-only — no automated test. -->
_pending_

---

# Phase plan

## Phase 1 — Pre-flip blockers (must fix before flipping any system) ✅ COMPLETE
- [x] C1 — stream.py bias_mode field for Gold Macro + Oil Macro
- [x] H1 — parse_bias_mode_env helper for whitespace/case safety
- [x] H2 — `_log_journal` → `_log_journal_safe` in 4 schedulers
- [x] H3 — Parity harness F28-aware

## Phase 2 — Should fix before second system flips
- [ ] H4 — Document restart-required (or make truly dynamic)
- [ ] M1 — Backtest dashboard route passes bias_mode
- [ ] M2 — F28 log-only-on-bias-change (drop volume from 526k/yr to ~1.4k/yr)
- [ ] M3 — F28 override block placement (combine with M2)
- [ ] M5 — Doc + commit-message qualifiers (single-seed disclosure)

## Phase 3 — Cleanup window (any time after first system stable)
- [ ] M4 — NeutralBiasDict regression test (anti-pattern guard)
- [ ] L1 — Remove redundant `print()` in F28 override
- [ ] L2 — Tighten bare `except` in `_get_bias_mode_safe`
- [ ] L3 — Frontend defensive lowercase
- [ ] L4 — Add `f28_active` to journal context

## Phase 4 — Long tail (when test infra is being touched anyway)
- [ ] I1 — Wrap config import in try/except
- [ ] I2 — Add F28 unit + integration tests
- [ ] I3 — Doc consistency pass (multi-seed numbers)

---

# Estimated total effort

| Phase | Items | Time | Blocks |
|---|---|---|---|
| Phase 1 | 4 (C1, H1, H2, H3) | ~80 min | First system flip |
| Phase 2 | 5 (H4, M1, M2, M3, M5) | ~90 min | Second system flip |
| Phase 3 | 5 (M4, L1, L2, L3, L4) | ~45 min | Nothing (cleanup) |
| Phase 4 | 3 (I1, I2, I3) | ~120 min | Nothing (long tail) |
| **TOTAL** | **17** | **~5.5 hr** | — |

---

# Lifecycle decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-18 | Audit run by general-purpose Sherlock-mode agent | After F28 deploy, before any live system flip |
| 2026-06-18 | Doc created with 17 items, 4 phases, framework lifecycle markers | Per `[[feedback-bug-fix-framework]]` standing rule |
| 2026-06-18 | Phase 1 complete: C1 + H1 + H2 + H3 shipped + 41 tests pass | First-flip blockers cleared. F28 can now safely flip first system to neutral. |
| (pending) | Phase 2 items shipped + tested | Required before second system flip |
| (pending) | First system flipped (recommend Gold Macro) | After Phase 1 complete |
| (pending) | Second system flipped | After 5-7 days observation + Phase 2 complete |

---

# Cross-references

- `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md` — parent F28 research doc
- `docs/FILTER_27_AUDIT_BACKLOG.md` — same framework precedent (24 items, 21 shipped)
- `[[feedback-bug-fix-framework]]` — VERIFY → RCA → FIX → TEST standing rule
- `[[feedback-no-auto-ship]]` — explicit user sign-off per item
- `[[feedback-user-explicit-opt-in]]` — multi-stage live opt-in
- `[[project-parity-harness]]` — H3 affects this safety net
- `backend/execution/limit_price.py:35-108` — H1 reference pattern (parse_dry_run_env)
- `backend/backtest/neutral_bias.py:53-70` — Path B's resolve_bias_mode (already correct)

---

**Audit completed: 2026-06-18.**
**Next action: User approval to proceed with Phase 1 fixes (4 items, ~80 min).**
