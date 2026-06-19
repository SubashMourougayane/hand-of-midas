# Session Handoff — 2026-06-11 (PM continuation)

Continues from `docs/SESSION_2026_06_11.md` (which covered the 22:00 IST Jun 10 → 02:30 IST Jun 11 marathon: orphan reconciler + phantom-fill fixes).

## Theme

Built the parity-verification harness end-to-end (Phases 1-6, 6 commits, baseline measured), then expanded EDGE_FILTERS from 7 candidates to 17 after a structural audit, capped by writing two new docs to formalize the rollout plan. Two more live trades happened during the session — one closed cleanly (`GD-MI-14e2fed1` MAX_HOLD harvest +$564), one is stuck in DB orphan state (`OIL-AS-59a94823`), one is currently open (`OIL-AS-f5e9710a` -$180 unrealized).

## What Happened (Chronological)

### Phase 1 — Parity harness scaffold (commits `81f7189`, `2d4c357`)
Built `tests/harness/parity/{config,extractor,diff,score,runner}.py` and `test_22_parity.py`. Phase 1 gold_micro only; Phase 2 extracted soft-gate logic into `evaluate_gates()` with 9 unit tests covering catastrophic / warning / clean branches. **Bug found during impl:** my mock_execute initially returned `len(records)` for ALL COUNT queries — scheduler emits TWO COUNT queries (trades-today and open-positions); returning the same value made the system think there was an open position after the first signal, blocking subsequent days. Fixed by SQL-token disambiguation.

### Phase 3 — Oil Micro added (commit `6fb1ff3`)
Two infrastructure issues surfaced: Oil Micro's backtest module is per-system (not shared with Gold's), and `BCO_USD_D.csv` has plain-OHLC columns (not bid/ask), so `load_candles()` left the DataFrame without `mid_*` columns. Added `_ensure_mid_columns()` post-processor in runner.

### Phase 4 — Macro systems (commit `d8fdde7`)
Macro architecture differs (single Asia window vs rolling). User explicitly approved the only production-code edit in this work: refactor `_run_alpha_sweep` into a thin wrapper + `_run_alpha_sweep_core(now, h1_candles, daily_candles, m3_candles, dry_run=False)`. Mirror change in `backend/scanner/scheduler.py` and `backend-oil/scanner/scheduler.py`. Production callers (zero-arg `_run_alpha_sweep()`) still work identically. Added `_extract_live_signals_macro()` for the rolling-vs-single-window dispatch.

### Phase 5 — Diagnosis hints (commit `bd481ab`)
Expanded SignalDiff hint heuristics: `direction_flipped`, `entry_price_delta_exceeds_X`, `timestamp_delta_more_than_180s`, `live_skipped_with_reason_X`, `live_signaled_outside_backtest_window`. Added 9 new unit tests. Total test_22 count: 22 (4 system parities + 9 gate logic + 9 diagnosis).

### Phase 6 — Operator docs + v1 baseline (commit `1a3f050`)
Wrote `docs/PARITY_HARNESS.md` (operator guide), updated `docs/EDGE_FILTERS.md` to mark Phase 0 SHIPPED, added test_22_parity.py mention to `CLAUDE.md`, recorded v1 baseline numbers.

### Trade incidents during session
- `GD-MI-14e2fed1` (entered 08:30 UTC, closed 12:31 UTC by MAX_HOLD at $4072.74, +$564.19 gross / +$562.58 net). User initially questioned whether trade was bypassing strategy ("JM panel says 'Closed by: Client'"). Investigation: MAX_HOLD closes via API, JM labels API closes as Client. Postmortem written: `docs/trades/GD-MI-14e2fed1.md` (commit `f82602f`). Verdict: ✅ Protected by BE.
- `OIL-AS-59a94823` (Oil Macro LONG @ $91.51, entered 12:18 UTC). Broker closed it ~11:43 UTC for ~+$564, but DWX OnTradeTransaction handler did NOT fire (same dual-instance bug as `OIL-AS-5434644d` last night). DB row stuck. EXIT_AMBIGUOUS streak hit 82+. Diagnostic written (`scripts/diagnose_OIL-AS-59a94823_close.py`), commit `1054196`. **Still unresolved at session end.**
- `OIL-AS-f5e9710a` (Oil Macro LONG @ $92.95, entered 12:45 UTC). Fired DESPITE `OIL-AS-59a94823` being stuck in DB — Oil Macro had ZERO of the 3 DB gates Gold Macro has. Fixed in commit `a515ff2` (added one-at-a-time + 5-min cooldown). User skeptical of the entry geometry (R:R 0.69 post-slippage; visible wick rejection on chart). Investigation showed gate's pre-slippage R:R was ~0.83 — barely passing — and slippage of $0.12 eroded it. **Trade still open at session end, -$180 unrealized.**

### EDGE_FILTERS expanded 7 → 17 (commit `76bb3ba`)
- **Filter #8** (Engulfing Close-Strength) — surfaced live by user's eye on `OIL-AS-f5e9710a` chart screenshot showing wick rejection
- **Filter #9** (R:R Upper Bound 4.0) — surfaced from R:R distribution analysis (OIL-AS-59a94823 had R:R 6.53)
- **Filters #10-#17** — surfaced by an audit agent reading all 4 schedulers + both backtest modules. Findings verified directly against source code:
  - #10 Spread-inside SL (Oil Macro sl_buffer 0.03 vs spread ~$0.10)
  - #11 Non-deterministic slippage (np.random.uniform unseeded — PARITY BLOCKER)
  - #12 Engulfing-of-doji (no prev-body magnitude check)
  - #13 Wick-vs-body asymmetry (no upper-wick-on-bullish check)
  - #14 prev=sweep-bar pollution
  - #15 Cooldown bypass (Macro adds _traded_sweeps AFTER execute, not before)
  - #16 R:R lower bound 0.8 too low
  - **#17 Live `risk<0.01` vs backtest `risk<0.3` (Oil Macro)** — 6th confirmed live↔backtest drift bug

### Final docs (commit `4db24d2`)
Wrote `docs/PARITY_HARNESS_EXPLAINED.md` — plain-language explainer + next-session priorities. Asked for by user after asking "what are we doing here on this numbers and whats parity harness and its status."

## What's Live (after session end)

- **VPS:** Contabo Windows, 4 services healthy
- **Branch:** `midas-deploy`, head `4db24d2`. **Pushed to origin (commits a515ff2 and 0a5ace4 pushed mid-session for VPS diagnostics; rest are local).** Verify `git log origin/midas-deploy..HEAD` if uncertain.
- **Open positions:** `OIL-AS-f5e9710a` Oil Macro LONG @ $92.95, currently -$180 unrealized. Bid 91.34, SL 90.96. Strategy will manage.
- **Stuck DB row:** `OIL-AS-59a94823` exit_time NULL, broker has no matching position. **Needs manual close** when ready (use pattern from `scripts/close_OIL-AS-5434644d.py`).
- **DD state Oil Macro:** consecutive_losses=3, risk_mult=0.5 → next Oil Macro signal will size at half. One more loss = 4/5; two more = pause 2 signals.
- **Tests:** 325 passing total, 3 pre-existing test_14_oil_micro fixture failures unchanged.

## Commits This Session (chronological — Jun 11 PM)

| SHA | Description |
|---|---|
| `81f7189` | Parity harness Phase 1 — Gold Micro skeleton + soft gate |
| `2d4c357` | Parity harness Phase 2 — soft-gate logic extracted + 9 unit tests |
| `6fb1ff3` | Parity harness Phase 3 — add Oil Micro |
| `d8fdde7` | Parity harness Phase 4 — Gold Macro + Oil Macro coverage |
| `bd481ab` | Parity harness Phase 5 — diagnosis hints expanded + 9 unit tests |
| `1a3f050` | Parity harness Phase 6 — operator docs + v1 baseline + integration |
| `1054196` | Diagnostic for OIL-AS-59a94823 closure investigation |
| `f82602f` | Postmortem: GD-MI-14e2fed1 — Protected by BE, MAX_HOLD harvested win |
| `a515ff2` | Oil Macro: add missing one-at-a-time + 5-min cooldown gates |
| `0a5ace4` | Diagnostic: investigate OIL-AS-f5e9710a R:R 0.69 gate bypass |
| `76bb3ba` | EDGE_FILTERS expanded to 17 candidates + detailed implementation plan |
| `4db24d2` | Add PARITY_HARNESS_EXPLAINED.md — plain-language doc + next-session plan |

## Outstanding Issues

### CRITICAL
1. **Filter #17 — live ≠ backtest risk threshold (Oil Macro).** 6th confirmed drift bug. 1-line fix at `backend-oil/scanner/scheduler.py:285,299` (`risk < 0.01` → `risk < 0.3` to match backtest). **Must ship before any filter measurement** — otherwise downstream backtest baselines are themselves drifted.
2. **`OIL-AS-59a94823` stuck DB row.** Broker has closed; DB has not. Needs manual-close script (mirror `scripts/close_OIL-AS-5434644d.py` from yesterday) with the real broker exit values from JM web History.

### HIGH
3. **Filter #11 — non-deterministic slippage.** `np.random.uniform(0, 0.02)` in `slippage()` is unseeded. Parity harness has 1-3pp run-to-run noise from this. Must fix before measuring filter alpha. Choice: drop random term entirely OR seed per-bar.
4. **Adversarial canary checks not yet run on the parity harness.** (a) Different `PARITY_DAYS` should produce different parity_pct; (b) intentional drift in one config value should drop parity. Both check the harness itself is correct. ~10 min of work.

### MEDIUM
5. **`OIL-AS-f5e9710a` open trade.** Let strategy manage — SL/TP/MAX_HOLD will resolve. Don't intervene.
6. **DWX OnTradeTransaction dual-instance bug** (yesterday's). Either shut down Mac MT5 or recompile its EA. Without this, future trades may end up stuck like `OIL-AS-5434644d` and `OIL-AS-59a94823`.

### LOW
7. **Mac MT5 still running** — has been since well before today. The closed_orders.json file has never existed on Mac.
8. **Oil Macro `/api/oil/trades` endpoint returns 500.** Hit this twice today during postmortem-skill runs. Worth fixing so future Oil Macro postmortems can use the deterministic gatherer. Investigate `backend-oil/routes/trades.py`.

## Decisions Made

- **Refactored Macro `_run_alpha_sweep` to add `_run_alpha_sweep_core` with `dry_run=True` parameter.** Only production code edit allowed in the parity-harness work, explicitly user-approved via `AskUserQuestion`. Existing zero-arg callers preserved.
- **Wick rejection — added Filter #8 to EDGE_FILTERS, did NOT change strategy gate.** User's eye caught a class of weak engulfings the body-based gate accepts. Filter #8 will be backtest-validated before shipping; the running strategy is unchanged for now.
- **Slippage erosion of R:R is a calibration issue, not a code bug.** The `OIL-AS-f5e9710a` "gate bypass" investigation revealed that `gd_signals.entry_price` is post-slippage `fill_price`, not the pre-slippage `entry_calc` that ran through the gate. Strategy code is correct; calibration to absorb slippage is the open question (Filter #16: raise R:R lower bound from 0.8 to 1.0 or 1.2).
- **Realistic ship count for EDGE_FILTERS: 5-7 of 17.** The plan does NOT commit to shipping all 17. Each filter must pay for itself with backtest improvement. Filters that don't improve PF get archived in a results doc as "tested, didn't help."

## What's Next

When work resumes, in this order:

1. **Run the parity harness adversarial canaries** (item HIGH-4 above). 10 minutes.
2. **Ship Filter #17 + parity harness re-run.** 1-line fix; confirm Oil Macro parity_pct moves toward 100% on the formerly-drifting subset. ~30 min.
3. **Ship Filter #11 (deterministic slippage) + parity harness re-run.** Confirm two consecutive runs produce identical parity_pct to 4 decimals. ~30 min.
4. **Re-establish v1.1 baseline post-Phase-0.** Append to `docs/PARITY_HARNESS.md`.
5. **Manually close `OIL-AS-59a94823`.** Pull real exit data from JM web History. ~15 min.
6. **Phase 1 EDGE_FILTERS rollout begins.** Each filter goes through the 6-step gate per `docs/EDGE_FILTERS_IMPLEMENTATION.md`. Order: #1 Range Exhaustion, #8 Engulfing Close-Strength, #10 Spread-Inside SL.

If 1 hour of additional time were available right now, I'd spend it on canary checks + #17 + #11 (Phase 0). That unblocks all subsequent measurement work and pays back immediately.

## File Inventory

### New files this PM
- `tests/harness/parity/__init__.py`
- `tests/harness/parity/config.py`
- `tests/harness/parity/extractor.py`
- `tests/harness/parity/diff.py`
- `tests/harness/parity/score.py`
- `tests/harness/parity/runner.py`
- `tests/harness/parity_reports/.gitkeep`
- `tests/harness/test_22_parity.py`
- `docs/PARITY_HARNESS.md` (operator guide)
- `docs/PARITY_HARNESS_PLAN.md` (design rationale)
- `docs/PARITY_HARNESS_EXPLAINED.md` (plain-language explainer + next plan)
- `docs/EDGE_FILTERS.md` (17 filter catalog)
- `docs/EDGE_FILTERS_IMPLEMENTATION.md` (6-step gate plan)
- `docs/trades/GD-MI-14e2fed1.md` (postmortem)
- `scripts/diagnose_OIL-AS-59a94823_close.py`
- `scripts/diagnose_OIL-AS-f5e9710a_rr.py`

### Modified
- `backend/scanner/scheduler.py` (additive `_run_alpha_sweep_core` refactor for Macro)
- `backend-oil/scanner/scheduler.py` (same refactor + missing one-at-a-time + 5-min cooldown gates added)
- `tests/harness/test_15_oil_macro.py` (regression tests for the new gates)
- `CLAUDE.md` (parity harness pointer added)

## Numbers to Remember

- **v1 parity baseline (May 19-26 data):** gold_micro 60.0%, oil_micro 77.0%, gold_macro 59.9%, oil_macro 57.4%. **All systems 100% direction agreement on overlapping signals.**
- **Tests:** 325 passing total. test_22_parity = 22 (4 live system parities + 9 gate logic + 9 diagnosis hints). 3 pre-existing test_14_oil_micro fixture failures unchanged.
- **Drift bugs total since system live:** **6** (was 5 at session start; #17 surfaced today by audit).
- **Account at session end:** ~$10,150 nav (balance $10,317.76 - open trade unrealized -$167). Net day **-$1,056** from this morning's `OIL-AS-5434644d` close (now realized).
- **Oil Macro DD state:** consecutive_losses=3, risk_mult=0.5, equity tracker at $7,488.63 (lags broker by ~$2,800 due to stale equity field — needs manual reconcile).
- **EDGE_FILTERS: 17 candidates, realistic ship 5-7.** The rest get logged as tested-didn't-help.
- **Final commit SHA:** `4db24d2`. **Pushed:** through `0a5ace4` (commits up to `0a5ace4` are on origin; everything from `76bb3ba` onwards is local-only).
