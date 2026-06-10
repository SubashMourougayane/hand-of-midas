# Production Fix Plan — Orphan Trade Cascade

**Date**: June 10, 2026  
**Trigger**: 4 orphan BRENT SHORT trades on broker, 0 in DB  
**Severity**: HIGH — silent failure mode that violates max_trades_per_day, loses tracking, loses Telegram visibility  
**Goal**: Eliminate the entire class of "orphan trade" failures via defense-in-depth

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

## Phase 1 — Immediate (Tonight, While 4 Trades Are Still Open)

### 1.1 Don't Close the Trades Manually

The 4 BRENT SHORTs have correct SL ($92.55) and TP ($88.99) on the broker side. The broker WILL execute them. Closing them now means giving up potential +$580 profit just to clean up DB state — that's panic, not engineering.

### 1.2 Backfill the DB So Position Monitor Adopts Them

Run the SQL below on the VPS Postgres. This makes the position monitor see them as normal trades. When they hit TP or SL on the broker side, `check_open_positions()` will detect the closure and update the DB rows correctly.

```sql
INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id) VALUES
('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 01:03:00+00', 91.45, 92.55, 88.99, 0.62, 620, 'live', '2031303852'),
('OIL-MI-rec-324884', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 01:06:00+00', 91.48, 92.55, 88.99, 0.61, 610, 'live', '2031324884'),
('OIL-MI-rec-450502', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 01:45:00+00', 91.53, 92.55, 88.99, 0.61, 610, 'live', '2031450502'),
('OIL-MI-rec-569381', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 02:27:00+00', 91.35, 92.55, 88.99, 0.62, 620, 'live', '2031569381');
```

### 1.3 Increment `_daily_state["trades"]` to Prevent More Entries Tonight

Restart Oil Micro service so its in-memory state matches reality. After restart, the cron sees `db_trades_today=4` from the backfilled rows → `max(4, 0)=4 >= max_trades_per_day=3` → **no more entries today**. This is automatic — no code change needed.

**Time:** 10 minutes total (SQL + service restart).

---

## Phase 2 — Code Fixes (Next Deploy, Before Tomorrow's Scan Window)

These are the minimal code changes to stop this exact failure mode.

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
| **1** | Backfill 4 orphan trades + restart Oil Micro | Tonight | 10 min | Position monitor doesn't track exits, BE doesn't fire |
| **2** | Wrap journal calls, fix sweep ordering, sanitize JSON, fix DWX | Before tomorrow's scan | 2 hr | Same bug recurs on next anomaly |
| **3** | Orphan reconciler + Telegram error alerts + daily recon | This week | 4 hr | Future orphans go undetected for hours |
| **4** | Health checks, idempotency, logging, auto-recovery | Next sprint | 1-2 days | Operational blindspots remain |

---

## Lessons Learned (Add to CLAUDE.md)

These belong in the "What NOT To Do" section of project memory:

- **Never call `_log_journal` (or any DB write) outside try/except in a critical path.** Journal writes are best-effort observability — they must never block trade tracking or position management.
- **In-memory deduplication state must be updated BEFORE the side-effecting call, not after.** Otherwise an exception in the side-effect lets the dedup miss → cascade of duplicate operations. This applies to `_traded_sweeps`, daily counters, cooldown timers — anything that prevents re-firing.
- **Every place that calls `place_market_order()` must have a corresponding orphan reconciler.** The system that places orders must also be the system that reconciles them. Position monitor + orphan reconciler must run on the same cadence.
- **JSON serialization in `json.dumps()` is a hidden landmine.** numpy floats, Decimal, datetime, custom objects all crash silently. Always pass through a sanitizer before any context dict goes to JSON.
- **`max_trades_per_day = max(db_count, local_counter)` is fragile.** Both can be 0 if INSERTs fail. A more correct guard is `db_count + len(unprocessed_orders_this_session)` — but the simpler fix is to make INSERTs robust (Phases 2-3).
- **The DWX EA's `StringSplit(cmd, '|', parts)` consumes ALL `|` separators** — which means any `|` in the comment field gets eaten. Either re-join `parts[7..n-1]` or pick a delimiter that won't appear in our comments.

---

## What I'm NOT Recommending (and Why)

- ❌ **Manually closing the 4 trades.** Throwing away $600 profit to clean up a tracking issue is wrong economics. The broker SL/TP works; we just need to track them.
- ❌ **Disabling Oil Micro pending fix.** The bug is now understood and the immediate trades are profitable. Better to deploy the fix in Phase 2 than to leave money on the table.
- ❌ **Rewriting the entire signal pipeline.** The architecture is fine — the failure is one missing try/except and one out-of-order operation. Rewrite when there's a strategic reason, not when patching bugs.
- ❌ **Adding more retries inside `execute_signal`.** That just increases the number of duplicate orders if the underlying issue is broker-side. The right answer is making the cross-cycle state robust (Phase 2.2 + Phase 3.1).
