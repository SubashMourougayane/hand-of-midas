# Filter #27 — Vigilant Audit Backlog

**Status:** Live with Fix B/C/A pending sign-off (see [BUG_FILTER_27_PENDING_RECONCILER_GAP.md](./BUG_FILTER_27_PENDING_RECONCILER_GAP.md))
**Audit date:** 2026-06-17
**Auditors:** 4 parallel detective agents covering ENTRY · FILL+EXIT · EA+SCHEDULER · OBSERVABILITY
**Scope:** every code path from signal generation through limit-fill-or-expiry across 3 limit-shipped systems (Oil Macro, Gold Micro, Oil Micro). Gold Macro stays on market entry — yearly slice rejected limits there.

---

## Why this exists

Filter #27 is the limit-order entry path. It's our defense against the 5-28 pip slippage we measured on market entries (see `docs/FILTER_27_LIMIT_ORDER_RESEARCH.md`).

The first live trade on 2026-06-17 (`GD-MI-2b152d33`) filled cleanly. The second (`GD-MI-1e53d69b`) hit a broker silent-expire path that exposed a reconciler gap → 7 hours of zombie state → see `BUG_FILTER_27_PENDING_RECONCILER_GAP.md`.

After fixing that bug we ran a deeper detective sweep across the entire Filter #27 surface. The sweep found 3 CRITICAL, 6 HIGH, 10 MEDIUM, and 4 OBSERVABILITY items. This doc tracks all of them.

**Code-freeze risk:** user has limited windows for follow-up deploys. **Goal: ship everything in this doc as a single hardened patch.**

---

## How to use this doc

- Each item has: severity, file:line, what could go wrong, what's logged today, fix plan, accept criteria.
- Severity legend:
  - **CRITICAL** — real-money risk if hit
  - **HIGH** — silent corruption, lost orders, or false-positive trading state
  - **MEDIUM** — degraded reliability, stuck rows, hard-to-diagnose
  - **OBSERVABILITY** — no crash but ops can't see / trend / postmortem
- Every fix needs: code change + test (or rationale why no test) + 1-line entry in the lifecycle decision log at the bottom.
- Status column: ⏸ TODO · ⏳ IN PROGRESS · ✅ DONE · 🚫 SKIPPED (with reason)

---

## Already shipped (not in this backlog — for context)

- **Hot fix #1** (zombie cleanup SQL via debug API) — APPLIED 2026-06-17 ~10:45 UTC
- **Fix B** (Python `pending_order_monitor` grace fallback, 60s past TTL) — IMPLEMENTED, awaiting commit
- **Fix C** (throttled Telegram per orphan ticket) — bundled with Fix B, IMPLEMENTED, awaiting commit
- **Fix A** (DWX EA poll-detect of broker silent-expire, v2.10→v2.11) — IMPLEMENTED, awaiting commit
- **Tests** — 30 new tests in `tests/test_filter_27_pending_monitor.py` — all green
- **Doc** — `docs/BUG_FILTER_27_PENDING_RECONCILER_GAP.md` — written

---

# CRITICAL (3)

### C1 — EA reports `success=true` even when broker rejects ✅ DONE (awaiting commit)

**Resolution (2026-06-17):**
- Added `IsOrderAccepted(sent, retcode)` helper in EA (returns true only when sent && retcode in {DONE, PLACED, DONE_PARTIAL})
- Patched all 6 OrderSend callsites: ExecuteOpen, ExecuteOpenPending, ExecuteCancelPending, ExecuteModify, ExecuteClose, ExecuteClosePartial
- All response JSONs now serialize `accepted` (not `sent`) into the `success` field — ops sees `success=false, retcode=10016` for rejection, identical to Python's existing handling
- Bumped EA version v2.11 → v2.12
- Defense-in-depth: enriched Python's `place_market_order_malformed_response` and `place_limit_order_malformed_response` log lines + return dicts to include `retcode` and `comment`
- Added 3 structural tests: `test_ea_has_is_order_accepted_helper`, `test_ea_no_bare_ordersend_success_assignment`, `test_ea_response_uses_accepted_not_sent`
- All 33 Filter #27 tests + 42 limit/fill/close-partial tests pass
- Production evidence: 11 ORDER_FAILED journal events found in DB (10016, 10018, etc.) — these were already caught by Python's ticket>0 guard but observability is now complete

**Files:** `mql5/DWX_Server.mq5` — `ExecuteOpenPending`, `ExecuteCancelPending`, `ExecuteOpen`, `ExecuteModifyStops` (all paths that call `OrderSend`)

**What goes wrong:**
- `OrderSend()` returns `true` whenever the request *reaches* the trade server, NOT when it's *accepted*
- Rejection codes 10018 (market closed), 10006 (invalid stops), 10015 (invalid price) → success=true with `result.order=0`
- Python's `place_limit_order` validates `ticket > 0` so we usually catch it. But `place_market_order` and `modify_stop_loss` have the same EA bug — and even the limit-order check returns "Timeout" rather than "Rejected" because `success=true` confuses the polling
- Bottom line: a real-money rejection can look like a timeout, leading to retry-storm or silent skip with no retcode field

**Logged today:**
- `place_limit_order_malformed_response` event exists but does NOT include `retcode`

**Fix plan:**
```mql5
// Replace bare success = OrderSend(...) with:
bool sent = OrderSend(req, result);
bool accepted = (result.retcode == TRADE_RETCODE_PLACED || result.retcode == TRADE_RETCODE_DONE);
bool success = sent && accepted;
// Always include result.retcode in the JSON written to last_response.json
```
Apply to all 4 OrderSend sites. Bump EA version v2.11 → v2.12.

**Accept criteria:**
- EA emits `success=false` with explicit `retcode` field whenever broker rejects
- Python `place_*` functions log retcode in their failure events
- Manual test: place a limit with SL on the wrong side → broker rejects → DB stays clean, journal shows `LIMIT_ORDER_FAILED` with `retcode=10016`

---

### C2 — SL wrong-side defensive guard (REFRAMED 2026-06-17) ✅ DONE (awaiting commit)

**Resolution (2026-06-17):**
- Stage 1 verified: original audit claim was wrong. Math holds for all current variants. 4 prod 10016 errors were `sl_too_close_to_market`, not wrong-side SL.
- Reframed as defense-in-depth guard for future regression
- Patched 3 backends (oil canonical + micro + oil-micro mirrors) — same code shape
- Both LONG (`sl >= limit`) and SHORT (`sl <= limit`) blocked before `place_limit_order` call
- On block: journal `LIMIT_INVALID_SL` event, gd_signals row with `skip_reason='limit_invalid_sl_wrong_side'`, return None
- Added 18 structural tests (6 properties × 3 backends): guard present, journals event, logs skip_reason, runs BEFORE place_limit_order, uses `>=` and `<=` (not `>` and `<`)
- 51/51 Filter #27 tests pass, 93/93 broader DB-free regression suite green

**Skeptic re-review (2026-06-17, post-fix):**

- ⚠️ **RCA framing was incomplete.** Initial claim "upstream `sl_too_close_to_price` check already blocks the real issue" is true ONLY for the micro backends. **Oil Macro has NO upstream `sl_too_close_to_price` check** — verified by grep on `backend-oil/scanner/live_engine.py`. So C2 actually closes a small Oil Macro coverage gap, not pure defense-in-depth as originally claimed.
- ⚠️ **What C2 does NOT solve:** the 4 production retcode=10016 errors are `sl_too_close_to_market` (broker's min stop-distance rule), NOT wrong-side SL. C2 will not prevent those. They need H6 (through-market check + min-distance validation).
- ✅ **What C2 actually delivers (corrected scope):**
  1. Oil Macro: closes small coverage gap — wrong-side SL would currently reach the broker as a noisy 10016. After C2: silent skip with distinct `LIMIT_INVALID_SL` journal event.
  2. Gold Micro / Oil Micro: pure defense-in-depth — upstream `sl_too_close_to_price` (with `>=` check vs current bid) already covers wrong-side via implication, but C2 makes the math invariant explicit at the code-level.
  3. All 3: distinct journal event `LIMIT_INVALID_SL` (vs generic `ORDER_FAILED retcode=10016`) for postmortem clarity.
  4. Future-proofing against any variant sweep with `offset_pct ∉ [-0.30, 0]` or any sl_price formula change.
- ✅ **Guard correctness verified:**
  - Boundary case (sl == limit) → block is correct (zero-risk SL = invalid)
  - Floating-point edge case → no realistic FP issue at instrument scales
  - Byte-position test sound (only call site matches `place_limit_order(`, not the import)
  - Logic right for both LONG and SHORT
- ✅ **No false-positive risk** — current variants all leave gap ≥ 0.70 × risk between SL and limit

**Files:**
- `backend-oil/scanner/live_engine.py:236-271` (canonical)
- `backend-micro/scanner/live_engine.py` (mirror)
- `backend-oil-micro/scanner/live_engine.py` (mirror)

**Original audit claim (CORRECTED):**
- Audit said: "Variant C with negative offset puts SL on wrong side of limit"
- **Reality (verified 2026-06-17 from prod data):** math doesn't trigger this with current variants. For LONG with offset=−0.10: limit=entry−0.10×risk, sl=entry−risk → gap=0.90×risk. SL stays below limit. For SHORT mirror holds. All 4 prod 10016 errors were `sl_too_close_to_market` (broker min-distance rule), NOT wrong-side. An upstream `sl_too_close_to_price` check already blocks these.

**Why we still ship this fix (defense-in-depth):**
- Math invariant is not asserted in code — only in comments. Future variant sweep (e.g. offset=−1.5) would silently break it.
- Production has 0 cases today, but cost of the guard is 4 lines per backend with zero runtime cost on the happy path.
- Pairs naturally with H6 (through-market check) for a complete pre-broker validation layer.
- Surfaces the math invariant where future readers can see it.

**Fix plan:**
```python
# After compute_limit_price, before place_limit_order:
# Defense-in-depth: assert SL stays on the correct side of the limit price.
# Math should guarantee this for current variants (offset_pct in [-0.30, 0]),
# but a future variant sweep or sl_price formula change could regress it.
# See docs/FILTER_27_AUDIT_BACKLOG.md C2 for the full RCA.
if direction == "long" and sl_price >= intended_limit:
    _log.error("BROKER", "limit_invalid_sl_long",
               trade_ref=trade_ref, intended_limit=intended_limit,
               sl_price=sl_price, gap=sl_price - intended_limit)
    _log_journal_safe(trade_ref, strategy, "LIMIT_INVALID_SL",
                      intended_limit, {
                          "side": "long", "sl": sl_price,
                          "intended_limit": intended_limit,
                          "reason": "sl_above_or_equal_long_limit",
                      })
    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                taken=False, skip_reason="limit_invalid_sl_wrong_side")
    return None
if direction == "short" and sl_price <= intended_limit:
    _log.error("BROKER", "limit_invalid_sl_short",
               trade_ref=trade_ref, intended_limit=intended_limit,
               sl_price=sl_price, gap=intended_limit - sl_price)
    _log_journal_safe(trade_ref, strategy, "LIMIT_INVALID_SL",
                      intended_limit, {
                          "side": "short", "sl": sl_price,
                          "intended_limit": intended_limit,
                          "reason": "sl_below_or_equal_short_limit",
                      })
    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                taken=False, skip_reason="limit_invalid_sl_wrong_side")
    return None
```
3 backends, identical patch. Sits inside the `if intended_limit is not None:` block, before the dry-run gate.

**Accept criteria:**
- Structural test: every limit-shipped backend has the wrong-side guard before `place_limit_order` call
- Unit test: LONG with sl > limit → returns None, journal LIMIT_INVALID_SL written, no broker call, gd_signals row with skip_reason="limit_invalid_sl_wrong_side"
- Unit test: SHORT with sl < limit → mirror
- Unit test: valid LONG (sl < limit) → unchanged behavior, still calls place_limit_order
- Unit test: valid SHORT (sl > limit) → unchanged
- All existing tests pass (no regression)

**Verification basis (Stage 1, 2026-06-17):**
- Verified math: LONG offset=−0.10 → gap = 0.90 × risk > 0. SHORT mirror. Variants A/B/C10/C20/C30 all safe.
- Verified production: scanned all 10016 errors in `gd_journal` — 4 hits, all `sl_too_close_to_market`, zero wrong-side
- Verified upstream guard exists at `live_engine.py:209-216` — blocks `sl_too_close_to_price` for both directions
- Production trade `GD-MI-a05fcfee` (Jun 17) — LONG limit=$4323.04, sl=$4318.54 → gap=$4.50 ✓ correct side

---

### C3 — Pending limit on broker but NO DB row (timeout-orphan blindness) ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- Bug class is real: `_send_command` 10s timeout returns `success=False` → DB INSERT skipped, but broker may have accepted the limit
- Production evidence: 0 limit-order timeouts, 1 market-order timeout ever (Jun 7) — race is theoretical but possible
- ⚠️ **Severity correction:** original audit classed CRITICAL, but real-money impact is bounded:
  - If timeout-orphan limit FILLS → `reconcile_orphans` (existing 60s job) adopts as `OIL-AS-orphan-XXXXXX`
  - If timeout-orphan limit EXPIRES → silent audit-trail loss (no real-money exposure)
- Should be MEDIUM, not CRITICAL. Pure observability + cleanup fix.

**Stage 2 RCA:**
- Layer A: `place_limit_order` 10s timeout silently treats slow broker confirmation as failure
- Layer B: no reconciler scans `pending_orders.json` cross-referenced against DB pending rows
- 3 mirror files (Oil Macro canonical + 2 mirrors)

**Stage 3 Fix:**
- Added `reconcile_broker_pending_orphans()` to all 3 backends
- Strategy: cancel-only (Option A — safest). Cancel orphan pendings at our magic with no DB row.
- Wired into `pending_order_monitor` BEFORE the early-return on empty `pending_db` (so it runs unconditionally every 30s)
- Uses `OUR_MAGIC=200000` to filter out manual MT5 trades (critical safety property)
- Skips DB-known tickets (already handled by existing pending_order_monitor flow)
- Journals distinct event `LIMIT_ORPHAN_PENDING_CANCELLED` (vs `LIMIT_TTL_EXPIRED` / `LIMIT_TTL_EXPIRED_GRACE`)
- Telegram alert `⚠️ BROKER PENDING ORPHAN` per occurrence
- Synthetic trade_ref `{system}-orphan-pend-{ticket-suffix}` for journal continuity

**Stage 4 Tests (20 new):**
- 15 structural × 3 backends × 5 properties: function defined, called from pending_order_monitor, called BEFORE early-return, filters by magic, skips DB-known, journals distinct event
- 5 runtime tests on Oil Macro canonical:
  1. No orphans → no-op (no cancel calls)
  2. Orphan at our magic → cancel + journal LIMIT_ORPHAN_PENDING_CANCELLED
  3. Wrong magic → NO cancel (manual MT5 trade safety)
  4. DB-known ticket → NO cancel (handled by existing flow)
  5. Malformed magic → NO crash, conservative skip
- All 71 Filter #27 tests pass, 113/113 broader DB-free regression suite green

**Files modified:**
- `backend-oil/scanner/live_engine.py` — added `reconcile_broker_pending_orphans()` + wiring (~100 lines)
- `backend-micro/scanner/live_engine.py` — mirror
- `backend-oil-micro/scanner/live_engine.py` — mirror
- `tests/test_filter_27_pending_monitor.py` — 20 new tests

**Files:**
- `backend/execution/mt5_executor.py:484-488` (timeout returns no ticket)
- `backend-oil/scanner/live_engine.py:1010-1018` (pending_order_monitor query starts from DB rows only)

**What goes wrong:**
- `place_limit_order` 10s timeout returns `{"success": False, "error": "Timeout..."}` → DB INSERT skipped
- BUT broker may have accepted slowly (file write back was the bottleneck, not the order)
- A real pending limit now exists at broker with **NO DB row**
- `pending_order_monitor` only iterates `mode='pending'` DB rows. It never scans `pending_orders.json` for tickets without DB rows
- Detection finally happens via `reconcile_orphans` ONLY AFTER fill (when ticket hits open_orders.json). Until fill: invisible

**Logged today:**
- `place_limit_order_timeout` event
- Nothing about the pending orphan that was just created at broker

**Fix plan:**
Extend `pending_order_monitor` with a **second query path**:
```python
# After existing pending-DB iteration, scan pending_orders.json for orphans
all_pending_dwx_tickets = set(pending_file.keys())
all_db_pending_tickets = {str(r["oanda_trade_id"]) for r in pending_db}
db_known_tickets = set(execute(
    "SELECT oanda_trade_id FROM gd_trades WHERE oanda_trade_id = ANY(%s)",
    (list(all_pending_dwx_tickets),), fetch=True
))
broker_only = all_pending_dwx_tickets - db_known_tickets
for ticket in broker_only:
    # Cancel via cancel_pending_order — safer than adopting (we have no signal context)
    cancel_pending_order(ticket)
    notify.limit_orphan_warn(...)  # alert ops
    _log_journal_safe(trade_ref="ORPHAN-PEND-"+ticket, ...)
```

**Accept criteria:**
- Unit test: pending_orders.json has ticket X, no DB row → monitor calls cancel_pending_order
- Live verification: simulated by manually placing a limit via MT5 UI (different magic) → orphan-pending detection triggers OR is correctly filtered out by magic
- Daily recon includes broker_pending_orphans count

---

# HIGH (6)

### H1 — `LIMIT_DRY_RUN` env var whitespace-fragile ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- Reproduced all 16 failure cases programmatically. Smoking gun: `'true '` (trailing space) silently flipped dry_run to **False** (REAL LIMIT) under old code — exact opposite of operator intent
- Bug class real, would trigger on rollback day if user wrote `LIMIT_DRY_RUN=true ` to revert
- `python-dotenv` mostly strips but Windows CRLF + quoted values can leak whitespace through

**Stage 2 RCA:**
- Naive boolean parsing — `os.environ.get(...).lower() == "true"` doesn't strip and doesn't warn on unrecognized values
- 3 mirror files (Oil Macro canonical + 2 mirrors), identical pattern
- Decided to centralize in `backend/execution/limit_price.py` — already a shared helper module + already imported by all 3 backends → minimum-surface-area change

**Stage 3 Fix:**
- Added `parse_dry_run_env(env_var, default, system_prefix)` helper in `limit_price.py`
- Behavior: `.strip().lower()` then check against TRUE set `{"1","true","yes","on"}` and FALSE set `{"0","false","no","off"}`
- Unknown values: log WARNING + return safe default (default=True)
- Bonus: built-in `system_prefix` parameter delivers M7 (per-system override) for free — caller passes "OIL" / "MICRO" / "OIL_MICRO" to enable per-system rollback later
- Wired all 3 backends to import + call the helper. Eliminated bare `os.environ.get("LIMIT_DRY_RUN", "true").lower() == "true"` pattern from all backends.

**Stage 4 Tests (19 new):**
- 16 pure-function tests on `parse_dry_run_env`:
  - canonical true/false
  - **trailing space true/false** (the smoking-gun bug)
  - leading space, uppercase, title case
  - synonyms (1/yes/on, 0/no/off)
  - typo + empty string → default + WARNING via caplog assertion
  - per-system override wins
  - per-system falls back to global when unset
- 3 structural tests × 3 backends: bare `os.environ.get("LIMIT_DRY_RUN", ...)` is GONE; `parse_dry_run_env` IS imported + called
- 90/90 Filter #27 tests pass, 132/132 broader regression green

**Files modified:**
- `backend/execution/limit_price.py` — added `parse_dry_run_env()` helper (~80 lines incl docstring + constants)
- `backend-oil/scanner/live_engine.py` — import + use helper
- `backend-micro/scanner/live_engine.py` — mirror
- `backend-oil-micro/scanner/live_engine.py` — mirror
- `tests/test_filter_27_pending_monitor.py` — 19 new tests

**Bonus:** M7 (per-system env vars) is **partially delivered** — the helper accepts `system_prefix=` kwarg. M7 just needs the callsites updated to pass their prefix. Move M7 from "MEDIUM" effort to "trivial wire-up" later.

**Files:**
- `backend-oil/scanner/live_engine.py:234`
- `backend-micro/scanner/live_engine.py:269`
- `backend-oil-micro/scanner/live_engine.py:243`

**What goes wrong:**
- `os.environ.get("LIMIT_DRY_RUN", "true").lower() == "true"` — no `.strip()`
- `LIMIT_DRY_RUN=false ` (trailing space) → `"false " != "true"` → dry_run=False (real limits — happens to be intended state today)
- `LIMIT_DRY_RUN=true ` → `"true " != "true"` → dry_run=False UNINTENTIONALLY
- Typo `LIMIT_DRY_RUN=fasle` → also False, no warning

**Fix plan:**
```python
_LIMIT_DRY_RUN_TRUE = {"1", "true", "yes", "on"}
_LIMIT_DRY_RUN_FALSE = {"0", "false", "no", "off"}

def _resolve_dry_run() -> bool:
    raw = os.environ.get("LIMIT_DRY_RUN", "true").strip().lower()
    if raw in _LIMIT_DRY_RUN_TRUE: return True
    if raw in _LIMIT_DRY_RUN_FALSE: return False
    _log.warn("CONFIG", "limit_dry_run_unrecognised", value=raw, defaulting_to=True)
    return True  # Safe default
```
Move into `backend/execution/limit_price.py` so all 3 backends share it.

**Accept criteria:**
- Unit tests: `"false "`, `" FALSE "`, `"true\n"`, `"YES"`, `"fasle"` → all parsed correctly with warn on the typo
- Manual: VPS `.env` audit reads as `false` cleanly

---

### H2 — Cross-process `last_response.json` race ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- `_command_lock = threading.Lock()` is per-process, not per-machine
- 4 services share `DWX_DIR/last_response.json`
- EA timer (every 25ms) processes ALL command files in one tick → if 2 commands queued, the second overwrites the first's response
- Python `_wait_response` correlates by mtime, not by command identity — wrong process can read wrong response
- Production: 0 cross-system collisions in 21 days (verified by SQL)
- Severity: HIGH if triggered (wrong DB↔broker mapping = orphan trades), but probability LOW

**Stage 2 RCA:**
- Two separate problems: (a) shared response file overwrites, (b) cmd filenames could collide if 2 PIDs pick same ms
- Fix design space: per-cmd response file (Option A — chosen), embed cmd-id in response (Option B), match on ticket (Option C)

**Stage 3 Fix (Option A — leverages existing WriteResponse infrastructure):**
- **EA side:**
  - Added `WriteFinalResponse(content, filename)` helper that writes to BOTH `responses/<filename>` AND `last_response.json` (latter for backward compat / observability)
  - Threaded `filename` through every Execute* function: ExecuteOpen, ExecuteOpenPending, ExecuteCancelPending, ExecuteModify, ExecuteClose, ExecuteClosePartial, ExecuteCloseAll
  - All 14+ direct `WriteFile(g_folder + "/last_response.json", ...)` writes replaced with `WriteFinalResponse(..., filename)`
  - ExecuteCloseAll passes empty filename to internal ExecuteClose calls (so loop's intermediate writes don't clobber the final summary), then writes own summary at end
  - Bumped EA version v2.12 → v2.13
- **Python side:**
  - `_write_command` now includes `os.getpid()` in filename: `cmd_<unix_ms>_<pid>.txt` — prevents cross-process filename collision even if 2 procs pick same millisecond
  - `_wait_response(filename, timeout)` — new positional arg. Polls `responses/<filename>` first (canonical race-free path)
  - Backward-compat fallback: if `responses/` dir doesn't exist (old EA), falls back to last_response.json mtime polling — emits warn so deploy mismatch is observable
  - Added cleanup: response file deleted after Python reads it (prevents `responses/` from growing unbounded)
  - `_command_lock` kept as in-process sanity-net but no longer load-bearing for cross-process correctness

**Deploy ordering note:**
- Safest: EA upgraded FIRST (writes both per-cmd AND shared file). Old Python keeps working via shared file. New Python (any time after) uses per-cmd file.
- If Python upgraded first while EA still pre-v2.13: new Python's `_wait_response` detects `responses/` dir absent and falls back to shared file with WARN.

**Stage 4 Tests (9 new):**
- 4 Python structural:
  - cmd filename includes PID
  - `_wait_response` uses per-cmd path (verified by source order: H2 canonical block before fallback)
  - `_wait_response` signature accepts filename as first arg (`inspect.signature` check)
  - `_send_command` threads filename to `_wait_response`
- 5 EA structural:
  - WriteFinalResponse helper defined
  - Helper writes to responses/ subfolder
  - No bare `WriteFile last_response.json` outside helper (count assertion: exactly 1)
  - All Execute* signatures include `filename` param
  - EA version bumped to v2.13
- Existing `test_ea_version_bumped` updated to assert v2.13
- 159/159 Filter #27 tests pass, 201/201 broader regression green

**Files modified:**
- `mql5/DWX_Server.mq5` — WriteFinalResponse helper + 14 callsite refactors + 7 signature changes (~80 lines net)
- `backend/execution/mt5_executor.py` — `_write_command` adds PID, `_wait_response` rewritten with per-cmd polling + fallback + cleanup, `_send_command` threads filename (~70 lines net)
- `tests/test_filter_27_pending_monitor.py` — 9 new tests + 1 updated

**Files:** `backend/execution/mt5_executor.py:103,150` + 4 backends share `DWX_DIR`

**What goes wrong:**
- `_command_lock` is `threading.Lock` — serializes within ONE Python process only
- 4 services hit the SAME `last_response.json` and `commands/` dir
- If Oil sends OPEN_PENDING and Micro sends OPEN within ~50ms, EA writes responses sequentially. Both Python processes' `_wait_response` see the same file mtime advance and parse the SAME JSON → wrong process gets the other's ticket

**Fix plan:**
Two options — pick one:
1. **Per-command response file**: Python writes `commands/<cmdId>.cmd`, EA writes `responses/<cmdId>.resp.json`. Python polls only its own response file. EA already has `WriteResponse` infrastructure — wire it up.
2. **Match on ticket/cmd-id, not mtime**: include `cmdId` in the command, EA echoes it in response. Python keeps last_response.json shared but only consumes responses where `cmdId` matches its own pending request.

Option 1 is cleaner; Option 2 is smaller diff. Recommend Option 1.

**Accept criteria:**
- Two simultaneous sends from different processes both get correct ticket back
- No regression on single-process flow
- New EA version (v2.12 or v2.13)

---

### H3 — `_orphan_lookup_ttl_seconds` silent None on DB hiccup ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- 3 None-return failure modes confirmed: empty journal, DB exception, missing ttl_seconds field
- Downstream consequence verified: `past_grace = (ttl is not None) and (...)` → forever-stuck row when ttl is None
- Production check: 0/4 historical limit-path trades have triggered this (all have LIMIT_PLACED journal). Bug class theoretical so far
- Severity stays HIGH because consequence is "row stuck forever blocking new signals" — defense-in-depth justified

**Stage 2 RCA:**
- Helper has 3 silent-None failure paths
- Caller correctly treats None as "can't determine, leave alone" — safe but creates the stuck scenario
- 3 mirror backends (Oil Macro canonical + 2 mirrors)

**Stage 3 Fix:**
- Replaced bare `except: return None` with `_log.exception` that logs the actual error
- Added explicit warn for empty-journal and missing-ttl-field paths
- Added Path 2 (config fallback): `ALPHA_SWEEP['limit_ttl_bars'] * 180` (Oil Macro) or `MICRO_ALPHA_SWEEP['limit_ttl_bars'] * 180` (micros)
- Returns None only in pathological case (config dict itself broken)
- Helper now has full observability: every path emits a distinct `_log` event

**Behavior change (deliberate):**
- Pre-H3: orphan with no journal/no ttl → ttl_seconds=None → past_grace=False → row stuck FOREVER
- Post-H3: orphan with no journal/no ttl → config fallback returns 900s → past_grace=True (if elapsed > 960s) → row resolves cleanly via grace path
- Existing test `test_no_ttl_no_grace_resolution` renamed to `test_no_journal_uses_config_fallback_h3` and inverted — was asserting "no UPDATE", now asserts UPDATE happens. Inversion is the desired effect.

**Stage 4 Tests (14 new):**
- 9 structural × 3 backends:
  - logs DB error (not silent)
  - falls back to config
  - logs no-journal warn path
- 5 runtime tests on Oil Macro:
  - happy path: journal has ttl → returns int
  - empty journal → fallback (900s)
  - missing ttl field → fallback (900s)
  - DB exception → fallback (900s)
  - pathological config broken → None (graceful)
- 134/134 Filter #27 tests, 176/176 broader regression green

**Files modified:**
- `backend-oil/scanner/live_engine.py` — replaced helper (~50 lines incl docstring)
- `backend-micro/scanner/live_engine.py` — mirror (uses MICRO_ALPHA_SWEEP)
- `backend-oil-micro/scanner/live_engine.py` — mirror (uses MICRO_ALPHA_SWEEP)
- `tests/test_filter_27_pending_monitor.py` — 14 new tests + 1 inverted (no_ttl_no_grace_resolution → no_journal_uses_config_fallback_h3)

**Files:**
- `backend-oil/scanner/live_engine.py:1002-1019` + 2 mirrors

**What goes wrong:**
- `_orphan_lookup_ttl_seconds` wraps `execute()` in bare `except: return None`
- DB hiccup → returns None → `past_grace=False` → ticket sits in throttle, never resolves
- Same dead-end if `LIMIT_PLACED` journal write was swallowed earlier (no journal row)

**Fix plan:**
```python
def _orphan_lookup_ttl_seconds(trade_ref: str) -> Optional[int]:
    try:
        rows = execute(...)
        if rows: ...
    except Exception as e:
        _log.exception("DB", "orphan_ttl_lookup_failed", trade_ref=trade_ref, err=str(e))
    # Fallback to config default
    try:
        return int(ALPHA_SWEEP.get("limit_ttl_bars", 5)) * 180
    except Exception:
        return None
```
3 backends.

**Accept criteria:**
- Unit test: DB raises → returns config default (5*180=900)
- Unit test: journal empty → returns config default
- Unit test: DB returns ttl=600 → returns 600 (no fallback)

---

### H4 — Silent fallback to `intended_limit` if `open_price` missing ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- 3 distinct edge cases identified: missing field (silent drift), `open_price=0` (DB garbage), `open_price=None` (would crash)
- Production: 0/2 historical fills triggered any edge case (both had valid open_price)
- Severity: HIGH stays HIGH because "garbage entry_price" propagates to P&L, BE/SL/TP

**Stage 2 RCA:**
- `.get("open_price", intended_limit)` collapses 3 failure modes into 1 bad path
- 3 mirror backends (Oil Macro canonical + 2 mirrors)

**Stage 3 Fix:**
- Extract `raw_open_price = fill_info.get("open_price")` separately
- Validate: `if raw_open_price is None or float(raw_open_price) <= 0: skip cycle`
- Log warn `limit_filled_missing_open_price` with `raw_open_price` + `fill_info_keys` for postmortem
- Use `continue` (not break/return) so other tickets in same monitor cycle still process
- Skip-and-retry: next 30s monitor tick will see updated DWX data

**Stage 4 Tests (16 new):**
- 5 structural × 3 backends:
  - no silent default to intended_limit (in CODE; comments allowed)
  - validates raw_open_price (None + <= 0)
  - logs warn on invalid
  - uses `continue` not break/return
- 4 runtime tests on Oil Macro:
  - open_price=0 → skip cycle, no UPDATE
  - open_price missing → skip cycle, no UPDATE
  - open_price=None → no crash, skip cycle
  - valid fill → UPDATE + LIMIT_FILLED journal (regression check)
- 150/150 Filter #27 tests, 192/192 broader regression green

**Skeptic re-review found follow-up issue (M13):**
- If DWX writes bad data PERSISTENTLY for same ticket, row stays `mode='pending'` forever — never reaches Fix B grace branch (because ticket IS in open_orders.json with bad data)
- H4 emits warn every 30s (observable) but no automatic escalation
- Tracked as **M13 — Stuck-on-bad-open_price escalation (H4 follow-up)** for future fix
- Acceptable trade-off: garbage state was undetected silently before; stuck state with periodic warn is louder & safer

**Files modified:**
- `backend-oil/scanner/live_engine.py` — replaced 1-line bad pattern with 13-line validate-and-skip block
- `backend-micro/scanner/live_engine.py` — mirror
- `backend-oil-micro/scanner/live_engine.py` — mirror
- `tests/test_filter_27_pending_monitor.py` — 16 new tests

**Files:** `backend-oil/scanner/live_engine.py:1086-1107` + 2 mirrors

**What goes wrong:**
- `actual_fill = float(fill_info.get("open_price", intended_limit))`
- If EA writes `open_orders.json` with missing/zero open_price (corrupt write), we record limit price as fill
- Live↔BT parity drift recorded as 0 (lie)

**Fix plan:**
```python
if not fill_info.get("open_price") or float(fill_info["open_price"]) <= 0:
    _log.warn("BROKER", "limit_filled_missing_open_price",
              trade_ref=trade_ref, ticket=ticket, fill_info=fill_info,
              note="will retry next cycle")
    continue  # skip this row this cycle
actual_fill = float(fill_info["open_price"])
```

**Accept criteria:**
- Unit test: fill_info missing open_price → no DB update, warn logged
- Unit test: fill_info has open_price=0 → same
- Unit test: valid fill → unchanged

---

### H5 — EA Fix A: lost ticket dropped if `HistoryOrderSelect` returns false on first poll ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- Audit claim confirmed in code: line 299-303 single `continue` on first miss; lines 357-358 wholesale `prev = current` swap
- Production: 0 hits today (Fix A poll-detect itself never fired in production yet)
- Severity correction: HIGH → MEDIUM (Python Fix B grace fallback already handles DB-row resolution; lost forensic trail only)

**Stage 2 RCA:**
- No retry mechanism — single-tick miss = permanent loss of poll-detect entry
- Single EA file affected
- Realistic failure window: broker server lag >25ms after pending vanishes

**Stage 3 Fix:**
- Extracted `TryProcessLostTicket(ticket)` helper from inline Fix A loop, returns 3 states (0=retry, 1=resolved, -1=permanent skip)
- Added retry pool: `g_retryTickets[16]` + `g_retryAge[16]` + `g_retryCount`
- Each tick processes retry pool FIRST (drain before adding new), then diff loop
- Tickets that fail HistoryOrderSelect get age++ on each retry; dropped after 3 attempts (~75ms total) with Print warn
- Duplicate-prevention: `alreadyQueued` check in diff loop
- Pool overflow handled gracefully with Print warn (rather than silent drop)
- Bumped EA version v2.13 → v2.14

**Stage 4 Tests (6 new):**
- 6 structural tests on EA source:
  - retry pool state arrays + counter defined
  - TryProcessLostTicket helper extracted (separate function, not inline)
  - Helper returns 3 distinct states (0/1/-1) verified by source-grep
  - Retry pool processed BEFORE diff loop (byte-position assertion)
  - Tickets dropped after FIX_A_RETRY_MAX_AGE attempts with Print warn
  - alreadyQueued check prevents duplicates
- 165/165 Filter #27 tests pass, 207/207 broader regression green

**Files modified:**
- `mql5/DWX_Server.mq5` — TryProcessLostTicket helper (~70 lines), retry pool state (~10 lines), retry-loop in WritePendingOrders (~30 lines), pool-overflow warns
- `tests/test_filter_27_pending_monitor.py` — 6 new tests + 1 version-check updated

**Files:** `mql5/DWX_Server.mq5` Fix A loop

**What goes wrong:**
- After diff, `g_prevPendingTickets` is REPLACED with `currentTickets`
- If `HistoryOrderSelect` failed for a lost ticket (history slow), `continue` skips this tick — but next tick the ticket is no longer in prev set → never retried
- Python Fix B grace catches DB row, but `cancelled_orders.json` poll-detect entry is lost forever

**Fix plan:**
Add a small "retry pool" of unresolved-lost tickets carried forward 1-2 ticks:
```mql5
#define FIX_A_RETRY_POOL 16
static ulong g_retryTickets[FIX_A_RETRY_POOL];
static int   g_retryCount = 0;
static int   g_retryAge[FIX_A_RETRY_POOL];  // ticks since added; drop after 3
// Process retry pool first; for each, try HistoryOrderSelect again
// Append unresolved to next-tick retry pool
```

**Accept criteria:**
- Test: simulate HistoryOrderSelect=false on tick 1, true on tick 2 → poll-detect entry written on tick 2
- Test: HistoryOrderSelect=false for 3+ ticks → ticket dropped from retry pool, Python Fix B grace handles it (no double-write)

---

### H6 — Limit price at/through current market — broker reject or instant fill ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- Bug class real but theoretical. Production data: 0/4 trip rate. Severity should be MEDIUM, not HIGH.
- Walked all 4 historical limit placements vs their snap_bid/snap_ask:
  - GD-MI-2b152d33: SHORT, limit $4337.93, bid $4337.27, ask $4337.37 → SAFE (limit above ask)
  - GD-MI-1e53d69b: SHORT, limit $4348.09, bid $4344.66, ask $4344.76 → SAFE
  - GD-MI-a05fcfee: LONG, limit $4323.04, bid $4331.70, ask $4331.80 → SAFE (limit below bid)
  - OIL-MI-08b725d3: SHORT, limit $79.0339, bid $79.03, ask $79.14 → BETWEEN bid/ask (filled cleanly in 28s)
- Real risk: market-moving-while-engulfing-bar-forms could land limit ABOVE current ask (LONG) or BELOW current bid (SHORT) → broker either instant-fills at unintended price OR rejects 10015

**Stage 2 RCA:**
- No code path validates `intended_limit` vs `current_bid/ask` before sending to broker
- 4 hot-path checks exist (`sl_too_close_to_price`, `tp_already_passed`, C2 wrong-side SL) but no through-market check
- 3 mirror files (Oil Macro canonical + 2 mirrors)
- `live_price` already fetched for variant B math at line 216 — reuse it for the H6 guard (no extra network call)

**Stage 3 Fix:**
- **Permissive threshold** (`limit > ask` for LONG, `limit < bid` for SHORT) — kills only clearly through-market placements, not between-bid-ask cases like OIL-MI-08b725d3 which fill cleanly
- Position: inside `if intended_limit is not None:` block, BEFORE C2 wrong-side check (so order-of-validation is: through-market → wrong-side → log intent)
- Distinct journal event `LIMIT_PRICE_THROUGH_MARKET` with full context (intended, bid, ask, distance)
- gd_signals row with `skip_reason='limit_price_through_market'` so 5-min cooldown picks it up
- Defensive: `if live_price:` wrapper + per-direction `live_ask_now and ...` truthy guards prevent crash on missing price feed

**Stage 4 Tests (18 new):**
- 6 properties × 3 backends:
  - LONG guard present (`intended_limit > live_ask_now`)
  - SHORT guard present (`intended_limit < live_bid_now`)
  - Distinct journal event `LIMIT_PRICE_THROUGH_MARKET`
  - skip_reason logged for cooldown
  - Guard runs BEFORE place_limit_order (byte-position assertion)
  - Handles missing live_price gracefully (defensive truthy guards)
- 108/108 Filter #27 tests pass, 150/150 broader regression green
- Skeptic re-validation: all 4 historical production placements would have passed under new check (0 false positives)

**Files modified:**
- `backend-oil/scanner/live_engine.py` — added H6 guard (~40 lines)
- `backend-micro/scanner/live_engine.py` — mirror
- `backend-oil-micro/scanner/live_engine.py` — mirror
- `tests/test_filter_27_pending_monitor.py` — 18 new tests

**Files:** all 3 live_engines

**What goes wrong:**
- `compute_limit_price` doesn't check side-of-market
- LONG: `intended_limit >= current_bid` → broker fills instantly (no price improvement) OR rejects 10015
- SHORT: same with `current_ask`
- Result: real-money trade at unintended price

**Fix plan:**
```python
# After compute_limit_price, before place_limit_order:
live_price = get_current_price(...)  # already cached in execute_signal
if direction == "long" and intended_limit >= live_price.bid:
    _log_journal_safe(trade_ref, strategy, "LIMIT_PRICE_THROUGH_MARKET",
                      intended_limit, {"side": "long", "bid": live_price.bid})
    notify.send(f"⚠️ LIMIT THROUGH MARKET — skipped {trade_ref}")
    return None
elif direction == "short" and intended_limit <= live_price.ask:
    # mirror
    return None
```

**Accept criteria:**
- Unit test: LONG with intended_limit=4350, bid=4348 → skip, journal event
- Unit test: SHORT with intended_limit=4350, ask=4351 → skip
- Unit test: valid case (LONG with intended < bid) → unchanged

---

# MEDIUM (10)

### M1 — `compute_limit_price` accepts negative output ⏸
**File:** `backend/execution/limit_price.py:84`
**Fix:** `if result <= 0: raise ValueError(f"compute_limit_price returned non-positive {result}")`. Add unit test.

### M2 — Log resolved entry_mode (catches typos) ⏸
**File:** all 3 live_engines, just before the `if cfg_entry_mode == "limit":` branch
**Fix:** `_log.info("BROKER", "entry_mode_resolved", raw=cfg_entry_mode, will_use_limit=(cfg_entry_mode=="limit"))`. Operator sees from logs whether limit path will fire.

### M3 — Journal `LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET` ⏸
**File:** all 3 live_engines, the `except` around `compute_limit_price`
**Fix:** in the except where `intended_limit = None`, write a journal event so ops can spot opted-into-limit-but-got-market.

### M4 — EA `OnTradeTransaction` dedup against `cancelled_orders.json` ⏸
**File:** `mql5/DWX_Server.mq5:992-1059`
**Fix:** Add `if(StringFind(existing, ticketKey) >= 0) return;` guard before `AppendCancelledOrder`. Same shape as Fix A loop.

### M5 — EA Fix A overflow warn ✅ DONE (awaiting commit, bundled with H5)

**Resolution (2026-06-17):**
- Bundled with H5 fix since both touch the same EA `WritePendingOrders` function
- Added Print warn when `ourCount > FIX_A_MAX_PENDING`, guarded by count-change pattern (`ourCount != g_lastPendingCount`) to avoid 25ms-tick spam when count is stable
- 1 new test verifies warn message exists + lives inside WritePendingOrders
- Free-rider on H5's EA recompile
**File:** `mql5/DWX_Server.mq5` `WritePendingOrders`
**Fix:** `if(ourCount > FIX_A_MAX_PENDING) Print("[DWX] WARN: pending count ", ourCount, " > ", FIX_A_MAX_PENDING, " — diff truncated");`

### M6 — Document EA-restart blind spot ⏸
**File:** `docs/BUG_FILTER_27_PENDING_RECONCILER_GAP.md` add a paragraph
**Fix:** explicitly call out: EA recompile/restart loses pre-restart pending tickets from Fix A diff. Python Fix B grace catches DB row → `LIMIT_TTL_EXPIRED_GRACE` (so the distinct exit_reason is the postmortem signal). No code change, just doc.

### M7 — Per-system `LIMIT_DRY_RUN` env vars ⏸
**Files:** all 3 live_engines + `backend/execution/limit_price.py` (helper)
**Fix:**
```python
def _resolve_dry_run(system_prefix: str) -> bool:
    # Per-system override wins, fallback to global
    raw = os.environ.get(f"{system_prefix}_LIMIT_DRY_RUN") or \
          os.environ.get("LIMIT_DRY_RUN", "true")
    return parse_bool_env(raw)
# Each backend passes its prefix: "OIL", "MICRO", "OIL_MICRO"
```
Enables per-system rollback via `OIL_LIMIT_DRY_RUN=true` without flipping the other two.

### M8 — `LIMIT_ORPHAN` journal event ✅ (2026-06-17)
**File:** all 3 pending_order_monitor orphan-within-grace branches
- `backend-oil/scanner/live_engine.py:1512–1521`
- `backend-micro/scanner/live_engine.py:1339–1348`
- `backend-oil-micro/scanner/live_engine.py:1308–1317`

**RCA:** Within-grace orphan path warned to file logs and fired throttled Telegram, but NEVER persisted a row to `gd_journal`. After file logs rotate, postmortem skill (`scripts/postmortem.py`) reconstructs timeline from DB only — orphan periods looked like silent gaps. Today's GD-MI-1e53d69b silent-expire confirms the gap: postmortem shows ENTRY_FILLED → jump straight to next event with no trace of the broker-visibility loss.

**Fix:** Inside the existing `if ticket not in _orphan_alerted:` throttle gate (so journal fires exactly once per ticket per session, matching Telegram), call `_log_journal_safe(trade_ref, row["strategy"], "LIMIT_ORPHAN", intended_limit, {instrument, ticket, intended_limit, elapsed_seconds, ttl_seconds, note})` BEFORE the Telegram. DB write happens first; even if Telegram fails, orphan is durable.

**Throttle gate design:** Reuses `_orphan_alerted` set. Cleared on resolution (`_orphan_alerted.discard(ticket)` in fill / cancel / grace branches — already in place from M5/Fix C). One LIMIT_ORPHAN per ticket per session is correct: this is a "broker became invisible" event, not a per-tick state.

**Tests added** (`tests/test_filter_27_pending_monitor.py`, +6 tests):
- `test_m8_orphan_within_grace_writes_journal` — runtime: oil monitor writes 1× LIMIT_ORPHAN with full context (ticket, elapsed_seconds, ttl_seconds, instrument, intended_limit)
- `test_m8_orphan_journal_throttled_across_calls` — runtime: 5 monitor invocations → still 1 journal event
- `test_m8_no_journal_when_past_grace` — runtime: past-grace path writes LIMIT_TTL_EXPIRED only, NOT LIMIT_ORPHAN (events are distinct)
- `test_m8_limit_orphan_journal_event_in_grace_branch` — structural × 3 backends: each grace block contains `"LIMIT_ORPHAN"` + `_orphan_alerted.add` (gated)

**Test count:** 178 → 182 (all green)
**Scope:** Limit-shipped backends only (oil / micro / oil-micro). Gold Macro N/A (no Filter #27).

### M9 — `state` + `detected_via` in `LIMIT_TTL_EXPIRED` journal context ✅ (2026-06-17)
**File:** all 3 pending_order_monitor cancel branches
- `backend-oil/scanner/live_engine.py:1346–1364` (parse) + cancel branch
- `backend-micro/scanner/live_engine.py:1192–1207` (parse) + cancel branch
- `backend-oil-micro/scanner/live_engine.py:1161–1176` (parse) + cancel branch

**RCA:** EA writes 4 distinct state values to `cancelled_orders.json`:
- `state="EXPIRED"`, `detected_via="ontradetrans"` — broker fired event normally (expected)
- `state="CANCELED"`, `detected_via="ontradetrans"` — manual or programmatic cancel
- `state="EXPIRED_POLLED"`, `detected_via="poll"` — Fix A path: broker silently expired, EA poll caught it
- `state="CANCELED_POLLED"`, `detected_via="poll"` — Fix A path: cancel detected by poll loop

Python parser was a `set()` of tickets only — dropped both fields entirely. LIMIT_TTL_EXPIRED journal context had no clue which path resolved it. **Telemetry value:** if `detected_via="poll"` rate is high → broker is silent-expiring our limits → important signal for filter tuning. Today's GD-MI-1e53d69b silent expire would have been visible from the journal context if M9 had been live.

**Fix:** Change `cancelled_tickets = set()` → `cancelled_tickets: dict = {}` (ticket → `{state, detected_via}`). Dict still satisfies `if ticket in cancelled_tickets` so existing branch logic unchanged. Cancel branch looks up `cancel_meta = cancelled_tickets[ticket]`, passes `state` + `detected_via` into both `_log.info` AND `_log_journal_safe` context.

**Backward compat:** Old EA writes (pre-M9 contract) without these fields default to `state=""` and `detected_via="ontradetrans"` (since pre-Fix-A EA was OnTradeTransaction-only). No crash on missing fields.

**Audit doc proposed `state_source` (single field).** Implemented as TWO fields (`state` + `detected_via`) because the EA already writes both and they answer different questions:
- `state` = "what happened?" (EXPIRED vs CANCELED — TTL vs manual)
- `detected_via` = "how did we find out?" (ontradetrans vs poll — broker-event vs Fix-A fallback)

**Tests added** (`tests/test_filter_27_pending_monitor.py`, +9 tests):
- `test_m9_ontradetrans_state_in_journal` — runtime: state=EXPIRED + detected_via=ontradetrans surfaced in journal
- `test_m9_poll_state_in_journal` — runtime: state=EXPIRED_POLLED + detected_via=poll surfaced (Fix A path)
- `test_m9_missing_state_backward_compat` — runtime: missing fields default to "" / "ontradetrans"; no crash
- `test_m9_cancelled_tickets_is_dict_with_state_metadata` — structural × 3: backend uses dict (not set), parses both fields
- `test_m9_journal_context_includes_state_fields` — structural × 3: cancel-branch journal includes both fields

**Test count:** 182 → 191 (all green)
**Scope:** Limit-shipped backends only. Gold Macro N/A.
**EA changes:** None (EA already writes the fields; M9 is parse-side only).

### M10 — Distinct Telegram for grace fallback ✅ (2026-06-17)
**Files:**
- `backend/notify.py:146–177` — added `via_grace=False` kwarg, distinct message body when True
- `backend-oil/scanner/live_engine.py:1517` — past-grace branch passes `via_grace=True`
- `backend-micro/scanner/live_engine.py:1339` — past-grace branch passes `via_grace=True`
- `backend-oil-micro/scanner/live_engine.py:1308` — past-grace branch passes `via_grace=True`

**RCA:** Two distinct broker behaviors produced identical Telegram:
- **Cancel branch** = broker fired ORDER_DELETE, EA wrote cancelled_orders.json. Healthy — expected lifecycle.
- **Grace-fallback branch (Fix B)** = broker silently auto-expired without ORDER_DELETE event; TTL+60s grace path resolved zombie row. **Indicates broker reliability issue.**

Both fired `notify.limit_ttl_expired(trade_ref, instrument, intended_limit)` — operator's phone said "⏱ LIMIT EXPIRED" with no path-of-detection signal. To tell them apart, operator had to SSH+grep logs. Symmetric to M9 (which fixed DB-side telemetry); M10 fixes Telegram-side telemetry.

**Fix:** Added `via_grace=False` kwarg to `notify.limit_ttl_expired()`. When True, message body includes `" (grace fallback)"` suffix and explanatory line `"broker silent expire"` so operator instantly distinguishes from clean cancel. Past-grace branches in 3 backends pass `via_grace=True`; cancel branches keep default. Cumulative grace-fallback rate now visible from Telegram alone.

**Backward compat:** Default value preserves all existing callers' behavior. Old EA + new Python = no breakage.

**Tests added** (`tests/test_filter_27_pending_monitor.py`, +10 tests):
- `test_m10_clean_cancel_telegram_no_via_grace` — runtime: cancel branch calls without via_grace=True
- `test_m10_grace_fallback_telegram_via_grace_true` — runtime: grace branch calls with via_grace=True
- `test_m10_notify_signature_accepts_via_grace` — signature: via_grace kwarg exists with default=False
- `test_m10_notify_grace_suffix_in_message` — actual message content: clean has no marker, grace has marker
- `test_m10_grace_branch_passes_via_grace_true` — structural × 3: each backend's grace branch passes True
- `test_m10_cancel_branch_does_not_pass_via_grace` — structural × 3: each backend's cancel branch keeps default

**Test count:** 191 → 201 (all green)
**EA changes:** None (Telegram is a Python-side concern).

### M11 — Filter #27 limit-success path missing `_log_signal(taken=True)` ✅ (2026-06-17) — REAL BUG, not observability

**Files:**
- `backend-oil/scanner/live_engine.py:~458` — limit-success path before `return trade_ref`
- `backend-micro/scanner/live_engine.py:~452` — limit-success path before `return trade_ref`
- `backend-oil-micro/scanner/live_engine.py:~424` — limit-success path before `return trade_ref`

**RCA:** Filter #27 was added on top of an existing market-order flow. Market path calls `_log_signal(strategy, direction, fill_price, sl, tp, taken=True, trade_ref=trade_ref)` at the bottom of `execute_signal` — this writes a row to `gd_signals` table. The 5-min cooldown query in `scheduler.py:127` relies on this:
```python
SELECT timestamp, taken, skip_reason FROM gd_signals
WHERE strategy='alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 1
```
Limit-shipped path returns early at `return trade_ref` immediately after `notify.limit_placed()` to skip the post-fill DB INSERT (pending isn't filled yet). **It also skipped `_log_signal()` — the cooldown record.** Effect:
- 14:00:00: signal fires limit-mode → broker accepts pending → `gd_signals` has NO row for this trade
- 14:00:30: scheduler tick → cooldown query returns the LAST row (could be hours earlier, e.g. 11:30 SL'd trade) → 5-min gate fails open
- 14:00:30: scanner re-evaluates → if engulfing setup still in window, could fire ANOTHER limit on the same setup

**Currently masked** by 30s scan cadence + bar boundaries + the fact that we've had few enough Filter #27 trades to see this in production. But the gate is structurally broken for limit-shipped systems.

**Fix:** Insert `_log_signal(strategy, direction, intended_limit, sl_price, tp_price, taken=True, trade_ref=trade_ref)` BEFORE `return trade_ref` in the limit-success path. Wrap in try/except (mirror of market-path pattern at oil:485-488) — broker order is on the wire, must not crash before journaling. Use `intended_limit` not `entry_price` because the cooldown row should record the price the broker was asked to fill at.

**Tests added** (`tests/test_filter_27_pending_monitor.py`, +12 tests via 4 parametrized × 3 backends):
- `test_m11_limit_success_path_has_log_signal_taken_true` — block between notify.limit_placed and `return trade_ref` contains `_log_signal(...,taken=True,...)`
- `test_m11_log_signal_uses_intended_limit_not_entry_price` — call args contain `intended_limit` (not `entry_price`)
- `test_m11_log_signal_wrapped_in_try_except` — `try:` immediately precedes call; `except` immediately follows
- `test_m11_no_silent_return_in_limit_path` — regression guard: any future `return trade_ref` in this region must have a preceding `_log_signal` call

**Test count:** 201 → 213 (all green)
**EA changes:** None (Python-side cooldown bookkeeping).
**Scope:** Limit-shipped backends only. Gold Macro N/A.

### M13 — Stuck-on-bad-open_price escalation (H4 follow-up) ✅ (2026-06-17)

**Files:**
- `backend/notify.py:179–197` — new `bad_open_price_persistent` Telegram helper
- `backend-oil/scanner/live_engine.py:1128–1136` — module-level `_bad_open_price_cycles` dict + `BAD_OPEN_PRICE_THRESHOLD = 5`
- `backend-oil/scanner/live_engine.py:~1407` — H4 block extended with counter + escalation
- `backend-micro/scanner/live_engine.py:1054–1058` — module state + same H4 escalation
- `backend-oil-micro/scanner/live_engine.py:1024–1028` — module state + same H4 escalation

**RCA:** H4 (shipped 2026-06-17 morning) handled transient bad open_price by `continue` (skip cycle, retry next 30s tick). This is correct for sub-second DWX mid-write races. **But:** if DWX writes bad data persistently (EA bug, file corruption, stuck state), the row stays `mode='pending'` forever:
- Every 30s monitor tick fires another `limit_filled_missing_open_price` warn → log spam
- Operator hears nothing on phone (no Telegram)
- Eventually grace path (TTL+60s) may resolve as `LIMIT_TTL_EXPIRED_GRACE` — but that masks the underlying broker/DWX bug
- Potential broker exposure: pending order still on broker books even though our system is stuck

**Fix design:**
1. **Per-ticket counter** `_bad_open_price_cycles: dict[str, int]` (module-level, persists across cycles)
2. **Threshold:** `BAD_OPEN_PRICE_THRESHOLD = 5` (5 × 30s = ~2.5 min)
3. **Increment** on each bad-data cycle; **clear** on valid fill (transient resolved)
4. **Escalation** when `bad_count >= threshold`:
   - `_log.error("bad_open_price_persistent", ...)` with full diagnostics
   - Journal `LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED` event with `bad_cycles + raw_open_price + fill_info_keys`
   - `cancel_pending_order(ticket)` — clear broker-side state
   - UPDATE `gd_trades SET exit_reason='LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED'` — close DB row
   - `notify.bad_open_price_persistent(...)` — Telegram with full diagnostics for operator
   - **Sentinel `-1`** to suppress re-fire (one-shot escalation per ticket)

**Why threshold = 5:** Transient DWX writes resolve sub-second; 5 cycles (2.5 min) is clearly persistent. Short enough that operator hears about persistent issue BEFORE grace fallback (TTL+60s ≈ 16min for 15-bar TTL) masks it.

**Tests added** (`tests/test_filter_27_pending_monitor.py`, +14 tests):
- `test_m13_bad_open_price_state_defined` — structural × 3: dict + threshold defined module-level
- `test_m13_h4_block_increments_counter` — structural × 3: H4 block increments _bad_open_price_cycles
- `test_m13_threshold_triggers_force_cancel` — structural × 3: threshold check + journal + cancel + notify + sentinel
- `test_m13_counter_cleared_on_valid_fill` — structural × 3: valid-fill path calls `.pop(ticket, None)`
- `test_m13_notify_helper_exists` — signature: `bad_open_price_persistent(trade_ref, instrument, ticket, intended_limit, bad_cycles, raw_value)`
- `test_m13_notify_message_contains_diagnostic_info` — message body has trade_ref, ticket, bad_cycles, "open_price", "force-cancel"

**Test count:** 213 → 227 (all green)
**Test compat:** H4's `test_h4_skips_cycle_on_invalid` regex window expanded `500 → 4000` chars to fit M13 escalation block.
**EA changes:** None.
**Scope:** Limit-shipped backends only.

---

# OBSERVABILITY (4)

### O1 — Dashboard pending vs live mode badge ⏸
**Files:** `backend-oil/routes/state.py` + `frontend/app/live/page.tsx`
**Gap:** `/state.db_positions` doesn't surface `mode`. Pending limits render as filled positions.
**Fix:** Add `mode` to state JSON. Frontend live page: distinct badge / lighter styling for `mode='pending'` rows.

### O2 — Trades page surfaces mode + limit exit reasons ⏸
**File:** `frontend/app/trades/page.tsx`
**Gap:** `mode` field IS in the response but never rendered. Cannot answer "fill rate of last 100 limits?" from UI.
**Fix:** Add mode column. Add filter for exit_reason in (LIMIT_TTL_EXPIRED, LIMIT_TTL_EXPIRED_GRACE).

### O3 — Daily recon Filter #27 counters ⏸
**Files:** `backend/db.py:daily_recon_stats` + `backend/notify.py:daily_recon`
**Gap:** Recon ignores Filter #27 entirely. No daily fill-rate.
**Fix:** Add 5 counts: `limit_placed`, `limit_filled`, `limit_expired_clean`, `limit_expired_grace`, `limit_orphan`. Display in daily Telegram.

### O4 — `time_to_fill` computation in `LIMIT_FILLED` ⏸
**File:** all 3 pending_order_monitor fill branches
**Gap:** Telegram says `time_to_fill='unknown'`. Math deferred. Latency drift never reaches operator.
**Fix:**
```python
broker_open_time = fill_info.get("open_time", "")  # "2026.06.17 04:00:18"
if broker_open_time:
    broker_dt = datetime.strptime(broker_open_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
    time_to_fill = int((broker_dt - entry_time).total_seconds())
else:
    time_to_fill = None
# Pass into journal context + notify.trade_filled
```

---

# Plan of action

## Phase 1 — pre-commit hardening (CRITICAL + HIGH only)
1. ✅ Fix B/C/A already implemented (separate doc)
2. ⏸ Apply C1, C2, C3, H1, H2, H3, H4, H5, H6 — write tests, verify, show diffs
3. ⏸ User reviews → commits → pushes
4. ⏸ EA recompile on VPS (v2.10 → v2.13 estimated after C1+H2+H5+M4+M5)
5. ⏸ Python services restart
6. ⏸ Live verification — next limit fire should:
   - C1: clean retcode in success+failure logs
   - C2: structurally invalid signals get journal event before hitting broker
   - C3: any orphan-pending caught within 30s
   - H1: env var parse logs match expectation
   - H6: through-market signals skipped pre-broker

## Phase 2 — observability hardening
7. ⏸ Apply M1-M10 + O1-O4 — bundle into a second commit if Phase 1 is too big
8. ⏸ Update memory entry [[project-filter-27-limit-orders]] with consolidated lessons

## Phase 3 — long-tail
9. ⏸ M6 doc-only update
10. ⏸ Calibration plan still triggered at 30+ clean live trades per [[project-calibration-plan]]

---

# Lifecycle decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-17 ~10:30 UTC | Hot fix #1 SQL applied to clear zombie row | Unblock signals immediately |
| 2026-06-17 ~11:00 UTC | Approved Fix A + Fix B + Fix C bundle, grace=60s, throttle per-ticket | User sign-off; minimum-surface-area defense in depth |
| 2026-06-17 ~11:30 UTC | Fix B/C/A implemented + tested (30/30) | Ready for review |
| 2026-06-17 ~12:00 UTC | Audit run by 4 parallel detective agents | Found 3 CRITICAL, 6 HIGH, 10 MED, 4 OBS |
| 2026-06-17 ~12:30 UTC | Decision: bundle ALL hardening into one push (code freeze risk) | This doc + 24-task backlog |
| 2026-06-17 ~14:00 UTC | C1 fix shipped (EA retcode + Python malformed-response enrichment, EA v2.11→v2.12, 3 new tests pass) | First framework cycle complete |
| 2026-06-17 ~15:00 UTC | C2 fix shipped (3 backends wrong-side SL guard, 18 new tests pass) | Defense-in-depth for limit order SL invariant |
| 2026-06-17 ~15:45 UTC | C2 skeptic re-review — caught RCA framing error | Original "upstream guard already covers it" was true for micro engines only; Oil Macro has no upstream sl_too_close check. Doc updated with corrected scope, code unchanged (fix shape was sound). Lesson: verify upstream-guard claims across ALL backends, not just one. |
| 2026-06-17 ~15:50 UTC | New trade `GD-MI-a05fcfee` postmortem written (limit BUY @ $4323.04, expired clean) | Same broker-silent-expire bug as `GD-MI-1e53d69b` — Fix A/B will resolve once deployed. M11 added (limit path missing `_log_signal(taken=True)` — gd_signals row never inserted for limit-shipped trades). |
| 2026-06-18 (next session) | M8 shipped — LIMIT_ORPHAN journal event in 3 backends within-grace branches, 6 new tests pass | Postmortem can now reconstruct broker-visibility-gap from DB even after file logs rotate. Audit count: 12/24 shipped. |
| 2026-06-18 | M9 shipped — cancelled_tickets set→dict in 3 backends, state + detected_via surfaced in LIMIT_TTL_EXPIRED journal context, 9 new tests pass | Postmortem can distinguish broker-normal-cancel (ontradetrans) from Fix-A-poll-detected silent-expire. EA already writes both fields; M9 is parse-side only (no EA changes). Audit count: 13/24 shipped. |
| 2026-06-18 | M10 shipped — notify.limit_ttl_expired gets via_grace kwarg, 3 grace branches pass True, 10 new tests pass | Operator can distinguish broker-normal-cancel from broker-silent-expire on phone Telegram alone — no SSH grep. Symmetric to M9: M9 fixed DB telemetry, M10 fixes Telegram telemetry. Audit count: 14/24 shipped. |
| 2026-06-18 | M11 shipped — _log_signal(taken=True) added to limit-success path in 3 backends before `return trade_ref`, 12 new tests pass | **REAL BUG (not observability):** limit-shipped trades had NO gd_signals row → 5-min cooldown query found wrong "last signal" → could re-fire same engulfing setup. Currently masked by 30s scan cadence but structurally broken. Audit count: 15/24 shipped. |
| 2026-06-18 | M13 shipped — per-ticket bad-open_price counter + 5-cycle threshold + force-cancel escalation in 3 backends, new notify.bad_open_price_persistent helper, 14 new tests pass | H4 protected against transient DWX races but had no ceiling; persistent bad data would loop forever silently. M13 fires Telegram + force-cancels at ~2.5 min. Sentinel -1 prevents re-fire spam. Audit count: 16/24 shipped. |
| (pending) | C3-H6 implemented + tested | Phase 1 continues |
| (pending) | M1-O4 implemented + tested | Phase 2 |
| (pending) | Single push to midas-deploy | After full review |
| (pending) | EA recompile on VPS + Python restart | After push |
| (pending) | Live verification | After restart |

---

# Fix coverage matrix

Question raised by user (2026-06-17): are CRITICAL+HIGH fixes common to all 4 systems or specific?

**System inventory:**

| System | Backend | Filter #27 limit shipped? |
|---|---|---|
| Gold Macro | `backend/` | ❌ STASHED (yearly slice rejected) — market entry only |
| Gold Micro | `backend-micro/` | ✅ shipped (variant C10_loose) |
| Oil Macro | `backend-oil/` | ✅ shipped (variant B / engulf_close) |
| Oil Micro | `backend-oil-micro/` | ✅ shipped (variant C10_loose) |

**Fix-by-fix coverage (verified by grep 2026-06-17):**

| Fix | Gold Macro | Gold Micro | Oil Macro | Oil Micro | Notes |
|---|---|---|---|---|---|
| **C1** EA retcode | ✅ | ✅ | ✅ | ✅ | Single shared EA file (`mql5/DWX_Server.mq5`) — covers all 4 systems via the same binary |
| **C2** wrong-side SL | N/A | ✅ | ✅ | ✅ | Limit-specific. Gold Macro doesn't have limit path → fix not applicable |
| **C3** broker-pending reconcile | N/A | ✅ | ✅ | ✅ | Limit-specific. Gold Macro market-orders use existing `reconcile_orphans` (filled-case) |
| **H1** env var hardening | N/A | ✅ | ✅ | ✅ | `LIMIT_DRY_RUN` only consulted by limit path |
| **H6** through-market | N/A | ✅ | ✅ | ✅ | Limit-specific |

🦣 **All limit-specific fixes propagated correctly to all 3 limit-shipped backends.** Gold Macro intentionally untouched per [[project-filter-27-limit-orders]] yearly-slice ship decision.

🦣 **C1 is the only fix that touches Gold Macro** (via the shared EA file). Verified intentional — Gold Macro market orders need the retcode-aware acceptance just as much as limit orders do.

## Bonus finding #2 — Filter #28 candidate (CRITICAL, separate doc)

After 2026-06-17 −$868 live day, user asked "what if no bias?" Single-seed BT shows ALL 4 systems improve by removing bias filter (+$3.58M over 21yr). **Not shipped** — full sweep workflow required. See [`FILTER_28_BIAS_DISABLE_RESEARCH.md`](./FILTER_28_BIAS_DISABLE_RESEARCH.md). Backlog item #289. Baseline script: `scripts/research/filter_28_neutral_bias_baseline.py`.

## Bonus finding from coverage audit (2026-06-17) — M12

While auditing fix scope, discovered a separate coverage gap:

- **Oil Macro lacks the upstream `sl_too_close_to_price` market-order guard** that Gold Macro / Gold Micro / Oil Micro all have
- Verified via grep: `grep -c sl_too_close_to_price backend{,-micro,-oil,-oil-micro}/scanner/live_engine.py` returns 2/2/0/2
- Production evidence: 4 OIL-AS retcode=10016 errors historically (Jun 2 + Jun 9) — would have been pre-empted with the upstream check
- Affects MARKET-order entries, not limit-orders. Unrelated to Filter #27 but worth fixing while we're already in the audit

### M12 — Oil Macro upstream sl_too_close_to_price gap ✅ DONE (awaiting commit)

**Stage 1 verification (2026-06-17):**
- Confirmed via grep: 0 occurrences in `backend-oil/scanner/live_engine.py` vs 2 in each of the other 3 backends
- Production: 4 historical OIL-AS retcode=10016 rejects (LONG entries with $0.24-$0.31 SL distance from market). All would have been pre-empted with this check.

**Stage 2 RCA:**
- Oversight when Oil Macro was first built. Other 3 backends got it, Oil Macro didn't.
- Single-file fix — no mirrors needed.
- Pattern available at `backend-oil-micro/scanner/live_engine.py:182-194` (same instrument family BCO_USD, same broker rules)

**Stage 3 Fix:**
- Mirrored Oil Micro pattern verbatim into Oil Macro at the same logical position (after `units_too_small`, before `oanda_units = ...`)
- BCO buffer = $0.05 (matches Oil Micro — BRENT scale ~10× smaller than XAU)
- Same `skip_reason="sl_too_close_to_price"` so 5-min cooldown query in scheduler.py picks it up identically

**Stage 4 Tests (12 new):**
- 3 properties × 4 backends parametrized:
  - check present in all 4 backends (cross-system parity)
  - check runs BEFORE `oanda_units = ...` (ordering correctness)
  - per-instrument buffer correct ($1.0 for XAU, $0.05 for BCO)
- 120/120 Filter #27 tests pass, 162/162 broader regression green

**Files modified:**
- `backend-oil/scanner/live_engine.py` — added 16-line check after `position_already_open` skip
- `tests/test_filter_27_pending_monitor.py` — 12 new tests

**Net:** Oil Macro now matches the other 3 backends' pre-broker SL validation. Production retcode=10016 errors should drop to zero on this path going forward.

---

# Files referenced

- `mql5/DWX_Server.mq5` — EA: `OrderSend` callsites, `WritePendingOrders`, `OnTradeTransaction`
- `backend/execution/limit_price.py` — compute_limit_price
- `backend/execution/mt5_executor.py` — place_limit_order, cancel_pending_order, _send_command
- `backend-oil/scanner/live_engine.py` — canonical execute_signal + pending_order_monitor
- `backend-micro/scanner/live_engine.py` — Gold Micro mirror
- `backend-oil-micro/scanner/live_engine.py` — Oil Micro mirror
- `backend/notify.py` — limit_placed, limit_ttl_expired, limit_orphan_warn (NEW), daily_recon
- `backend/db.py:daily_recon_stats` — daily count rollup
- `backend/routes/state.py` — db_positions response shape
- `frontend/app/live/page.tsx` — pending vs live UI
- `frontend/app/trades/page.tsx` — mode column + filter
- `docs/BUG_FILTER_27_PENDING_RECONCILER_GAP.md` — companion bug doc
- `docs/FILTER_27_LIMIT_ORDER_RESEARCH.md` — original research doc
- `tests/test_filter_27_pending_monitor.py` — Fix B/C/A tests
- `tests/test_limit_price.py` — compute_limit_price tests
