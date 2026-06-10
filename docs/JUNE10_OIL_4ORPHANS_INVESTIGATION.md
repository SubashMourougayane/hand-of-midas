# June 10 — 4 Orphan Oil Trades Investigation

**Status**: Active orphans on broker, NO DB record  
**System**: Oil Micro (per MT5 comment)  
**Date**: June 10, 2026  
**Open positions**: 4 BRENT SHORT trades  
**Combined exposure**: ~2.46 lots (2,460 barrels)  
**Current Open P&L**: +$324.90 (per JM web)

---

## Q1: When Did These Trades Happen + Which System?

### Times (All Sources Reconciled)

| Order ID | JM Web (IST) | MT5 (Server GMT+3) | Real UTC |
|---|---|---|---|
| 2031303852 | 06:33 | 04:03 | **01:03** |
| 2031324884 | 06:36 | 04:06 | **01:06** |
| 2031450502 | 07:15 | 04:45 | **01:45** |
| 2031569381 | 07:57 | 05:27 | **02:27** |

### System: OIL MICRO (not Oil Macro)

**Evidence:**
- MT5 Magic Number = **200000** (our system's magic)
- MT5 Comment = **`'micro_alpha_sweep_oil'`** (Oil Micro's strategy name)

**Why Comment is missing the trade_ref portion:**
- Code passes `comment=f"{strategy}|{trade_ref}"` = `'micro_alpha_sweep_oil|OIL-MI-xxxxxxxx'`
- DWX EA at `mql5/DWX_Server.mq5:261` does `StringSplit(cmd, '|', parts)` — splits ALL `|` separators
- `parts[7]` (comment field) = only the part BEFORE the first `|` in comment = `'micro_alpha_sweep_oil'`
- **The trade_ref portion is silently dropped during parsing**

This is a **separate bug** in the DWX EA, not the cause of the orphans.

---

## Q2: Why No Telegram Messages?

**Telegram only fires at line 208 of `backend-oil-micro/scanner/live_engine.py`:**

```python
notify.trade_filled(trade_ref, "BCO_USD", direction, fill_price, units, sl_price, tp_price)
```

This line runs AFTER:
1. `place_market_order()` — succeeded (line 166)
2. `_log_signal()` (try/except wrapped, line 184)
3. DB INSERT into gd_trades (try/except wrapped, line 189)
4. `_log_journal("ENTRY_FILLED")` — **NOT try/except wrapped (line 202)**

**The Telegram call never runs because something between order placement and Telegram is raising an exception.**

---

## Q3: Why Same TP and SL on All 4 Trades?

All 4 trades have:
- TP: $88.99
- SL: $92.55

**Same TP/SL means same `range_high` and `range_low`**, which means **same consolidation window** detected the **same setup repeatedly**.

This confirms the trades came from a **looping scan cycle** that re-detected the same sweep multiple times.

---

## Q4: What Signals Contributed? Are They Legit?

### What We Don't Know
- `gd_signals` table has **0 rows** for `strategy='micro_alpha_sweep_oil'`
- `gd_journal` table has **0 events** for these trades
- `gd_trades` table has **0 rows** with `OIL-MI-` prefix
- Recent signals API returns **empty array**

### What We Can Infer
The strategy detected:
- A 4hr consolidation window with `range_high≈$92.57, range_low≈$88.97` (back-calculated from SL/TP + buffers)
- A bullish sweep BELOW range_low (price dipped below $88.95)
- An M3 bearish engulfing pattern
- Result: SHORT signal queued

**BUT we can't verify this from any logs because none were created.**

### Are the Signals Legit?
- BRENT was trading around $91 at the time
- Consolidation between $89-$93 is plausible for that price range
- A sweep below $89 followed by reversal would be a valid signal pattern
- **Without journal entries, we can't confirm what bars triggered the entries**

---

## Q5: Is This Execution Bug or Other?

**This is a SOFTWARE BUG with multiple layers:**

### Layer 1: DB Logging Failure (Primary Cause)

**Hypothesis**: `_log_journal("ENTRY_FILLED")` at line 202 of `live_engine.py` is raising an exception. This call is **not wrapped in try/except**, so the raise:
1. Skips Telegram notification
2. Returns control to scheduler's outer try/except
3. Scheduler logs the error to journal (which also fails)
4. **`_traded_sweeps["keys"].add(sweep_key)` at line 370 NEVER RUNS** (it's after `execute_signal` returns normally)

### Layer 2: Sweep Blacklist Not Updated (Cascade Effect)

Because `_traded_sweeps` blacklist is updated AFTER `execute_signal` succeeds:
- If `execute_signal` raises → sweep_key not added to blacklist
- Next scan (3 min later) → same sweep detected again → another order placed
- **Infinite loop while the sweep window is active**

### Layer 3: max_trades_per_day=3 Violation (Secondary Effect)

Counter check:
```python
trades_today = max(db_trades_today, _daily_state["trades"])
```

- `db_trades_today` = 0 (no INSERTs succeeded)
- `_daily_state["trades"]` = increments only AFTER `execute_signal` returns trade_ref
- If `execute_signal` raises before returning, `_daily_state["trades"]` stays 0
- **trades_today permanently equals 0 → max_trades_per_day filter never fires**

This is why we got **4 trades when config max is 3**.

### Layer 4: DWX Comment Parsing (Cosmetic)

`StringSplit(cmd, '|', parts)` in DWX EA splits the comment field at `|`. Our format `strategy|trade_ref` becomes only `strategy` after parsing. **trade_ref is silently lost in the broker's record.**

This means we can't recover the original trade_ref by looking at MT5 history alone.

---

## Most Likely Root Cause

**Suspected exception in `_log_journal`**:

```python
def _log_journal(trade_ref, strategy, event_type, price=None, context=None):
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, json.dumps(context) if context else None)
    )
```

The ENTRY_FILLED context contains:
```python
{
    "instrument": "BCO_USD", "units": units, "sl": sl_price, "tp": tp_price,
    "oanda_id": oanda_trade_id, "risk_mult": risk_mult, "risk_pct": risk_pct,
    "equity_usd": equity_usd,
}
```

**Possible failure modes:**
1. `risk_mult` is `numpy.float64` → not JSON-serializable
2. `equity_usd` is `Decimal` from psycopg2 → not JSON-serializable
3. `units` is calculated as `int(min(risk_dollar / sl_distance, MAX_UNITS))` — should be safe
4. DB connection pool exhausted intermittently

To confirm, we'd need to see the Oil Micro service logs at the exact moment of these 4 trades.

---

## Why Gold Micro Worked Earlier But Oil Micro Didn't

**Earlier success (Gold Micro 22:39 UTC):**
- Trade `GD-MI-c5ad6dbd` was logged correctly to all DB tables
- Telegram fired
- Recent signals show it as `taken=True`

**Oil Micro now (01:03-02:27 UTC):**
- 4 trades on broker, 0 in DB

**Same code path** in both files. So either:
- Something Oil Micro-specific in the data caused the failure
- A transient DB hiccup at that exact time
- A config/env difference (DD_STATE_ID? equity calc?)

---

## Immediate Action Items

### CRITICAL (Risk Management)

The 4 BRENT positions are SHORT with proper SL/TP set on broker side. Even though we have no DB record:
- Broker WILL hit SL at $92.55 if BRENT rises (max loss per trade ≈ $122)
- Broker WILL hit TP at $88.99 if BRENT falls (max gain per trade ≈ $145)
- **Max combined loss if all hit SL: ~$488**
- **Max combined gain if all hit TP: ~$580**
- **Currently +$324 unrealized — partial profit already**

### Decision Point: What To Do With These 4 Orphans?

**Option A — Let them run with broker SL/TP:**
- Pros: All 4 are profitable. Could ride to TP.
- Cons: We have no in-system tracking. Position monitor won't see them. Break-even won't fire.
- Risk: Loses BE protection but original SL still works

**Option B — Manually reduce to 1 position (close 3, keep best):**
- Pros: Reduces correlated exposure
- Cons: Manual intervention, still have orphan

**Option C — Close all 4 manually now:**
- Pros: Lock in the +$324 profit. Eliminate orphan risk.
- Cons: Misses potential +$580 if all hit TP

**Option D — Manually backfill DB with these 4 trades:**
- Run SQL to INSERT trade rows matching the broker positions
- Position monitor will pick them up and manage exits
- Required SQL provided below

### SQL to Backfill DB (Option D)

```sql
INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id) VALUES
('OIL-MI-recovered1', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 01:03:00+00', 91.45, 92.55, 88.99, 0.62, 620, 'live', '2031303852'),
('OIL-MI-recovered2', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 01:06:00+00', 91.48, 92.55, 88.99, 0.61, 610, 'live', '2031324884'),
('OIL-MI-recovered3', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 01:45:00+00', 91.53, 92.55, 88.99, 0.61, 610, 'live', '2031450502'),
('OIL-MI-recovered4', 'micro_alpha_sweep_oil', 'SHORT', '2026-06-10 02:27:00+00', 91.35, 92.55, 88.99, 0.62, 620, 'live', '2031569381');
```

### Code Fixes Needed

1. **Wrap `_log_journal` calls in try/except** (line 202, 107, 117 of Oil Micro)
2. **Move `_traded_sweeps["keys"].add(sweep_key)` BEFORE `execute_signal`** so blacklist is updated even if signal logging fails
3. **Fix DWX EA to escape `|` in comment** or use a different delimiter character
4. **Convert numpy/Decimal to native types** in journal context dicts before serializing

---

## TL;DR

**The bug:** `_log_journal("ENTRY_FILLED")` is raising an exception (likely JSON serialization issue with numpy/Decimal values), which:
1. Prevents Telegram notification
2. Prevents sweep blacklist update
3. Causes scheduler to retry the same sweep on next cycle
4. Each retry places another order
5. max_trades_per_day=3 doesn't fire because counter never increments

**Result:** 4 BRENT SHORT positions on broker, 0 in our DB.

**Fix:** Wrap journal call in try/except, fix `_traded_sweeps` ordering, fix DWX comment parsing.

**Immediate:** Decide what to do with the 4 orphan positions. They're currently +$324 in profit but have proper SL/TP on broker.
