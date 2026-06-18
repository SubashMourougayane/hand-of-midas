# Refactor Plan — Unify Live & BT Signal Generation (All 4 Systems)

**Date:** 2026-06-18
**Owner:** Subash
**Driver:** [`MASTER_RCA_LIVE_BT_PARITY.md`](MASTER_RCA_LIVE_BT_PARITY.md)
**Goal:** Eliminate the architectural root cause behind today's $1,517 live disaster (and the 6 prior parity-gap bugs in 3 weeks). Make each live scheduler call its system's BT `generate_signals()` instead of maintaining a parallel reimplementation.

---

## Outcome (what "done" looks like)

- All 4 systems' schedulers call the SAME `generate_signals()` function that BT calls.
- Live still applies production-only gates (cooldown, open-position blockers, persistent blacklist, scheduler tick cadence, wall-clock window) — but they wrap the unified call, not duplicate its math.
- Strategy bug fixes auto-apply to BT and live simultaneously.
- Parity harness — given identical input data + identical config — produces identical signal sets in BT and live (both via `generate_signals()`).
- Drift-bug count for the next 30 days: 0 (vs 6 in the prior 3 weeks).

---

## Constraints / non-goals

- **NOT** changing strategy logic. The math (sweep + engulfing + bias + risk) is already in parity per RCA.
- **NOT** removing live-only safety gates. Cooldown, cross-strategy/cross-system locks, sweep blacklist all stay — they wrap the unified call.
- **NOT** deploying during the 30-day challenge freeze (Jun 22 onwards). All work to land by **Sunday Jun 21 EOD**.
- **NOT** introducing new test infrastructure beyond a parity harness per system.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Refactor breaks live trading mid-deploy | Phase per system; deploy one at a time; smoke test on dry_run before flip |
| BT engine assumes closed bars; live can have in-progress bar | Adapter discards latest bar if `complete=False` (DWX) or if last bar's timestamp == current minute (OANDA) |
| DWX symbol vs OANDA symbol naming mismatch in DataFrame index | Adapter normalizes timezone to UTC; index uses pandas `DatetimeIndex` always |
| Per-system config-key drift (`asia_min_range` vs `min_range`) survives refactor | Phase 1 includes a config-key normalization pass before unification |
| Filter-#27 limit-order live state machine diverges from BT's pre-walk | Out of scope — live state machine stays as-is, only signal-gen unifies |
| Cross-system MT5 lock semantic change | Out of scope for unification; tracked as separate Phase 5 item |

---

## Architecture (target state)

```
LIVE SCHEDULER                                BT ENGINE
----------------                              ---------
fetch DWX/OANDA bars (list[dict])             load CSV (DataFrame)
        │                                              │
        ▼                                              │
broker_to_dataframe(bars) ─────►   dataframe   ◄──────┘
                                       │
                                       ▼
                          generate_signals(h1_df, m3_df, daily_bias)
                                       │
                                       ▼
                                 list[Signal]
                                       │
                       ┌───────────────┴────────────────┐
                       ▼                                ▼
              live: apply gates,                BT: cooldown +
              call execute_signal()             position_exit_time +
                                                execute_trade()
```

Single source of truth: `<system>/strategies/<strategy>.py:generate_signals()`.

---

## Adapter spec (Phase 1 deliverable)

**File:** `backend/scanner/broker_to_dataframe.py` (NEW, shared by all 4 systems)

```python
def broker_bars_to_dataframe(bars: list[dict]) -> pd.DataFrame:
    """Convert broker (DWX/OANDA) candle dicts into BT-compatible DataFrame.
    
    Input format (DWX/OANDA both):
        {"timestamp": ISO str, "bid_open": float, ..., "ask_close": float, "volume": int,
         optionally "complete": bool}
    
    Output:
        DataFrame with DatetimeIndex(UTC), columns:
            bid_open, bid_high, bid_low, bid_close,
            ask_open, ask_high, ask_low, ask_close,
            mid_open, mid_high, mid_low, mid_close,
            volume
    
    - Drops any bar with `complete=False`
    - Normalizes timestamps to UTC
    - Computes mid_* from bid/ask
    - Returns empty DataFrame if input is empty (caller should handle len==0)
    """
```

**Why a shared module:** all 4 schedulers will import it. ONE place to fix DWX/OANDA quirks.

---

## Phasing

| Phase | Scope | Estimated time | Blocking |
|---|---|---|---|
| **0** | Pre-flight: snapshot live-vs-BT parity baseline (dry-run signals for each system) | 1h | none |
| **1** | Build `broker_to_dataframe.py` adapter + unit tests | 1h | Phase 0 done |
| **2** | **Oil Macro** — refactor scheduler to use `generate_signals()` + fix D1 TP formula in BT | 2.5h | Phase 1 done |
| **3** | **Gold Macro** — refactor + verify cross-strategy lock semantics preserved | 2h | Phase 2 done |
| **4** | **Gold Micro** — refactor + fix dedup keying drift + window-iteration parity | 2.5h | Phase 3 done |
| **5** | **Oil Micro** — extract `generate_signals` from `engine.py` to `strategies/` + refactor scheduler | 3h | Phase 4 done |
| **6** | Cross-system safety review: cross-strategy / cross-system MT5 locks | 1h | Phase 5 done |
| **7** | Production smoke test: deploy in dry-run mode, watch 1 cycle each system | 1h | Phase 6 done |
| **8** | Flip dry-run → live, monitor 1 trade per system | n/a (real-time) | Phase 7 done |
| **TOTAL** | | **~14h** | spread over Sat Jun 20 + Sun Jun 21 |

---

## Phase 0 — Baseline parity snapshot (1h)

**Why:** establish "before" numbers so we can prove the refactor didn't change strategy behavior, only its container.

### Tasks

| # | Task | Verification |
|---|---|---|
| 0.1 | Run BT for each system (Jun 11–18 window) on the JM CSV data — record signal list per system | `scripts/output/baseline_bt_signals_<system>.json` |
| 0.2 | Run each scheduler's `_run_*_core` in `dry_run=True` against the same data — record signal list | `scripts/output/baseline_live_signals_<system>.json` |
| 0.3 | Diff baseline_bt vs baseline_live per system — confirm divergences match the per-system RCAs | written to `scripts/output/baseline_parity_<system>.txt` |
| 0.4 | Count: # signals matched, # BT-only, # live-only — baseline metric | committed to `docs/30-day-challenge/reports/PARITY_BASELINE.md` |

**Done when:** all 4 baseline files committed, divergence numbers documented.

---

## Phase 1 — Build adapter (1h)

### Tasks

| # | Task | Verification |
|---|---|---|
| 1.1 | Create `backend/scanner/broker_to_dataframe.py` with `broker_bars_to_dataframe()` | exists, imports cleanly |
| 1.2 | Handle DWX format: `timestamp` as `"2026.06.18 13:00:00"` (server time, no tz) | unit test |
| 1.3 | Handle OANDA format: `timestamp` as `"2026-06-18T13:00:00.000000000Z"` (UTC) | unit test |
| 1.4 | Normalize index to `DatetimeIndex(tz='UTC')` regardless of source | unit test |
| 1.5 | Drop `complete=False` rows if present | unit test |
| 1.6 | Compute `mid_*` columns from bid/ask | unit test |
| 1.7 | Handle empty input → return `pd.DataFrame()` (not raise) | unit test |
| 1.8 | Add tests in `tests/test_broker_to_dataframe.py` (≥ 6 cases) | all pass |

**Done when:** `pytest tests/test_broker_to_dataframe.py` green; `from backend.scanner.broker_to_dataframe import broker_bars_to_dataframe` works in all 4 schedulers (verify by running scheduler imports).

---

## Phase 2 — Oil Macro (2.5h, MOST CRITICAL)

**Why first:** Oil Macro carries the D1 TP-formula divergence — the only system with strategy-math drift. Fixing this first proves the refactor approach works AND closes the largest behavior gap in one stroke.

### Tasks

| # | Task | Files | Verification |
|---|---|---|---|
| 2.1 | **Pin TP formula on BOTH sides to live's structure-based formula:** `tp = asia_high − tp_buf` (LONG) / `asia_low + tp_buf` (SHORT). Update `backend-oil/strategies/alpha_sweep.py:118-119, 136-137` to match `scheduler.py:365, 383`. | `backend-oil/strategies/alpha_sweep.py` | BT trade list for Oil Macro changes — record before/after |
| 2.2 | Re-run BT post-2.1 — verify resulting trade list is "live-realistic" (live's TP geometry) | `backend-oil/backtest/engine.py` | Phase 0 baseline replaced for Oil Macro |
| 2.3 | Refactor `_run_alpha_sweep_core` to call `alpha_sweep.generate_signals(h1_df, m3_df, daily_bias)` | `backend-oil/scanner/scheduler.py:87-431` | dry_run signals match BT exactly |
| 2.4 | Production-only gates kept ABOVE the call: cooldown, open-position DB blocker, daily cap, wall-clock window | scheduler.py | each gate tested in isolation |
| 2.5 | Production-only gates kept BELOW the call: persistent sweep blacklist, lookback windows | scheduler.py | each tested |
| 2.6 | Add `tests/harness/parity/test_oil_macro_parity.py` — runs BT + live (dry_run) on identical data, asserts signal lists match | new test file | passes |
| 2.7 | Run on Jun 11–18 window + 2024 random week + 2020 COVID week → assert 100% signal match (timestamps, direction, entry within $0.01, sl within $0.01, tp within $0.01) | parity harness | 100% match |
| 2.8 | Code review diff before commit | git diff | reviewer (you) signs off |
| 2.9 | Commit with message `Oil Macro: unify live signal-gen with BT generate_signals (drift bug #7 fix)` | git | pushed |

**Done when:** parity harness shows 100% signal match for Oil Macro on Jun 11–18 + 2 historical weeks; BT now runs the live TP formula.

**Critical decision in 2.1:** which TP formula is "right"? The live formula (`asia_high − tp_buf`) is what's been running in production for months. The BT formula (`entry + range × multi`) is what F28 multi-seed validation was based on. **Pinning live's formula on BT is the safer move** — production has been running on it, BT was the outlier. Document the F28 numbers will shift slightly (re-run multi-seed post-fix is a Phase 6 item).

---

## Phase 3 — Gold Macro (2h)

**Why next:** TP formula already in parity (cleanest refactor). D3 cross-strategy lock is preserved. Mainly a wiring exercise.

### Tasks

| # | Task | Files | Verification |
|---|---|---|---|
| 3.1 | Refactor `_run_alpha_sweep_core` to call `alpha_sweep.generate_signals(h1_df, m3_df, daily_bias)` | `backend/scanner/scheduler.py:408-786` | dry_run signals match BT |
| 3.2 | Cross-strategy lock (D3 — `strategy IN ('alpha_sweep', 'mean_rev', 'cross_market')`) preserved in scheduler, NOT in strategy module | scheduler.py:466-474 | confirmed via grep |
| 3.3 | Verify D8 OANDA `dailyAlignment=21` daily-bias slicing — pull live `gd_signals` rows around daily-close boundary, confirm `bias` matches BT for same date | manual audit | resolution either parity or documented divergence |
| 3.4 | Add `tests/harness/parity/test_gold_macro_parity.py` — runs BT + live on Jun 11–18 + 2025 sample week | new test | passes |
| 3.5 | Commit + push with message `Gold Macro: unify live signal-gen with BT generate_signals` | git | pushed |

---

## Phase 4 — Gold Micro (2.5h)

**Why next:** D3 + D4 (window-iteration + dedup keying) are unique to rolling-window architecture. Fix here informs Oil Micro.

### Tasks

| # | Task | Files | Verification |
|---|---|---|---|
| 4.1 | **Fix D2 (config-key drift):** in `backend/strategies/micro_alpha_sweep.py:42-223`, replace `cfg["asia_min_range"]` with `cfg["min_range"]`. Document the alias chain (`MICRO_ALPHA_SWEEP["min_range"]` is the source of truth). | strategy file | grep confirms no `asia_min_range` references in micro path |
| 4.2 | **Fix D4 (dedup keying):** standardize on `(sbar_ts, start_hour)` per-window tuple in BOTH BT and live. Update `scheduler.py:382` to use `(bar['timestamp'], window['start_hour'])`. Update `is_sweep_consumed`/`mark_sweep_consumed` callers to pass the same tuple. | scheduler.py + db.py | dedup parity test passes |
| 4.3 | Refactor `_run_micro_sweep_core` to call `micro_alpha_sweep.generate_signals(h1_df, m3_df, daily_bias)` | `backend-micro/scanner/scheduler.py:184-571` | dry_run signals match BT |
| 4.4 | Production gates wrap: cooldown, open-position DB+MT5 blocker, daily cap, persistent sweep blacklist (with new keying) | scheduler.py | each tested |
| 4.5 | Live still iterates active windows on cron tick, but each window's signal-gen is now via the unified call | scheduler.py | architectural review |
| 4.6 | Add `tests/harness/parity/test_gold_micro_parity.py` | new test | passes including overlapping-window same-direction sweep case |
| 4.7 | Commit + push with message `Gold Micro: unify live signal-gen + fix D2 config-key + D4 dedup keying` | git | pushed |

---

## Phase 5 — Oil Micro (3h, biggest because needs strategy extraction)

**Why last:** Oil Micro has its `generate_signals` inlined in `backend-oil-micro/backtest/engine.py:72-226` instead of in a separate `strategies/` file. Extract first, then refactor.

### Tasks

| # | Task | Files | Verification |
|---|---|---|---|
| 5.1 | **Extract `generate_signals` to its own file:** create `backend-oil-micro/strategies/__init__.py` and `backend-oil-micro/strategies/micro_alpha_sweep_oil.py`. Move the function + Signal dataclass. | new file | `from strategies.micro_alpha_sweep_oil import generate_signals` works in engine.py and scheduler.py |
| 5.2 | Update `backend-oil-micro/backtest/engine.py:158` to import from new location | engine.py | BT still produces same signals as before extraction |
| 5.3 | Re-run Phase 0 baseline for Oil Micro post-extraction — verify zero drift | scripts/output | match |
| 5.4 | **Fix D9 (hardcoded `range(2, ...)`):** replace with `range(2 if cfg["skip_first_bar"] else 1, ...)` in `scheduler.py:396` | scheduler.py | grep confirms no hardcoded `2` |
| 5.5 | Refactor `_run_micro_sweep_core` to call `generate_signals(h1_df, m3_df, daily_bias)` | `backend-oil-micro/scanner/scheduler.py:156-525` | dry_run signals match BT |
| 5.6 | Production gates wrap (same as Gold Micro): cooldown, open-position DB+MT5, daily cap, persistent blacklist, startup cooldown | scheduler.py | each tested |
| 5.7 | **D5 dedup keying:** apply same fix as Gold Micro (per-window tuple `(sbar_ts, start_hour)`) | scheduler.py | dedup parity |
| 5.8 | Add `tests/harness/parity/test_oil_micro_parity.py` — Jun 11–18 + 2024 random week | new test | passes |
| 5.9 | Commit + push with message `Oil Micro: extract strategy + unify live signal-gen + fix D5 dedup + D9 range hardcode` | git | pushed |

---

## Phase 6 — Cross-system safety review (1h)

### Tasks

| # | Task | Files | Verification |
|---|---|---|---|
| 6.1 | **D4 Oil Micro: account-wide MT5 lock** — decide: keep as-is (cross-system safety) OR strategy-filter (Oil Micro only blocks on `OIL-MI-%` open trades). User decides. | scheduler.py | decision logged in PARITY_BASELINE.md |
| 6.2 | **D3 Gold Macro: cross-strategy lock** — same question. Currently blocks Alpha-Sweep on any open `mean_rev` / `cross_market` trade. Keep or change? | scheduler.py | decision logged |
| 6.3 | **D8 Gold Macro: OANDA daily-bar alignment** — verify resolved in Phase 3. If not, fix here. | scheduler.py | match |
| 6.4 | Re-run F28 multi-seed validation post-Phase 2 TP-formula fix (Oil Macro BT now uses live formula) — record new numbers | F28 sweep script | new baseline document |

**Decision points 6.1 + 6.2 affect signal counts.** Document trade-offs:

- Keep cross-system locks → safer (one stuck trade can't blow up). More dropped signals, BT vs live still has structural divergence. Live conservatism wins.
- Strategy-filter the locks → BT and live behave identically. More signals fire. Higher risk if a trade gets stuck.

Recommended (caveman): **keep cross-system locks for safety**, document them as deliberate live-only overrides in PARITY_BASELINE.md. Then BT can be re-run with the same lock simulated if you want true parity.

---

## Phase 7 — Production smoke test (1h)

### Tasks

| # | Task | How |
|---|---|---|
| 7.1 | Deploy refactored code to VPS (`git pull` + `start-win.bat`) | manual |
| 7.2 | Watch each system's first scheduler tick post-deploy — confirm signals fire (or not) for the right reason. Tail Telegram + journal events. | live observation |
| 7.3 | Run parity harness on VPS data (last 24hr) — confirm BT and live agree on what should have been signaled | parity harness output |
| 7.4 | If any system mismatches → roll back to prev commit, debug, re-deploy | git revert |
| 7.5 | If all systems pass → mark refactor complete, update CLAUDE.md if needed | git push |

**Done when:** all 4 systems live, parity harness green on VPS data, no mismatch.

---

## Phase 8 — Flip dry-run → live (real-time)

If any system was deployed with `dry_run=True` mode for safety:

### Tasks

| # | Task | When |
|---|---|---|
| 8.1 | Per system: confirm dry_run dashboard shows correct signal generation for 24h | 1 day post-Phase 7 |
| 8.2 | Flip dry_run → False per system, one at a time, 6h apart | spread over Mon Jun 22 |
| 8.3 | Watch first real trade fire on refactored code — verify entry, SL, TP, journal events match expected | live observation |
| 8.4 | Update memory: drift bug #7 closed | `bug_live_bt_parity_gap.md` |

---

## Verification — what proves we're done

After all 8 phases:

1. **Code:** every scheduler imports `generate_signals` from its strategy module (verifiable via `grep -r "generate_signals" backend*/scanner/scheduler.py`)
2. **Tests:** 4 parity harness tests pass; runs in CI
3. **Behavior:** Day 1 of post-refactor 30-day challenge — BT-vs-live divergence count = 0 (target: zero "live signal not in BT" / "BT signal not in live" events)
4. **Memory:** `[[project-live-backtest-parity-gap]]` updated to "RESOLVED 2026-06-21" with reference to this plan

---

## Phase-by-phase commit messages (for reference)

| Phase | Commit message |
|---|---|
| 0 | `RCA: Phase 0 baseline parity snapshot — pre-refactor signal divergence numbers` |
| 1 | `Add broker_to_dataframe adapter for DWX/OANDA → BT-format DataFrame` |
| 2 | `Oil Macro: unify live signal-gen with BT generate_signals + pin TP formula (drift bug #7 fix)` |
| 3 | `Gold Macro: unify live signal-gen with BT generate_signals` |
| 4 | `Gold Micro: unify live signal-gen + fix D2 config-key + D4 dedup keying` |
| 5 | `Oil Micro: extract strategy + unify live signal-gen + fix D5 dedup + D9 range hardcode` |
| 6 | `Cross-system safety review: log decisions on cross-strategy / cross-system locks` |
| 7 | `Refactor verification: parity harness green on VPS data` |

---

## What this plan does NOT cover (out of scope)

- Filter #27 limit-order live state machine (DWX file races, grace, reconciliation) — already shared `compute_limit_price`, the rest stays in `live_engine.py`
- Filter #28 dormant rollout (already wired to BT routes Jun 18, separate concern)
- F29 (bar-aware BE) — research stays parked
- Bug #1 (phantom BE-arm trigger_price) — diagnostic logging already shipped, RCA continues separately
- Cap rework already shipped Jun 18

---

## Open questions for user before starting

1. **Phase 2.1 — TP formula choice:** pin BT to live's `asia_high − tp_buf` formula? (Recommendation: yes — production has been running on it, BT was the outlier.)
2. **Phase 6.1 — Oil Micro MT5 cross-lock:** keep account-wide lock (Oil Macro position blocks Oil Micro)? (Recommendation: yes for safety, document as deliberate override.)
3. **Phase 6.2 — Gold Macro cross-strategy lock:** keep `alpha_sweep + mean_rev + cross_market` interlock? (Recommendation: yes for safety.)
4. **Refactor timing:** start Sat Jun 20 morning, target Sun Jun 21 EOD complete. Day 1 of 30-day challenge starts Mon Jun 22.

---

## Files created by this plan

- `backend/scanner/broker_to_dataframe.py` — adapter (Phase 1)
- `backend-oil-micro/strategies/__init__.py` — new (Phase 5)
- `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` — new (Phase 5)
- `tests/test_broker_to_dataframe.py` — adapter tests (Phase 1)
- `tests/harness/parity/test_oil_macro_parity.py` — Phase 2
- `tests/harness/parity/test_gold_macro_parity.py` — Phase 3
- `tests/harness/parity/test_gold_micro_parity.py` — Phase 4
- `tests/harness/parity/test_oil_micro_parity.py` — Phase 5
- `docs/30-day-challenge/reports/PARITY_BASELINE.md` — Phase 0 + 6
- `scripts/output/baseline_*_<system>.json` — Phase 0 artifacts

## Files modified by this plan

- `backend-oil/strategies/alpha_sweep.py` — Phase 2.1 (TP formula)
- `backend-oil/scanner/scheduler.py` — Phase 2.3-2.5
- `backend/scanner/scheduler.py` — Phase 3.1-3.2
- `backend/strategies/micro_alpha_sweep.py` — Phase 4.1
- `backend-micro/scanner/scheduler.py` — Phase 4.3
- `backend-oil-micro/backtest/engine.py` — Phase 5.2
- `backend-oil-micro/scanner/scheduler.py` — Phase 5.4-5.7
- `backend/db.py` — Phase 4.2 (`is_sweep_consumed`/`mark_sweep_consumed` keying)
