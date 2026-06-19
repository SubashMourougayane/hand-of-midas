# Audit 2026-06-15 — Dedup-Class Silent-Fail Bugs

**Trigger:** Gold Macro fired 3 trades on one Asia sweep (10:51, 12:36, 12:42) because `live_engine.py:189` had a dead dedup query (`LIKE 'GD-AS-%'` vs actual `GD-AL-` refs). Dead since commit `93f3eae` 2026-05-28. Fixed in `5c86466`.

**Scope:** Audit four parallel agents identified 24 issues of the same class (silent guards, scope-mismatched queries, hardcoded fallbacks, dead error paths) across all 4 backends.

**Framework per issue:**
1. **RCA** — read the actual code, confirm whether the agent's claim holds.
2. **Cross-check** — does the same pattern exist in the other 3 backends?
3. **Verdict** — REAL / NOT-REAL / PARTIAL (with reason).
4. **Fix** — if real, propose minimal change, ship, verify on VPS or in tests.
5. **Sign-off** — record final state in this doc.

**Backends audited:**
- `backend/` (Gold Macro)
- `backend-oil/` (Oil Macro)
- `backend-micro/` (Gold Micro)
- `backend-oil-micro/` (Oil Micro)

---

## Status legend

- ⏳ pending — not yet investigated
- 🔍 investigating — RCA in progress
- ✅ fixed — root cause confirmed and patched
- 🟢 not-an-issue — investigated, no actual bug
- ⚠️ partial — partial issue, partial fix or accepted-as-is
- 🚫 won't-fix — confirmed but conscious deferral

---

## CRITICAL — duplicate-trade or wrong-size class

### #1 — `execute_signal` has no open-position guard in 3 of 4 backends

**Status:** ✅ fixed (commit `ae63a77`)
**Files:**
- `backend-micro/scanner/live_engine.py:108` — `execute_signal` for Gold Micro
- `backend-oil/scanner/live_engine.py:113` — `execute_signal` for Oil Macro
- `backend-oil-micro/scanner/live_engine.py:101` — `execute_signal` for Oil Micro

**Claim:** Only Gold Macro has dedup guard inside `execute_signal`. Other three rely entirely on scheduler-level guard.

**RCA:**
- Read all 4 backends. Confirmed: only `backend/scanner/live_engine.py:187` (Gold Macro) has the in-function dedup guard. The other 3 flow from skip checks → broker order with no second check.
- Scheduler-level guards DO exist in all 3 (`scheduler.py:147` for oil, `scheduler.py:347` for micro, `scheduler.py:303` for oil-micro), and they use the correct prefix:
  - Oil Macro: `LIKE 'OIL-AS-%'` matches generated `f"OIL-AS-{uuid}..."` ✓
  - Gold Micro: `LIKE '{TRADE_REF_PREFIX}%'` where `TRADE_REF_PREFIX = "GD-MI-"` matches gen ✓
  - Oil Micro: `LIKE '{TRADE_REF_PREFIX}%'` where `TRADE_REF_PREFIX = "OIL-MI-"` matches gen ✓
- All 3 use config constants (or hardcoded matching the generator), so no GD-AS-style drift.

**Cross-check:** Bug class is only Gold Macro. Other 3 dedups are correct *as written*. **However**, defense-in-depth is missing — if any future caller bypasses scheduler (orphan adoption, debug API exec, refactor), there's no second line.

**Verdict:** REAL (defense-in-depth gap), not a live bug today.

**Fix:** Mirror the Gold Macro guard pattern into all 3 backends. Each guard uses the same prefix the scheduler does (config constant or hardcoded matching gen), so it can't drift. Inserted just before `place_market_order` call in each `execute_signal`.

**Test:**
- `python3 -m ast` parses all 3 modified files OK.
- VPS deployed via debug API; `findstr` confirms `position_already_open` skip_reason present in all 3 files on disk.
- Will activate on next service restart.

**Commit:** `ae63a77`


---

### #2 — Adaptive sizing queries leak across systems

**Status:** ✅ fixed (commit `3132c45`)
**Files:**
- `backend/scanner/live_engine.py:100` (Gold Macro) — **WORSE than reported: NO prefix filter, reads ALL systems**
- `backend-oil/scanner/live_engine.py:100` (Oil Macro) — `LIKE 'OIL-%'` reads OIL-AS- + OIL-MI-

**Claim:** `LIKE 'OIL-%'` matches both Oil Macro and Oil Micro. Equity-MA polluted.

**RCA:**
- Confirmed Oil Macro: `LIKE 'OIL-%%'` matches `OIL-AS-` (macro) + `OIL-MI-` (micro). Risk-halving decision factored in Micro outcomes.
- **Gold Macro is worse** (agent missed): query at `backend/scanner/live_engine.py:101` has no `WHERE trade_ref LIKE` filter at all — reads last 20 closed trades across **all 4 systems**. Gold Macro's risk-halving was a function of *every* system's P&L.

**Cross-check:**
- Gold Micro (`backend-micro/scanner/live_engine.py`): uses `LIKE '{TRADE_REF_PREFIX}%%'` (= `GD-MI-%`). ✓ correct, micro-only.
- Oil Micro (`backend-oil-micro/scanner/live_engine.py`): uses `LIKE '{TRADE_REF_PREFIX}%%'` (= `OIL-MI-%`). ✓ correct, micro-only.
- Both Macros leaked; both Micros are clean.

**Verdict:** REAL. Wider impact than agent reported (Gold Macro had no filter at all).

**Fix:** scope each macro query to its own strategies via `strategy IN (...)` / `strategy = ...` (same pattern as the dedup fix). Cannot drift like prefix LIKEs can.

**Test:** AST parse OK. Manually verified queries return only macro rows by inspection of strategy column values (see Issue #0 audit context: distinct strategies are `alpha_sweep`, `alpha_sweep_oil`, `micro_alpha_sweep`, `micro_alpha_sweep_oil`).

**Commit:** `3132c45`


---

### #3 — Gold Macro daily recon Telegram includes Gold Micro

**Status:** ✅ fixed (commit `0a392a0`)
**File:** `backend/scanner/scheduler.py:835`

**Claim:** `daily_recon_stats("GD-%", ...)` matched GD-MI- too.

**RCA:**
- Confirmed: `backend/db.py:184` has `WHERE trade_ref LIKE %s` — passing `"GD-%"` matches all GD- prefixes including Micro.
- The `count_event` calls inside use `strategy = 'alpha_sweep'` exactly, so error/orphan counts were correct, but `total_trades` + `net_pnl` were polluted.

**Cross-check:** Confirmed all 4 systems' recon calls:
- Gold Macro: `"GD-%"` ❌
- Gold Micro: `"GD-MI-%"` ✓
- Oil Macro: `"OIL-AS-%"` ✓
- Oil Micro: `"OIL-MI-%"` ✓

**Verdict:** REAL. Gold Macro only.

**Fix:** Extended `daily_recon_stats()` with optional `strategies=[...]` parameter. When passed, adds `AND strategy IN (...)` to the trades query. Gold Macro caller now passes `["alpha_sweep","mean_rev","cross_market"]`. Other 3 systems left unchanged (their LIKE patterns are already correct).

**Test:** AST parse OK. The new SQL builds correctly: f-string interpolates only `%s` placeholders (no user input), strategy values pass through standard psycopg parameterization.

**Commit:** `0a392a0`


---

### #4 — Trades API + state/stream routes drop mean_rev/cross_market

**Status:** ✅ fixed (commit `9959e4b`)
**Files:**
- `backend/routes/trades.py:95` — `LIKE 'GD-AL-%'`
- `backend/routes/state.py:71` — typo `'mean_reversion'` (long form)
- `backend/routes/stream.py:186, 205` — same `'mean_reversion'` typo

**RCA:**
- `trades.py:95` confirmed: `LIKE 'GD-AL-%%'` matches alpha_sweep only.
- **state.py and stream.py** have a related typo (agent missed): they use `IN ('alpha_sweep', 'mean_reversion', 'cross_market')` but the actual strategy values used in code are `'mean_rev'` (see `backend/strategies/mean_rev.py:61`). So mean_rev open trades would never appear on /live page even though state.py/stream.py *intended* to include them.
- DB query confirmed: distinct strategy values in production are `alpha_sweep`, `alpha_sweep_oil`, `micro_alpha_sweep`, `micro_alpha_sweep_oil` — `mean_rev` and `cross_market` have never executed in production. So the typos were latent.

**Cross-check:** Oil/Micro routes use a single strategy each, no IN-list typo possible.

**Verdict:** REAL but **latent** (mean_rev/cross_market never ran). Fix is forward-compatibility for when they activate.

**Fix:** trades.py switched to `strategy IN ('alpha_sweep', 'mean_rev', 'cross_market')`. state.py and stream.py corrected `'mean_reversion'` → `'mean_rev'`.

**Commit:** `9959e4b`


---

### #5 — Oil Macro UI/state/stream routes show Micro trades mixed in

**Status:** ✅ fixed (commit `be2d83e`)
**Files:** `backend-oil/routes/state.py`, `stream.py`, `trades.py` — 5 queries.

**RCA:** All confirmed: each uses `LIKE 'OIL-%%'` with no strategy filter. Oil Macro UI showed Micro trades mixed in.

**Cross-check:** Gold Macro routes use a clean `strategy IN (...)` filter; oil-micro routes use `TRADE_REF_PREFIX` constant (`OIL-MI-`) which matches generation. Issue is Oil Macro routes only.

**Verdict:** REAL.

**Fix:** Switch all 5 to `strategy = 'alpha_sweep_oil'`.

**Commit:** `be2d83e`


---

### #6 — Hardcoded $10,000 equity fallback + missing sanity floor

**Status:** ✅ fixed (commit `f10eb81`)
**Files:** all 4 backend `live_engine.py` files

**RCA:**
- Gold Micro line 142: `or` chain falls back to 10000 if all NAV fields are 0/falsy.
- Oil Micro line 129: same pattern.
- Gold Macro and Oil Macro use `acct.get("nav_usd", acct.get("nav", float(dd_state["equity"])))` — safer (uses tracked equity) but no sanity floor.

**Cross-check:** Both Micros vulnerable to the $10k fallback; both Macros have no floor.

**Verdict:** REAL.

**Fix:**
- Micros: replace `or 10000` with `or float(dd_state["equity"])`.
- All 4: add `if equity_usd < 100: skip(equity_too_low)`. Refuses the trade rather than silently sizing on a phantom amount.

**Commit:** `f10eb81`


---

### #7 — `place_market_order` returns success on malformed EA response

**Status:** ✅ fixed (commit `e409ecf`)
**File:** `backend/execution/mt5_executor.py:353-370`

**RCA:** Confirmed: `success` path uses `response.get("ticket", 0)` and `response.get("price", 0)` — defaults silently mask bad EA replies.

**Cross-check:** Single shared file used by all 4 backends. One fix covers all.

**Verdict:** REAL.

**Fix:** After `success=True` branch, validate `ticket > 0` and `price > 0`. If either fails, log full response and return `success=False`. Caller treats as order failure (already handled by existing error path).

**Commit:** `e409ecf`


---

## HIGH — silent-fail surfaces, dependent-state bugs

### #8 — 5-min cooldown is too short for the engulfing window

**Status:** ⚠️ accepted-as-is (post-#1 fix)
**File:** `backend/scanner/scheduler.py:454` and 3 mirrors

**RCA:**
- Confirmed all 4 backends use `timedelta(minutes=5)` for cooldown.
- Today's failure: entry #2 → entry #3 at T+6min on same Asia sweep, both passed cooldown.
- BUT: with Issue #1 fixed, both #2 and #3 would be blocked by the new `position_already_open` dedup check before reaching the broker.
- The cooldown is a fallback for the case where position #1 has already closed (SL'd) by the time the next signal fires.

**Cross-check:** all 4 backends have same 5min logic.

**Verdict:** NOT-A-LIVE-BUG post-Issue #1.
- Today's specific incident is fully mitigated by Issue #1's dedup guard + Issue #9's sweep blacklist (when persisted).
- 5min is the right value for protecting against duplicate cron ticks (the original intent).
- Extending to 60min would block legitimate re-entry if SL hits early in session and a new sweep occurs same day. That's actually undesirable.

**Fix:** none. Cooldown stays at 5min, justified by the post-#1 dedup defense-in-depth.

**Decision recorded in doc**, not deployed.


---

### #9 — Sweep blacklist in-memory only

**Status:** ✅ fixed (commit `a625954`)
**Files:** all 4 schedulers + `database/schema.sql` + `backend/db.py`

**RCA:** Confirmed: each scheduler keeps `_traded_sweeps_*` as a module-level dict with a `keys: set()` member. Restart wipes this. Same Asia wick could re-fire after a restart.

**Cross-check:** All 4 backends had identical pattern.

**Verdict:** REAL.

**Fix:**
- New table `gd_traded_sweeps(system, date, sweep_key, consumed_at)` with `UNIQUE(system, date, sweep_key)`.
- Helpers `is_sweep_consumed()` + `mark_sweep_consumed()` in `backend/db.py`.
- All 4 schedulers: lookup checks DB if not in hot cache; consume writes to BOTH memory and DB. Failures to persist are logged but don't crash the scan loop.
- Schema migration applied to VPS via debug API.

**Commit:** `a625954`


---

### #10 — Cooldown only counts limited skip reasons

**Status:** ⚠️ accepted-as-is (post-#1 + #9)
**File:** `backend/scanner/scheduler.py:453`

**RCA:** Confirmed: cooldown extends only on `taken`, `order_error`, `sl_too_close`. `position_already_open` does NOT extend.

**Cross-check:** All 4 schedulers same pattern.

**Verdict:** NOT-A-LIVE-BUG post-#1 + #9.
- Concern was that a position closes → new signal fires immediately because cooldown didn't extend.
- Post-#9, the persistent sweep blacklist blocks any new entry on the same Asia sweep_key regardless of cooldown.
- A *different* sweep firing within seconds is correct behavior (different setup). The cooldown's job is only to throttle bursts, not to enforce single-position-per-sweep.

**Fix:** none. Documented decision.


---

### #11 — `_get_gbp_usd_rate` falls back to hardcoded 1.33 silently

**Status:** ✅ fixed (commit `4873e9a`)
**File:** `backend/execution/oanda_executor.py:81-87`

**RCA:** Confirmed: 4 silent fallbacks in 12 lines. Currently broker is JustMarkets/MT5 (USD account, hardcoded `gbp_usd_rate: 1.0`), so this path is dormant.

**Cross-check:** Single shared file. MT5 path doesn't use it.

**Verdict:** REAL but dormant.

**Fix:** Log `_log.warn("BROKER", "gbp_usd_rate_fallback", reason=...)` on every fallback hit. Behavior unchanged when broker responds; failures become loud.

**Commit:** `4873e9a`


---

### #12 — `_get_dd_state` returns hardcoded default if row missing

**Status:** ✅ fixed (commit `b6b0dbe`)
**File:** `backend/scanner/live_engine.py:64-66`

**RCA:** Confirmed silent fallback to `{equity: 5000, peak_equity: 5000}` doesn't match any real account.

**Cross-check:** Other 3 backends already self-heal via `INSERT ... ON CONFLICT DO NOTHING` then re-read. Gold Macro was the outlier.

**Verdict:** REAL.

**Fix:** Align Gold Macro to other 3 — emit error log, attempt self-heal INSERT, re-read. If still fails, return zeros (fail-closed: Issue #6's $100 floor blocks all trades on equity=0).

**Commit:** `b6b0dbe`


---

### #13 — `notify.py` swallows all Telegram errors with `except: pass`

**Status:** ✅ fixed (commit `1620edc`)
**File:** `backend/notify.py:14-23`

**RCA:** Confirmed bare `except Exception: pass`. Import-time would also pass even if BOT_TOKEN empty.

**Cross-check:** Single shared file; covers all 4 backends.

**Verdict:** REAL.

**Fix:**
- Import-time check + stderr warning if BOT_TOKEN/CHAT_ID missing.
- Three failure-mode logs: empty-token, HTTP non-200, exception.
- Rate-limited (first 3 + every 50th) so spam doesn't drown logs.
- No heartbeat added (would require new scheduler job; deferred — visible failures cover the main concern).

**Commit:** `1620edc`


---

### #14 — EXIT_AMBIGUOUS streak alert wrapped in `except Exception: pass`

**Status:** ✅ fixed (commit `9c34ebe`)
**Files:** `backend/scanner/live_engine.py:373-380` and `backend-oil/scanner/live_engine.py` mirror

**RCA:** Confirmed bare pass. Alert only fires once per streak (`streak == ALERT_CYCLES`); if notify.error raises at that exact boundary, alert is lost forever.

**Cross-check:** Gold Macro and Oil Macro have this path; Micros don't.

**Verdict:** REAL.

**Fix:** Log exception + decrement streak by 1 so next cycle re-tries at threshold.

**Commit:** `9c34ebe`


---

### #15 — `_log_journal_safe` swallows DB exceptions to `print()`

**Status:** ✅ fixed (commit `6ef6a97`)
**File:** all 4 backend `live_engine.py` files

**RCA:** Confirmed all 4 backends had `except Exception as e: print(...)` only.

**Cross-check:** identical pattern in all 4.

**Verdict:** REAL.

**Fix:** Add `_log.exception("JOURNAL", "log_journal_failed", ...)` before the print. Visible in debug API + log files now.

**Commit:** `6ef6a97`


---

### #16 — `reconcile_orphans` early-returns silently on empty broker response

**Status:** ✅ fixed (commit `ca5d048`)
**Files:** all 4 `live_engine.py`

**RCA:** Confirmed `if not broker_open: return` had no log. Could be normal or file-race. Indistinguishable.

**Cross-check:** All 4 backends had identical pattern.

**Verdict:** REAL.

**Fix:** When broker_open is empty, query DB for open trades scoped to this system. If DB shows open but broker shows none → log `_log.warn("reconcile_empty_but_db_has_open")`. Now visible.

**Commit:** `ca5d048`


---

### #17 — Gold Macro DD state shared across 3 strategies

**Status:** 🚫 won't-fix (deferred until mean_rev/cross_market activate)
**File:** `backend/scanner/live_engine.py` — `gd_dd_state` row id=1

**RCA:** Confirmed: `_get_dd_state()` and `_update_dd_state()` use a single `id=1` row across alpha_sweep, mean_rev, cross_market.

**Cross-check:** Oil Macro/Micro/Oil-Micro use separate ids (2/3/4) — proper isolation. Gold Macro is the outlier because it has 3 sub-strategies sharing one slot.

**Verdict:** PARTIAL — design ambiguity, not a live bug.
- Production reality: only `alpha_sweep` has ever executed (confirmed via `SELECT DISTINCT strategy FROM gd_trades`). The shared row is effectively the alpha_sweep row.
- If `mean_rev` or `cross_market` is ever activated, decide then whether they should share or have separate rows.

**Fix:** None today. Documented decision. Reopen when mean_rev/cross_market ship.


---

### #18 — Oil Micro `gd_dd_state` row 4 not in schema

**Status:** ✅ fixed (commit `c891380`)
**File:** `database/schema.sql:154-157`

**RCA:** Confirmed schema only had INSERT for ids 1, 2, 3. Oil Micro uses 4. Migration on VPS confirmed row 4 was actually missing (now created with defaults).

**Cross-check:** All 4 backends now have a row.

**Verdict:** REAL.

**Fix:** Add `INSERT INTO gd_dd_state (id) VALUES (4) ON CONFLICT DO NOTHING` to schema.sql. Migration applied on VPS via debug API.

**Commit:** `c891380`


---

## LOWER — code smells, fragile-but-working

### #19 — `"order_error" in skip` substring match

**Status:** ✅ fixed (commit `c80ac6b`)
**Files:** all 4 schedulers

**RCA:** Confirmed substring match. Today's skip reasons don't include `"no_order_error"` so safe in practice, but fragile.

**Cross-check:** Same pattern in all 4.

**Verdict:** REAL (latent).

**Fix:** Use `startswith("order_error")` and `startswith("oanda_error")` for the prefix-match cases; exact `==` for `sl_too_close_to_price`.

**Commit:** `c80ac6b`


---

### #20 — f-string SQL with `TRADE_REF_PREFIX` constant

**Status:** 🟢 not-an-issue
**Files:** `backend-micro/scanner/scheduler.py:199, 348` and equivalents

**RCA:** `TRADE_REF_PREFIX` is a module-level constant from `config.py`. Never user-influenced. f-string interpolation is fine.

**Verdict:** NOT-A-BUG. Defensive fix would be to use `%s` parameterization, but the gain is theoretical and the cost is N call sites. Keep as-is.


---

### #21 — Bare `except:` in M3 candle audit

**Status:** ✅ fixed (commit `91960f9`)
**File:** `backend/scanner/scheduler.py:753`

**RCA:** Confirmed bare `except:`. Forensic-only.

**Cross-check:** Gold Macro only.

**Verdict:** REAL.

**Fix:** Catch `Exception as e`, swallow as before (forensic-only), but `_log.exception` for visibility.

**Commit:** `91960f9`


---

### #22 — DWX `last_response.json` parse errors swallowed

**Status:** 🟢 not-an-issue
**File:** `backend/execution/mt5_executor.py:131-132`

**RCA:** Confirmed bare `except: pass` inside a retry loop. Behavior: read → if parse fails, retry; eventually `return None` after timeout. Every parse failure during a file race is **expected** — the file is being written by the EA at exactly that moment.

**Verdict:** NOT-A-BUG. Adding a log would spam logs during normal operation. The timeout-then-None contract is sufficient — caller already handles `None` as "broker timeout."


---

### #23 — `_parse_mt5_time` falls back to `datetime.now()` on parse failure

**Status:** ✅ fixed (commit `eb8ac43`)
**File:** `backend/execution/mt5_executor.py:184`

**RCA:** Confirmed bare `except: return datetime.now()`. Function has NO callers today.

**Cross-check:** Single shared file.

**Verdict:** REAL but dormant.

**Fix:** Log warning before fallback.

**Commit:** `eb8ac43`

---

### #24 — Orphan ref hardcoded as `f"GD-AL-orphan-..."` regardless of actual strategy

**Status:** ✅ fixed (commit `8daa5b6`)
**File:** `backend/scanner/live_engine.py:719`

**RCA:** Confirmed: ref + strategy hardcoded to `alpha_sweep`. The broker `comment` field (`"{strategy}|{trade_ref}"`) had the actual strategy but wasn't parsed.

**Cross-check:**
- Oil Macro hardcodes `OIL-AS-orphan` — correct (only one strategy: alpha_sweep_oil).
- Gold Micro / Oil Micro use TRADE_REF_PREFIX — correct (only one strategy each).
- Gold Macro is the only multi-strategy backend.

**Verdict:** REAL but latent (mean_rev/cross_market never running in prod).

**Fix:** Parse `comment` for strategy name. If matches one of `('alpha_sweep','mean_rev','cross_market')`, use it; else default to `alpha_sweep`. ref_prefix derived via same `f"GD-{strategy[:2].upper()}"` formula as gen.

**Commit:** `8daa5b6`


---

## Final tally

- ✅ **20 fixed** (real bugs patched + shipped to VPS)
- ⚠️ **2 accepted-as-is** (concerns covered by other fixes — #8 cooldown, #10 cooldown skip-reasons)
- 🟢 **2 not-a-bug** (#20 f-string with constant, #22 retry-loop bare except is intentional)
- 🚫 **0 wont-fix as-bug** but #17 deferred until mean_rev/cross_market activate

**Commits shipped (16):** `5c86466`, `ae63a77`, `3132c45`, `0a392a0`, `9959e4b`, `be2d83e`, `f10eb81`, `e409ecf`, `a625954`, `4873e9a`, `b6b0dbe`, `1620edc`, `9c34ebe`, `6ef6a97`, `ca5d048`, `c891380`, `c80ac6b`, `91960f9`, `eb8ac43`, `8daa5b6`

All on `midas-deploy`, all pulled to VPS. Will activate at next service restart.

## Summary table

| # | Severity | Status | Real? | Fix commit | Notes |
|---|---|---|---|---|---|
| 1 | 🔴 | ✅ | yes (def-in-depth gap) | ae63a77 | guards added to oil, micro, oil-micro execute_signal |
| 2 | 🔴 | ✅ | yes (worse than reported — Gold had no filter) | 3132c45 | scoped Gold + Oil Macro adaptive sizing queries |
| 3 | 🔴 | ✅ | yes (Gold Macro only) | 0a392a0 | extended daily_recon_stats with strategies kwarg |
| 4 | 🔴 | ✅ | yes (latent — mean_rev/cross_market unused) | 9959e4b | trades.py LIKE→IN; state/stream `mean_reversion` typo fixed |
| 5 | 🔴 | ✅ | yes | be2d83e | Oil Macro routes scoped to alpha_sweep_oil |
| 6 | 🔴 | ✅ | yes | f10eb81 | $10k fallback removed; $100 floor added in all 4 backends |
| 7 | 🔴 | ✅ | yes | e409ecf | EA response validated; ticket/price > 0 required |
| 8 | 🟡 | ⚠️ | not-a-live-bug post-#1 | - | accepted; cooldown stays 5min, defense covered by #1 + #9 |
| 9 | 🟡 | ✅ | yes | a625954 | gd_traded_sweeps table + DB-backed in all 4 schedulers |
| 10 | 🟡 | ⚠️ | not-a-live-bug post-#1+#9 | - | covered by sweep blacklist |
| 11 | 🟡 | ✅ | yes (dormant on MT5) | 4873e9a | log every fallback to 1.33 |
| 12 | 🟡 | ✅ | yes (Gold Macro outlier) | b6b0dbe | self-heal pattern matching other 3 backends |
| 13 | 🟡 | ✅ | yes | 1620edc | rate-limited stderr logs on every failure mode |
| 14 | 🟡 | ✅ | yes | 9c34ebe | log + retry on next cycle (streak decrement) |
| 15 | 🟡 | ✅ | yes | 6ef6a97 | _log.exception added across 4 backends |
| 16 | 🟡 | ✅ | yes | ca5d048 | smell detector: warn when broker empty but DB has open |
| 17 | 🟡 | 🚫 | partial / deferred | - | only alpha_sweep runs in prod; reopen if mean_rev/cross_market activate |
| 18 | 🟡 | ✅ | yes (row was missing) | c891380 | row 4 inserted; schema updated |
| 19 | 🟢 | ✅ | yes (latent) | c80ac6b | startswith + exact match in all 4 |
| 20 | 🟢 | 🟢 | not-a-bug | - | constant from config; no user input ever |
| 21 | 🟢 | ✅ | yes | 91960f9 | logged but still swallowed (forensic only) |
| 22 | 🟢 | 🟢 | not-a-bug | - | retry loop with timeout-then-None is correct |
| 23 | 🟢 | ✅ | yes (dormant — no callers) | eb8ac43 | log warn before fallback to now() |
| 24 | 🟢 | ✅ | yes (latent) | 8daa5b6 | parse strategy from broker comment |
