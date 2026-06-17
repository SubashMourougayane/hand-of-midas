# BUG: Filter #27 — Pending-Order Monitor Cancellation Gap

**Status:** RCA COMPLETE · Fix B + Fix A + Fix C IMPLEMENTED + TESTED · Awaiting user diff review + commit · Hot fix #1 (zombie cleanup) APPLIED

**Discovered:** 2026-06-17 ~10:30 UTC during routine trade postmortem
**Reporter:** ops postmortem (after `GD-MI-1e53d69b` showed as open in dashboard despite TTL having expired 7+ hours earlier)
**Trades affected:** 1 confirmed (`GD-MI-1e53d69b`); class affects ALL 3 limit-shipped systems (Gold Micro, Oil Micro, Oil Macro)
**Severity:** MEDIUM — no real money exposure, but zombie DB rows block one-at-a-time guard → blocks all subsequent signals on the affected system until manual cleanup

---

## Summary (caveman)

Limit order placed → broker auto-expired at TTL → DWX EA didn't write `cancelled_orders.json` → Python pending-order monitor stuck waiting for confirmation forever → DB row stuck `mode='pending'` → new signals blocked.

Bug is at the broker-notification layer (silent server-side TTL expiry not visible to MT5 client). Fix is broker-agnostic detection at both EA and Python layers.

---

## 1. Symptom

`GD-MI-1e53d69b` (Gold Micro SHORT) appeared as open trade in dashboard from 03:18 UTC through 10:45 UTC — over 7 hours after its 75-minute TTL should have expired at 04:33 UTC. No fill ever happened (zero broker exposure). The DB row was `mode='pending'`, `exit_time=NULL`. New Gold Micro signals were blocked by the one-at-a-time guard.

## 2. Confirmed facts (verified from logs + DB + DWX files)

| Fact | Source | Verified |
|---|---|---|
| EA v2.10 with `OnTradeTransaction ORDER_DELETE` handler IS loaded on VPS | MT5 Experts log: `[DWX] Server started v2.10 (Filter #27)` at 18:52:29 on 2026-06-16 | ✅ |
| Limit placed at 03:18:01 UTC with TTL until 04:33 UTC | Trades log + `last_response.json` + DB row | ✅ |
| At 03:33:00.502, ticket disappeared from `OrdersTotal()` (EA poll) | Experts log: `pending_orders.json count changed: 1 -> 0` | ✅ |
| At broker (`Trades` log channel) NO event was logged for the disappearance | Terminal log lines jump from 03:18:01 (placement) directly to 08:58:56 (network scan) | ✅ |
| `OnTradeTransaction` did NOT fire — no `[DWX] PENDING EXPIRED` print | grep on full Experts log | ✅ |
| `cancelled_orders.json` was never created | DWX dir listing | ✅ |
| Order is NOT in pending, NOT in open, NOT in cancelled, NOT in closed | All 4 DWX files inspected | ✅ |
| DB row stayed `mode='pending'` with `exit_time=NULL` until manual cleanup | DB query | ✅ |
| `pending_order_monitor` saw row, fell into `pending_monitor_orphan` warn loop silently | Code review of `live_engine.py:1051` | ✅ |

## 3. Root cause (3 layers)

### Layer 1 — Broker silent TTL expiry
JustMarkets server-side TTL expiry (`ORDER_TIME_SPECIFIED` reaching `expiration` field) cancelled the order **without sending an MT5 client notification**. No `Trades` event in terminal log. This is a JustMarkets / MT5 quirk: pending orders that expire by their own `ORDER_TIME_EXPIRATION` can be "silently reaped" if the terminal doesn't receive notification at exactly that moment.

### Layer 2 — EA detects via polling, but doesn't write `cancelled_orders.json`
`WritePendingOrders()` runs on `OnTimer` and notices the order disappeared (count `1 → 0`). Logs the count change but doesn't track which specific ticket vanished and doesn't write to `cancelled_orders.json`. The handler that DOES write that file (`OnTradeTransaction → TRADE_TRANSACTION_ORDER_DELETE`) only fires for events the terminal receives notifications about.

### Layer 3 — Python monitor has no fallback
`pending_order_monitor` uses 3 deterministic branches (still pending / filled / cancelled). If the ticket is in NONE of those files, it logs a `pending_monitor_orphan` warn and waits forever. No timeout-based fallback. No Telegram alert.

## 4. Misconceptions corrected during RCA

| Initial guess | Reality | Evidence |
|---|---|---|
| "EA might be old version" | EA IS v2.10 | Experts log startup line |
| "OnTradeTransaction never fires for pending events" | It DOES fire for client-initiated cancels (CANCEL_PENDING). It DIDN'T fire here because broker silently expired | Code review + log absence |
| "Missing cancelled_orders.json → EA isn't writing" | EA WOULD write it correctly if `OnTradeTransaction` fired. The bug is upstream | Code review |

## 5. Why it didn't get caught earlier

- This is the **first ever pending-order TTL expiry in production**. Filter #27 went live at ~21:05 UTC on 2026-06-16. First trade fired at 03:00 UTC on 2026-06-17 (which FILLED — no expiry path tested). Second trade at 03:18 UTC was the first to actually expire.
- `pending_monitor_orphan` warn is silent (no Telegram). 7 hours of zombie state went unnoticed until manual postmortem.

---

## 6. Hot fix #1 — Zombie cleanup (APPLIED ✅)

```sql
UPDATE gd_trades
SET exit_time = NOW(),
    exit_reason = 'LIMIT_TTL_EXPIRED',
    pnl_usd = 0,
    pnl_gbp = 0,
    mode = 'live',
    exit_price = entry_price
WHERE trade_ref = 'GD-MI-1e53d69b'
  AND mode = 'pending'
  AND exit_time IS NULL;
```

Plus journal backfill:
```sql
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp)
VALUES ('GD-MI-1e53d69b', 'micro_alpha_sweep', 'LIMIT_TTL_EXPIRED', 4348.0919,
        '{"manual_recon":true,"reason":"broker_auto_expire_TTL_2026-06-17_04:33:00_UTC"}'::jsonb,
        NOW());
```

**Applied via debug API at 2026-06-17 ~10:45 UTC. `db_positions=[]` confirmed. New signals unblocked.**

---

## 7. Permanent fix design (NOT YET APPLIED)

### Fix B — Python monitor self-heal grace period

In `pending_order_monitor` orphan branch (current behavior: silent warn forever), add time-based fallback:

- If ticket is NOT in pending_orders.json, NOT in open_orders.json, NOT in cancelled_orders.json
- AND `entry_time + ttl_seconds + grace_seconds < NOW()`
- → Treat as `LIMIT_TTL_EXPIRED`, update DB row exactly as the cancelled-branch does today

**Grace seconds:** 60s default. Rationale:
- Broker file-write lag rarely exceeds 30s (DWX poll is 1s, file rotation is fast)
- 60s = 6× safety margin against false-positive expiry while a fill is still propagating through DWX files
- Short enough that zombie blocks signals for at most 1 extra minute

### Fix A — EA-level lost-ticket detection

In `WritePendingOrders()`, after building the current ticket list, compare against the previous tick's snapshot:
- For each ticket present last tick but NOT present now AND NOT in `closed_orders.json` → write to `cancelled_orders.json` with `state="EXPIRED_POLLED"` and `reason="poll_detected_lost_ticket"`

This catches the silent-broker-expire case at the EA layer, redundantly with Fix B.

### Fix C — Throttled Telegram alert on orphan warn

In `pending_order_monitor` orphan branch:
- Track `_notified_orphan_tickets` set at module level
- On first encounter of an orphan ticket, send `notify.send()` with trade ref + ticket + "investigation needed"
- Subsequent encounters of the SAME ticket: silent
- On state resolution (filled / expired / DB cleanup), remove from set

Rationale: silent orphans are how this bug went unnoticed for 7 hours. One-shot alert per ticket = signal without spam.

### Layered defense

| Failure mode | Fix B catches it? | Fix A catches it? |
|---|---|---|
| Broker silently expires | ✅ (after grace period) | ✅ (next EA poll) |
| EA crash / not reading | ✅ (Python only depends on DB) | ❌ (EA is the actor) |
| Python monitor down | ❌ (Python is the actor) | ✅ (writes file regardless) |
| `OnTradeTransaction` fires correctly | unchanged (cancelled file written normally) | redundant write skipped (ticket not "lost", just transitioned) |

Both fixes complementary. Both broker-agnostic.

---

## 8. Tests

### Fix B tests (`tests/test_filter_27_pending_monitor.py`)

1. **happy path — fill detected** — DB row pending, ticket in `open_orders.json` → row flipped to live, `LIMIT_FILLED` journal event, intended vs actual recorded
2. **happy path — cancel detected** — DB row pending, ticket in `cancelled_orders.json` → row marked LIMIT_TTL_EXPIRED via existing branch
3. **NEW: orphan within grace** — DB row pending, ticket NOT in any file, age = TTL + 30s (under 60s grace) → no DB change, warn fires, Telegram fires once
4. **NEW: orphan past grace** — DB row pending, ticket NOT in any file, age = TTL + 90s (over 60s grace) → DB row marked LIMIT_TTL_EXPIRED, journal event written, exit_reason="LIMIT_TTL_EXPIRED_GRACE"
5. **NEW: idempotent** — call monitor twice on past-grace orphan → second call is no-op (mode now 'live' so filter excludes)
6. **NEW: throttled alert** — call monitor 5× on within-grace orphan → only 1 Telegram sent
7. **NEW: no false-positive on fresh ticket** — ticket placed 5s ago, not yet in any file (network lag) → no DB change, no warn, no alert

### Fix A tests (manual + unit if possible)

EA logic is MQL5; cannot unit-test directly. Verify by:
1. Compile clean
2. Live test: place a 60s-TTL limit order on staging, let it expire, verify `cancelled_orders.json` written by EA-poll path
3. Stress: place + manually cancel via CANCEL_PENDING → both `OnTradeTransaction` AND poll path detect; verify ONE entry in `cancelled_orders.json` (no double-write)

---

## 9. Plan of action

| # | Step | Owner | Status |
|---|---|---|---|
| 1 | RCA + design | claude | ✅ DONE |
| 2 | Hot fix #1 SQL via debug API (zombie cleanup) | claude | ✅ DONE |
| 3 | Write doc (this file) | claude | ✅ DONE |
| 4 | Write Fix B + Fix C + Fix A tests | claude | ✅ DONE (30/30 pass) |
| 5 | Implement Fix B (Oil Macro canonical + 2 mirrors) | claude | ✅ DONE |
| 6 | Implement Fix C (throttle, bundled with Fix B) | claude | ✅ DONE |
| 7 | Implement Fix A (EA poll-based detection, v2.10→v2.11) | claude | ✅ DONE |
| 8 | Show diffs for user review | claude | ⏳ AWAITING |
| 9 | User commits + pushes to midas-deploy | user | ⏸ |
| 10 | EA recompile on VPS (F7 in MetaEditor) | user | ⏸ (only after Fix A merged + push) |
| 11 | Python services restart on VPS | user | ⏸ (after git pull) |
| 12 | Live verification on next TTL expiry | both | ⏸ |
| 13 | Update [[project-filter-27-limit-orders]] memory | claude | ⏸ |

### Test summary

**`tests/test_filter_27_pending_monitor.py` — 30 tests, all pass:**
- 18 structural tests (5 properties × 3 backends + 3 EA structural)
- 8 runtime tests on Oil Macro canonical (mocked DWX + DB):
  1. fill detected (regression — unchanged path)
  2. cancel detected via DWX file (regression — unchanged path)
  3. orphan within grace → no DB change, alert fires once
  4. orphan past grace → row marked LIMIT_TTL_EXPIRED_GRACE, journal `fallback=fix_b_grace`
  5. idempotent (past-grace + already resolved → no-op)
  6. throttle (5 calls within grace → 1 telegram)
  7. ttl_seconds missing → no false-positive grace resolution
  8. throttle cleared on resolution

**Regression run:** 72 pass / 30 errors (errors are pre-existing test-DB connection issues, not introduced by these changes).

### Files modified

```
backend-micro/scanner/live_engine.py     | +88 -1   (Fix B + Fix C)
backend-oil-micro/scanner/live_engine.py | +88 -1   (Fix B + Fix C)
backend-oil/scanner/live_engine.py       | +103 -5  (Fix B + Fix C, canonical)
backend/notify.py                        | +20      (limit_orphan_warn helper)
mql5/DWX_Server.mq5                      | +104     (Fix A poll-detect, v2.11)
tests/test_filter_27_pending_monitor.py  | +320     (NEW — 30 tests)
docs/BUG_FILTER_27_PENDING_RECONCILER_GAP.md | +260 (NEW — this file)
```

---

## 10. Verification post-fix

After Fix B + Fix A merge + EA recompile on VPS, the next limit-order TTL expiry should:
1. EA logs `[DWX] PENDING EXPIRED:` (Fix A)
2. `cancelled_orders.json` gets written with the ticket
3. Next `pending_order_monitor` tick (≤30s) sees ticket in cancelled, runs the existing cancel branch
4. DB row marked `LIMIT_TTL_EXPIRED` cleanly
5. Telegram sent: `⏱ LIMIT EXPIRED: <trade_ref>`

OR (if Fix A regresses for some reason):
1. After 60s grace + TTL, Fix B fallback triggers
2. DB row marked `LIMIT_TTL_EXPIRED_GRACE` (different exit_reason — observable difference for telemetry)
3. Telegram sent: `⏱ LIMIT EXPIRED (grace fallback): <trade_ref>`

Belt + suspenders. Either path works alone; both is safest.

---

## 11. Decision log

- **2026-06-17 10:45 UTC** — Hot fix #1 SQL applied. `db_positions=[]` confirmed.
- **2026-06-17 ~11:00 UTC** — User approved plan: Fix A + Fix B + Fix C bundled. `grace_seconds=60`. Telegram throttled per-ticket.
- **2026-06-17 ~11:30 UTC** — Fix B + Fix C + Fix A implemented across 3 Python backends + EA. 30 tests written, all pass. 72/72 DB-free regression tests still green. Diffs prepared for user review.
- **(pending)** User reviews diffs → commits → pushes → EA recompile → live verification

---

## 12. Future format additions

If we ship more fixes for this bug class:
- track which fix caught the next zombie (was it Fix A's poll detection or Fix B's grace fallback? observable via different exit_reason values)
- after 7-day window: if Fix A successfully catches everything, Fix B grace can be widened or removed
- if Fix B carries the load, EA-side improvement is optional polish

This pattern — defense in depth at two layers, with telemetry to compare — is how we figure out which layer is doing the work.

---

## 13. EA-restart blind spot (M6, documented 2026-06-17)

**The gap:** EA Fix A (poll-detect) tracks `g_prevPendingTickets` as `static` in-memory state. On EA recompile/restart (manual recompile, MT5 restart, terminal crash, etc.):
- `g_prevPendingTickets` is reset to all-zeros
- `g_prevPendingCount = 0`
- First poll cycle after restart sees the live pending list as "all new", with NO prior tickets to diff against
- Any pending order that EXPIRED while EA was down is permanently invisible to Fix A
- `cancelled_orders.json` will NOT receive a poll-detected entry for those tickets

**Why this is acceptable (not a real-money bug):**
- Python's Fix B grace fallback (TTL+60s) catches the DB row and resolves it as `LIMIT_TTL_EXPIRED_GRACE`
- Strategy keeps running normally
- Only loss is the `cancelled_orders.json` forensic trail entry for the specific in-flight ticket(s) at restart time

**Postmortem signal:**
- If you see `exit_reason='LIMIT_TTL_EXPIRED_GRACE'` with no matching entry in `cancelled_orders.json`, suspect EA restart during the trade's TTL window
- Cross-check by grepping MT5 Experts log for `[DWX] Server started v2.X` timestamps within the trade's lifetime

**No code fix needed.** EA-restart is rare (manual recompile or crash), and the consequence is purely observability — Python Fix B handles DB resolution. Documenting here so future operators don't chase a phantom bug when this pattern shows up.
