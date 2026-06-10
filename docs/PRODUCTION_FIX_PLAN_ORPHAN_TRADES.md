# Production Fix Plan — Orphan Trade Cascade

**Date**: June 10, 2026  
**Trigger**: 4 orphan BRENT SHORT trades on broker, 0 in DB  
**Severity**: HIGH — silent failure mode that violates max_trades_per_day, loses tracking, loses Telegram visibility  
**Goal**: Eliminate the entire class of "orphan trade" failures via defense-in-depth

---

## Status Update (post-decision)

The 4 orphan BRENT SHORTs were **closed manually** by the user, locking in **+$600 realized profit**. Reasoning: the TP was unrealistically far ($88.99 vs price ~$91.30), reversal risk was real, and we couldn't track the positions through our system anyway. **This was the right call — turning unmanaged exposure into realized gain.**

### A 5TH ORPHAN APPEARED (~07:03 server / 04:03 UTC / 09:33 IST)

After the user closed the 4 trades, **another orphan trade was placed** by Oil Micro:
- Order ID: `2031871738`
- BRENT SHORT 1.01 lot (~65% larger than earlier orphans)
- Entry $91.20, SL $91.78, TP $90.67 (R:R 0.91 — different setup, different consolidation)
- DB has 0 entries for it. No Telegram. **Same failure mode as the earlier 4.**

This proves the bug is **not a one-time stuck signal in a loop** — it's a **consistent failure** in the Oil Micro `execute_signal` path. Every Oil Micro signal that places an order fails to write to DB and fails to send Telegram. The strategy is generating fresh signals correctly; the persistence layer is broken.

### TWO ADDITIONAL DISCOVERIES (Same Investigation)

**Discovery 1: 3 of 4 systems are still hitting OANDA price stream despite being on MT5**

Only Gold Macro's `main.py` checks `if EXECUTOR != "mt5"` before starting `start_stream()`. Oil Macro, Gold Micro, and Oil Micro **always start the OANDA stream** regardless of EXECUTOR setting. With empty `OANDA_TOKEN` (env var unset on the VPS since we migrated to MT5), the stream throws `Illegal header value b'Bearer '` and reconnects every 3 seconds.

Evidence: `gd_journal` for Oil Macro and Gold Macro both contain ONLY `STREAM_DISCONNECTED` events for the past hour — flooding at ~20-30 events/minute per system.

**Discovery 2: BE detection on Oil Macro / Gold Micro / Oil Micro is BROKEN (silently)**

The price-stream `_on_tick()` function is the BE trigger for these systems (see `backend-oil-micro/scanner/price_stream.py:30-82`). With OANDA stream constantly disconnected, **no ticks ever reach `_on_tick()`** → **BE never fires from the stream path**. They have to rely on the cron-based `position_monitor_job` which runs every 60 seconds — slower, less precise, and we just saw it has its own issues.

This is why Gold Micro's June 10 trade hit SL with no BE protection earlier — even though we "fixed" the missing `check_alpha_sweep_breakeven()` call, the stream-based real-time BE detection was already dead because of this OANDA misconfig.

### Implications for the Plan

- Phase 1: Now needs to backfill **5 trades** (4 closed + 1 currently open) plus the 5th's eventual exit when user closes it.
- Phase 2: Must include **disabling OANDA stream startup** in the 3 systems that don't check EXECUTOR. This is a 5-line change but stops the journal flooding and CPU thrash immediately.
- Phase 3: The orphan reconciler becomes even more critical — it's the **only** safety net catching these failures right now since logging/Telegram are broken.

---

## Mental Model: Why Orphans Happen

This isn't one bug — it's a **failure cascade** with 4 distinct stages:

```
Stage 1: A DB write fails (network blip, serialization error, lock timeout)
   ↓
Stage 2: Unprotected call lets exception propagate, control flow exits early
   ↓
Stage 3: In-memory state (sweep blacklist, trade counter) is NOT updated
   ↓
Stage 4: Next scan cycle re-runs the same path → places another order
   ↓
LOOP: Until either the sweep window expires or service crashes hard
```

**The lesson:** Any code path that places an order MUST be transactionally consistent — either all post-order work succeeds, or the system knows it failed and prevents the next cycle from re-firing.

---

## Phase 1 — Immediate Recovery (Tonight)

The 4 trades are already closed manually. Phase 1 is now about reconciling the DB to reality and stopping any further damage tonight.

### 1.1 Pull Exact Close Details from MT5

Before writing the backfill SQL, fetch the **actual** close price and close time for each of the orphan orders from MT5 history (don't guess, don't approximate). These should be visible in JustMarkets web → History tab, or in the local MT5 terminal History.

**5 orders to backfill** (4 closed manually + 1 still open at time of writing):

Closed:
- 2031303852, 2031324884, 2031450502, 2031569381 (the original 4)

Currently open (close it manually first, then backfill as closed):
- **2031871738** — BRENT SHORT 1.01 lot @ $91.20, opened 04:03 UTC, currently underwater ~$150

For each, capture:
- `close_time` (server time → convert to UTC)
- `close_price`
- `realized_pnl` (Trade P&L, before swap/commission)
- `realized_pnl_after_costs` (Net P&L)

Replace the placeholder values in the SQL below with these real numbers. **No phantom fills, no fake numbers.**

### 1.2 Backfill DB With Trades AS CLOSED

This SQL inserts the 4 trades complete with exit data. The position monitor will not try to manage them (because `exit_time IS NOT NULL` filters them out). The strategy's recent-trades query, daily P&L sum, and DD state recovery will all see them.

```sql
-- Replace ?? with actual values from MT5 history
INSERT INTO gd_trades
  (trade_ref, strategy, side,
   entry_time, entry_price,
   exit_time, exit_price,
   sl_price, tp_price,
   lot_size, units, mode, oanda_trade_id,
   pnl_usd, pnl_gbp, exit_reason)
VALUES
  ('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 01:03:00+00', 91.45,
   '<close_time_utc_1>',     <close_price_1>,
   92.55, 88.99,
   0.62, 620, 'live', '2031303852',
   <pnl_usd_1>, <pnl_usd_1>, 'MANUAL_CLOSE'),
  ('OIL-MI-rec-324884', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 01:06:00+00', 91.48,
   '<close_time_utc_2>',     <close_price_2>,
   92.55, 88.99,
   0.61, 610, 'live', '2031324884',
   <pnl_usd_2>, <pnl_usd_2>, 'MANUAL_CLOSE'),
  ('OIL-MI-rec-450502', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 01:45:00+00', 91.53,
   '<close_time_utc_3>',     <close_price_3>,
   92.55, 88.99,
   0.61, 610, 'live', '2031450502',
   <pnl_usd_3>, <pnl_usd_3>, 'MANUAL_CLOSE'),
  ('OIL-MI-rec-569381', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 02:27:00+00', 91.35,
   '<close_time_utc_4>',     <close_price_4>,
   92.55, 88.99,
   0.62, 620, 'live', '2031569381',
   <pnl_usd_4>, <pnl_usd_4>, 'MANUAL_CLOSE'),
  -- 5th orphan, larger position, different setup
  ('OIL-MI-rec-871738', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 04:03:00+00', 91.20,
   '<close_time_utc_5>',     <close_price_5>,
   91.78, 90.67,
   1.01, 1010, 'live', '2031871738',
   <pnl_usd_5>, <pnl_usd_5>, 'MANUAL_CLOSE');
```

`exit_reason='MANUAL_CLOSE'` is a new value — it tells the system "this didn't hit SL or TP, a human intervened." Useful for filtering later (e.g., when measuring strategy P&L, you might want to exclude manual closes since they don't reflect strategy edge).

### 1.3 Update DD State With the Realized P&L

DD state (gd_dd_state row id=4 for Oil Micro) tracks consecutive losses, equity, peak equity. The 4 closed trades changed equity by approximately **+$600** (realized profit). Update DD state to reflect this:

```sql
UPDATE gd_dd_state
SET
  consecutive_losses = 0,                                   -- 4 wins in a row reset the counter
  pause_counter = 0,
  equity = equity + <total_realized_usd>,                   -- e.g., equity + 600.00
  peak_equity = GREATEST(peak_equity, equity + <total_realized_usd>),
  updated_at = NOW()
WHERE id = 4;
```

Run this AFTER the trade backfill so it reflects the same reality.

### 1.4 Backfill the Journal With ENTRY/EXIT Events

Optional but recommended for audit trail. The journal is the system's history-of-record:

```sql
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp)
VALUES
  ('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.45,
   '{"recovered": true, "reason": "orphan_backfill", "broker_id": "2031303852"}'::jsonb,
   '2026-06-10 01:03:00+00'),
  ('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', <close_price_1>,
   '{"recovered": true, "reason": "user_closed_due_to_orphan", "pnl_usd": <pnl_usd_1>}'::jsonb,
   '<close_time_utc_1>');
-- ... repeat for the other 3 trades
```

### 1.5 Verify Post-Backfill State

After running the SQL, verify with these checks (each should return the expected count):

```sql
-- Should return 4 rows
SELECT trade_ref, side, entry_time, exit_time, pnl_usd, exit_reason
FROM gd_trades
WHERE trade_ref LIKE 'OIL-MI-rec-%'
ORDER BY entry_time;

-- Should return ~$600 (sum of realized P&L)
SELECT SUM(pnl_usd) FROM gd_trades WHERE trade_ref LIKE 'OIL-MI-rec-%';

-- Should reflect updated equity
SELECT equity, peak_equity, consecutive_losses FROM gd_dd_state WHERE id = 4;

-- Should still be 0 (we don't want any open Oil Micro positions)
SELECT COUNT(*) FROM gd_trades WHERE trade_ref LIKE 'OIL-MI-%' AND exit_time IS NULL;
```

### 1.6 Restart Oil Micro Service

Restart so the in-memory `_daily_state["trades"]` syncs with the new DB count. After restart:
- Daily count = 4 (from backfilled rows with today's date)
- `max_trades_per_day = 3` → guard fires → no more Oil Micro entries today
- Tomorrow at 00:00 UTC, daily state resets and the system runs clean

**Total time:** 20 minutes (5 min to pull MT5 history + 10 min to write/run SQL + 5 min restart/verify).

---

## Phase 2 — Code Fixes (Next Deploy, Before Tomorrow's Scan Window)

These are the minimal code changes to stop this exact failure mode.

### 2.0 Disable OANDA Price Stream on MT5 Systems (NEW — DO FIRST)

**Why first:** The constant reconnect loop is corrupting our investigation of the orphan bug (journal floods drown out real events) and likely contributing to DB latency that's making the `execute_signal` path unstable.

**Files to fix:** `backend-oil/main.py`, `backend-micro/main.py`, `backend-oil-micro/main.py`

Apply the same pattern Gold Macro already uses (`backend/main.py:32-37`):

```python
# BEFORE — always starts OANDA stream
@asynccontextmanager
async def lifespan(app: FastAPI):
    from scanner.scheduler import start_scheduler, stop_scheduler
    from scanner.price_stream import start_stream, stop_stream

    print("Starting Oil Micro Alpha-Sweep scheduler...")
    start_scheduler()
    start_stream()                                          # ← ALWAYS RUNS
    print("OilMiner Micro ready.")
    yield
    print("Shutting down OilMiner Micro...")
    stop_stream()
    stop_scheduler()

# AFTER — only starts stream if running on OANDA executor
@asynccontextmanager
async def lifespan(app: FastAPI):
    from scanner.scheduler import start_scheduler, stop_scheduler
    from config import EXECUTOR

    print("Starting Oil Micro Alpha-Sweep scheduler...")
    start_scheduler()
    if EXECUTOR != "mt5":
        from scanner.price_stream import start_stream, stop_stream
        print("Starting OANDA price stream...")
        start_stream()
    else:
        print("MT5 mode — OANDA price stream disabled (DWX provides prices)")
    print("OilMiner Micro ready.")
    yield
    print("Shutting down OilMiner Micro...")
    if EXECUTOR != "mt5":
        stop_stream()
    stop_scheduler()
```

**Apply to all 3 files:** `backend-oil/main.py`, `backend-micro/main.py`, `backend-oil-micro/main.py`.

**Followup needed (Phase 3):** Add an MT5-tick-based BE detector to replace the OANDA stream's BE function. The current state is that BE on these 3 systems falls back to the 60-sec cron `check_alpha_sweep_breakeven()` — which works but is slower/less precise than tick-level. For now, that's acceptable; the stream BE was effectively already dead.

**Time:** 15 min (3 files, identical pattern, plus restart).

### 2.1 Wrap All `_log_journal` Calls in Try/Except

**Files:** `backend/scanner/live_engine.py`, `backend-oil/scanner/live_engine.py`, `backend-micro/scanner/live_engine.py`, `backend-oil-micro/scanner/live_engine.py`

The pattern around line 202 (varies by file):

```python
# BEFORE (raises if DB fails, kills the rest of execute_signal)
_log_journal(trade_ref, strategy, "ENTRY_FILLED", fill_price, {...})

# AFTER (best-effort journal write — never blocks the main flow)
try:
    _log_journal(trade_ref, strategy, "ENTRY_FILLED", fill_price, {...})
except Exception as e:
    print(f"  [{system}] _log_journal ENTRY_FILLED FAILED: {e}")
```

**Apply to every `_log_journal` call** that runs after a successful order — these are the dangerous ones because they sit between order placement and Telegram/state updates. There are ~6-8 such calls across the 4 systems.

### 2.2 Move Sweep Blacklist Update BEFORE `execute_signal`

**Files:** `backend-micro/scanner/scheduler.py:370`, `backend-oil-micro/scanner/scheduler.py:370`

```python
# BEFORE (blacklist only updated if execute_signal returns normally)
trade_ref = execute_signal(...)
_traded_sweeps["keys"].add(sweep_key)  # ← skipped if exception raised
if trade_ref:
    trades_today += 1

# AFTER (blacklist updated unconditionally, before risky call)
_traded_sweeps["keys"].add(sweep_key)  # ← always runs, prevents re-fire
try:
    trade_ref = execute_signal(...)
    if trade_ref:
        trades_today += 1
        _daily_state["trades"] += 1
except Exception as e:
    # Sweep already blacklisted, don't retry this cycle
    print(f"  [system] execute_signal raised: {e}")
    _log_journal_safe(...)  # best effort
```

**Why this matters:** Even if `execute_signal` partially fails, the sweep_key is already blacklisted, so the next 3-min scan won't retry the same setup. **This single change would have stopped the cascade at trade #1 instead of letting it run to trade #4.**

### 2.3 Sanitize Journal Context Before JSON Serialization

**File:** Add to `backend/db.py` or a new `backend/utils/serialize.py`:

```python
def safe_json_context(ctx):
    """Convert numpy/Decimal/datetime to JSON-serializable types."""
    if ctx is None:
        return None
    import json, decimal
    from datetime import datetime, date
    
    def _convert(v):
        if hasattr(v, 'item'):  # numpy scalars
            return v.item()
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return v
    
    if isinstance(ctx, dict):
        return {k: _convert(v) for k, v in ctx.items()}
    return ctx

# In _log_journal:
def _log_journal(trade_ref, strategy, event_type, price=None, context=None):
    safe_ctx = safe_json_context(context)
    execute(
        "INSERT INTO gd_journal (...) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, json.dumps(safe_ctx) if safe_ctx else None)
    )
```

**This eliminates the most likely root cause** (numpy/Decimal serialization) without us needing to chase down every numeric value's type.

### 2.4 Fix DWX EA Comment Parsing

**File:** `mql5/DWX_Server.mq5:261`

```cpp
// BEFORE — splits ALL '|' separators, dropping trade_ref portion
int n = StringSplit(cmd, '|', parts);
// ... parts[7] = comment, but only the part before second '|'

// AFTER — split only first 7 separators, keep rest of comment intact
int n = StringSplit(cmd, '|', parts);
// Reassemble parts[7..n-1] back into the comment field
string comment = parts[7];
for(int i = 8; i < n; i++) {
    comment = comment + "|" + parts[i];
}
```

**Or simpler:** Change the Python side to use a different delimiter:

```python
# In mt5_executor.py
cmd = f"OPEN|{symbol}|{order_type}|{lots}|{price}|{sl_price}|{tp_price}|{comment}"
# comment from caller is "strategy|trade_ref" — but | breaks DWX parsing

# Change to:
safe_comment = comment.replace("|", "_")  # OR use ~ as internal delimiter
```

The DWX fix is more correct (don't lose data); the Python fix is faster. **Recommend doing both** — Python first (5 min), DWX next deploy.

### 2.5 Add Regression Test

**File:** `tests/harness/test_17_orphan_prevention.py`

```python
def test_log_journal_failure_does_not_cascade():
    """If _log_journal raises, sweep blacklist must still update,
    and max_trades_per_day must still increment."""
    # Mock _log_journal to raise on ENTRY_FILLED
    # Mock place_market_order to return success
    # Run scheduler scan
    # Assert: trade placed once, _traded_sweeps has the sweep_key,
    #         _daily_state["trades"] == 1, second scan does NOT place another order

def test_orphan_position_gets_adopted():
    """A position on broker but not in DB should be adopted by reconciler."""
    # Setup: 1 broker position, 0 DB rows
    # Run reconcile_orphans()
    # Assert: gd_trades has 1 row with that broker_id, trade_ref starts with 'OIL-MI-orphan-'
```

**Time for Phase 2:** ~2 hours (changes + tests + deploy verification).

---

## Phase 3 — Defense in Depth (This Week)

The fixes in Phase 2 stop the specific bug. Phase 3 ensures **no orphan can survive even if some other bug appears later**. This is the production-grade layer.

### 3.1 Orphan Reconciliation Job (THE Key Addition)

**New function in each `live_engine.py`:**

```python
def reconcile_orphans():
    """Find broker positions that don't exist in DB and adopt them.
    Runs every minute alongside check_open_positions()."""
    broker_open = get_open_trades(instrument="BCO_USD")  # or XAU_USD
    
    db_open = execute(
        f"SELECT oanda_trade_id FROM gd_trades "
        f"WHERE exit_time IS NULL AND trade_ref LIKE '{TRADE_REF_PREFIX}%%'",
        fetch=True
    )
    db_ids = {r["oanda_trade_id"] for r in (db_open or [])}
    
    for pos in broker_open:
        bid = pos.get("id")
        if bid in db_ids:
            continue  # Already tracked
        
        # ORPHAN — adopt it
        trade_ref = f"{TRADE_REF_PREFIX}orphan-{bid[-8:]}"
        units = abs(int(pos["currentUnits"] * 1000))  # for oil
        side = "LONG" if pos["currentUnits"] > 0 else "SHORT"
        
        try:
            execute(
                """INSERT INTO gd_trades 
                   (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price,
                    lot_size, units, mode, oanda_trade_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'live', %s)
                   ON CONFLICT (oanda_trade_id) DO NOTHING""",
                (trade_ref, "micro_alpha_sweep_oil", side,
                 pos["openTime"], pos["price"], pos["sl"], pos["tp"],
                 abs(pos["currentUnits"]), units, bid)
            )
            _log_journal_safe(trade_ref, "micro_alpha_sweep_oil", "ORPHAN_ADOPTED",
                              pos["price"], {"broker_id": bid, "side": side})
            notify.error(f"ORPHAN ADOPTED: {trade_ref} (broker {bid}) — investigate logs")
        except Exception as e:
            print(f"Orphan adoption failed for {bid}: {e}")
```

**Wire it in scheduler.py:**

```python
def position_monitor_job():
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
        reconcile_orphans()  # ← NEW
    except Exception as e:
        ...
```

**Add unique constraint to gd_trades.oanda_trade_id:**

```sql
CREATE UNIQUE INDEX IF NOT EXISTS gd_trades_oanda_id_uniq
  ON gd_trades(oanda_trade_id) WHERE oanda_trade_id IS NOT NULL;
```

The `ON CONFLICT DO NOTHING` makes the adoption idempotent — running every minute is safe.

**Why this matters:** Even if Phase 2 fixes miss something, this safety net catches any orphan within 60 seconds and brings it under management. **It's the production guarantee.**

### 3.2 Telegram Error Alerts (Not Just Trade Events)

**File:** `backend/notify.py` — add `notify.error(msg)` if not present, then call it from:

- Scheduler outer try/except blocks
- DB INSERT failures
- Orphan adoption events
- Service startup/shutdown

```python
# In scheduler.py
except Exception as e:
    notify.error(f"OIL-MICRO scheduler crashed: {e}\n{traceback.format_exc()[:500]}")
    _log_journal_safe(...)
```

**Right now, when the system silently fails, you find out hours later via JustMarkets web.** With this, you'd get a Telegram alert within 60 seconds of the first orphan being detected.

### 3.3 Daily Reconciliation Report

**New cron job at 00:00 UTC daily:**

```python
def daily_reconciliation_report():
    """Send a Telegram summary of yesterday's trades + any anomalies."""
    yesterday = datetime.now(utc).date() - timedelta(days=1)
    
    db_count = execute("SELECT COUNT(*) FROM gd_trades WHERE entry_time::date = %s", (yesterday,))
    orphan_adoptions = execute("SELECT COUNT(*) FROM gd_journal WHERE event_type='ORPHAN_ADOPTED' AND timestamp::date = %s", (yesterday,))
    db_inserts_failed = execute("SELECT COUNT(*) FROM gd_journal WHERE event_type='DB_INSERT_FAILED' AND timestamp::date = %s", (yesterday,))
    
    notify.info(f"""
📊 Daily Recon — {yesterday}
Trades placed: {db_count}
Orphans adopted: {orphan_adoptions}  ← should be 0
DB INSERT failed: {db_inserts_failed}  ← should be 0
""")
```

If those numbers ever go above 0, you know to investigate immediately. **Operations visibility.**

**Time for Phase 3:** ~4 hours.

---

## Phase 4 — Long-term Hardening (Next Sprint)

Lower priority but worth doing for true production-grade reliability.

### 4.1 Health Check Endpoint

`/api/oil-micro/health` returns:
- `db_reachable: bool`
- `dwx_active: bool` (last market_data.json update < 30s ago)
- `scheduler_last_run: timestamp`
- `journal_recent_errors: int` (last 5 minutes)

Used by uptime monitoring (UptimeRobot, Healthchecks.io). If any goes false, alert.

### 4.2 Idempotent Order Placement

**New invariant:** Before calling `place_market_order`, generate a deterministic client-order-id from `(strategy, sweep_key, scan_timestamp)`. If the broker already has an order with that id, refuse to place. This prevents duplicate orders from rapid scheduler retries.

OANDA supports this natively. MT5/DWX would need EA changes.

### 4.3 Structured Logging

Replace `print(f"...")` with `logger.info(...)` and write to:
- stdout (existing logs/oil-micro.log)
- A structured JSON file `logs/oil-micro.jsonl`
- Optional: ship to Loki/Cloudwatch for searchability

When a future bug appears, "what was the system doing 5 hours ago?" becomes searchable instead of needing to scroll through `tail -10000`.

### 4.4 Service-level Auto-Recovery

If the scheduler hasn't successfully completed a cycle in 10 minutes (last_successful_run timestamp stale), the service should self-restart. Today, if the scan job hangs on a DB call, it stays hung forever.

**Time for Phase 4:** ~1-2 days.

---

## Summary by Priority

| Phase | What | When | Time | Risk if Skipped |
|---|---|---|---|---|
| **1** | Backfill 5 closed trades (with real PnL) + DD state + restart | Tonight | 25 min | Equity tracking off, DD state wrong, audit trail gap |
| **2.0** | **Disable OANDA stream on 3 MT5 systems** (NEW) | Before next scan | 15 min | Journal flooding continues, BE on 3 systems remains broken |
| **2** | Wrap journal calls, fix sweep ordering, sanitize JSON, fix DWX | Before tomorrow's scan | 2 hr | Same bug recurs on next anomaly |
| **3** | Orphan reconciler + Telegram error alerts + daily recon | This week | 4 hr | Future orphans go undetected for hours |
| **4** | Health checks, idempotency, logging, auto-recovery, MT5-tick BE | Next sprint | 1-2 days | Operational blindspots remain; BE precision suboptimal |

---

## Lessons Learned (Add to CLAUDE.md)

These belong in the "What NOT To Do" section of project memory:

- **Never call `_log_journal` (or any DB write) outside try/except in a critical path.** Journal writes are best-effort observability — they must never block trade tracking or position management.
- **In-memory deduplication state must be updated BEFORE the side-effecting call, not after.** Otherwise an exception in the side-effect lets the dedup miss → cascade of duplicate operations. This applies to `_traded_sweeps`, daily counters, cooldown timers — anything that prevents re-firing.
- **Every place that calls `place_market_order()` must have a corresponding orphan reconciler.** The system that places orders must also be the system that reconciles them. Position monitor + orphan reconciler must run on the same cadence.
- **JSON serialization in `json.dumps()` is a hidden landmine.** numpy floats, Decimal, datetime, custom objects all crash silently. Always pass through a sanitizer before any context dict goes to JSON.
- **`max_trades_per_day = max(db_count, local_counter)` is fragile.** Both can be 0 if INSERTs fail. A more correct guard is `db_count + len(unprocessed_orders_this_session)` — but the simpler fix is to make INSERTs robust (Phases 2-3).
- **The DWX EA's `StringSplit(cmd, '|', parts)` consumes ALL `|` separators** — which means any `|` in the comment field gets eaten. Either re-join `parts[7..n-1]` or pick a delimiter that won't appear in our comments.
- **Migrations between brokers must update EVERY service uniformly.** When we migrated from OANDA to JustMarkets MT5, only `backend/main.py` (Gold Macro) got the `if EXECUTOR != "mt5"` guard around the price stream startup. The other 3 services (Oil Macro, Gold Micro, Oil Micro) silently kept hitting OANDA endpoints with no token, flooding journals and burning CPU for weeks. **Migration checklist:** any "broker integration" change must include a grep for ALL services using the old broker's symbols/endpoints/tokens, not just the system you're focused on.
- **A shared infrastructure failure (OANDA stream loop) can mask a different bug.** The journal flooding from STREAM_DISCONNECTED events drowned out the search for ENTRY_FILLED events in our orphan investigation. Always **filter journal queries by event_type** when investigating, never trust a `LIMIT 200` view of mixed events.

---

## What I'm NOT Recommending (and Why)

- ✅ ~~Manually closing the 4 trades.~~ — User did this and it was the right call given the unrealistic TP and untrackable orphan state. **Updated**: Phase 1 is now backfill-as-closed instead of backfill-as-open.
- ❌ **Disabling Oil Micro pending fix.** The bug is now understood and the realized profit confirms the entry signals had directional edge. Better to deploy Phase 2 than to leave the system off.
- ❌ **Rewriting the entire signal pipeline.** The architecture is fine — the failure is one missing try/except and one out-of-order operation. Rewrite when there's a strategic reason, not when patching bugs.
- ❌ **Adding more retries inside `execute_signal`.** That just increases the number of duplicate orders if the underlying issue is broker-side. The right answer is making the cross-cycle state robust (Phase 2.2 + Phase 3.1).
- ❌ **Skipping the audit-trail backfill (Phase 1.4).** It's tempting to just leave the DB empty since the trades closed manually. Don't — the journal is your forensic record for next time something goes weird. A 4-trade gap with no entries makes future debugging much harder.
