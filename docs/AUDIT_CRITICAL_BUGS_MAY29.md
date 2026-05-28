# Critical Audit Report — Gold Micro System (May 29, 2026)

**Auditor:** Claude (GOD MODE — adversarial, skeptical, assume everything broken)
**Scope:** Full live trading path + backtest parity
**Verdict:** 3 CRITICAL bugs that WILL cause money loss if not fixed before market open

---

## 🔴 CRITICAL #1: Daily Max Loss Circuit Breaker is DEAD CODE

### What it should do:
Stop all trading after losing $400 in a single day. This prevents catastrophic drawdowns.

### What actually happens:
The variable `_daily_state["pnl"]` is initialized to 0.0 at the start of each day and **NEVER UPDATED** with actual trade P&L. The check `if _daily_state["pnl"] <= -400` can literally never trigger because `_daily_state["pnl"]` is always 0.

### Where the bug lives:
**File:** `backend-micro/scanner/scheduler.py`

```python
# Line 20: initialized
_daily_state = {"date": None, "pnl": 0.0, "trades": 0}

# Line 98: checked (ALWAYS passes because pnl is always 0)
if DD_PROTECTION["daily_max_loss"] and _daily_state["pnl"] <= -DD_PROTECTION["daily_max_loss"]:
    return

# Line 358: trades counter incremented but NOT pnl
trades_today += 1
_daily_state["trades"] += 1
# ← WHERE IS _daily_state["pnl"] += pnl ???
```

### Impact:
- System takes 3 trades per day regardless of losses
- Worst case: 3 × SL ($19 risk × 100 units = $1,900 per trade × 3 = $5,700 in one day)
- The "daily max loss $400" protection we tested and validated in backtest DOES NOT EXIST in live

### Fix needed:
In `check_open_positions()` when a trade closes, update `_daily_state["pnl"]` with the realized P&L. Also query actual daily P&L from DB at job start as a backup.

---

## 🔴 CRITICAL #2: MAX_HOLD Force-Close Crashes

### What it should do:
After 80 M3 bars (4 hours), force-close the position and record the exit in DB.

### What actually happens:
`mt5_executor.close_trade()` returns `{"success": True, "close_price": X, "realized_pl": Y}` — no `"time"` field. But `live_engine.py` accesses `result["time"]` which throws `KeyError`. The trade IS closed on MT5 but the DB update NEVER happens.

### Where the bug lives:
**File:** `backend-micro/scanner/live_engine.py` line ~215

```python
result = close_trade(oanda_id)
if result.get("success"):
    # ...
    execute("UPDATE gd_trades SET exit_time=%s ...", (result["time"], ...))
    #                                                  ^^^^^^^^^ CRASHES HERE
```

**File:** `backend/execution/mt5_executor.py` — close_trade response:
```python
return {
    "success": True,
    "close_price": result.price,
    "realized_pl": result.profit,
    # NO "time" FIELD!
}
```

### Impact:
- Trade force-closed on MT5 ✓
- DB still shows trade as "open" (exit_time = NULL)
- Next cycle: "one position at a time" check sees open trade → blocks ALL new signals
- System is permanently stuck until manual DB intervention
- Alternatively: position monitor's estimation branch eventually fires, but with WRONG PnL

### Fix needed:
Use `result.get("time", datetime.now(timezone.utc).isoformat())` or add `"time"` to mt5_executor's close response.

---

## 🔴 CRITICAL #3: Orphaned Position on _log_signal Failure

### What it should do:
After order fills on MT5, save the signal and trade to DB, then return trade_ref.

### What actually happens:
The call sequence after a successful fill:

```python
fill_price = result["fill_price"]       # ← Success! Trade exists on MT5
oanda_trade_id = result["trade_id"]

_log_signal(...)  # ← Line 176: OUTSIDE try/except. If this throws...
                  #    → exception propagates up
                  #    → trade_ref NEVER returned
                  #    → scheduler thinks signal failed
                  #    → next cycle: no cooldown (no signal in DB)
                  #    → no "open position" check (no trade in DB)
                  #    → places ANOTHER order!

try:
    execute("INSERT INTO gd_trades ...")  # Line 180-188: this IS in try/except
except Exception as e:
    print(f"DB INSERT FAILED...")
```

### Impact:
- MT5 has a real position (money at risk)
- DB has NO record of it
- System doesn't know the position exists
- No break-even monitoring
- No max-hold monitoring  
- No exit detection
- Allows duplicate positions (the EXACT bug that caused 10 duplicates on May 28)
- Position runs until SL/TP hit on MT5 — but P&L never recorded in DB

### When it triggers:
- DB connection timeout (network blip)
- Unique constraint violation on gd_signals (if trade_ref somehow duplicates)
- Any psycopg2 error during _log_signal INSERT

### Fix needed:
Wrap `_log_signal()` in its own try/except, or move it inside the existing try block. Return `trade_ref` ALWAYS after successful fill regardless of what happens to DB writes.

---

## 🟠 HIGH #4: Backtest Position Sizing is 2x More Conservative Than Live

### The mismatch:
**Backtest** (`backend-micro/backtest/engine.py` lines 143-146):
```python
risk_mult = get_risk_multiplier(state)  # Returns 0.5 when consecutive_losses >= 3
if state.consecutive_losses >= HALF_AFTER_CONSECUTIVE:
    risk_mult *= 0.5  # SECOND halving! Net = 0.25x
```

**Live** (`backend-micro/scanner/live_engine.py` line 80-87):
```python
def _get_risk_multiplier(dd_state, nav_usd):
    mult = 1.0
    if dd_state["consecutive_losses"] >= DD_PROTECTION["half_after_consecutive"]:
        mult = 0.5  # Only ONE halving. Net = 0.5x
    # equity MA check can add another 0.5 → max 0.25x
```

### Impact:
- After 3 consecutive losses, backtest uses 0.25x position size, live uses 0.5x
- Backtest shows smaller drawdowns than live will actually experience
- The "max DD -24.1%" from backtest could be -35%+ in live during a losing streak
- We validated the system on artificially conservative numbers

### Fix needed:
Remove the duplicate halving from backtest engine (line 146), OR add it to live. Choose one — they must match.

---

## 🟠 HIGH #5: Incomplete H1 Bars Pass Sweep Detection

### The mismatch:
**Backtest:** H1 bars from CSV are ALL complete (historical data).
**Live:** `get_candles(granularity="H1", count=24)` from MT5 DWX may include the currently-forming bar.

The filter `c.get("complete", True)` is supposed to remove incomplete bars, but **MT5 executor does NOT return a `"complete"` field** — so the default `True` means ALL bars pass.

### Impact:
- At 14:35 UTC, the 14:00 bar is only 35 minutes old
- If price temporarily spikes above sweep level but closes below by 15:00 → backtest would NOT see it as a sweep (bar closes back inside)
- But live sees it mid-bar and triggers
- Estimated: ~1 false sweep per 2-3 weeks → 1 bad trade → one SL hit ($200-400)

### Fix needed:
Filter by timestamp: only use H1 bars where `bar_timestamp + 3600 <= now`.

---

## 🟠 HIGH #6: Window 22-02 Uses Different Data in Backtest vs Live

### The mismatch:
**Backtest** processes day by day: `for date in dates: day_h1 = gold_h1[gold_h1.index.date == date]`

For the 22-02 window on January 15:
- Consolidation hours: {22, 23, 0, 1}
- BUT `day_h1` only contains bars from Jan 15
- Hours 22 and 23 don't exist on Jan 15 (they're Jan 14)
- Result: only 2 bars (00:00, 01:00) used for range

**Live** fetches last 24 H1 bars regardless of date boundary:
- Gets hours 22 (yesterday), 23 (yesterday), 00 (today), 01 (today)
- Full 4-bar range

### Impact:
- Live computes a WIDER range for window 22-02 (4 bars)
- Backtest computes a NARROWER range (2 bars)
- Different sweep levels → different signals
- Trades from this window in live have NOT been validated by backtest
- These represent ~11% of all trades (Asian session from the session breakdown)

### Fix needed:
Make backtest include previous day's bars for overnight windows, OR make live only use same-day bars.

---

## 🟡 MEDIUM #7: Break-Even SL Distance Differs

**Backtest:** `current_sl = entry + _sl_slip(bar_range)` → typically entry + $0.03-$0.07
**Live:** `new_sl = entry + 0.30` → always entry + $0.30

Live gives 6x more room after BE triggers. Live will slightly outperform backtest for BE trades.

---

## 🟡 MEDIUM #8: Max-Hold Bar Count vs Wall Clock

**Backtest:** Counts actual M3 bars in the dataframe (skips market close gap).
**Live:** `(now - entry_time).total_seconds() / 180` — counts elapsed time including market close.

For a trade entered at 20:00 UTC (before close), live will count the 21:00-22:00 close hour as ~20 bars of "holding." Backtest skips it (no bars during close). Live exits 1 hour earlier.

---

## 🟡 MEDIUM #9: Equity MA Formula Differs

**Backtest:** `np.mean(state.equity_history[-20:])` — rolling equity after each trade.
**Live:** `equity_20_ago = nav - cumulative_pnl_last_20; MA = (equity_20_ago + nav) / 2` — linear approximation.

These diverge when equity trajectory is non-linear (which it often is during drawdowns).

---

## 🟡 MEDIUM #10: Incomplete M3 Bar in Engulfing Detection

If scheduler fires at minute :01 (not aligned with M3 bar close), the last M3 bar is incomplete. Could show bullish body (current = high) that triggers engulfing, but bar might close bearish. Partially mitigated by `*/3` cron alignment, but not guaranteed.

---

## SUMMARY TABLE

| # | Severity | Issue | Money Impact |
|---|:--------:|-------|:----------:|
| C1 | 🔴 CRITICAL | Daily max loss is dead code | Up to $5,700/day unprotected |
| C2 | 🔴 CRITICAL | MAX_HOLD close crashes | System gets stuck, no new trades |
| C3 | 🔴 CRITICAL | Orphan position on _log_signal fail | Duplicate orders, unmonitored positions |
| H4 | 🟠 HIGH | Backtest double-halves (0.25x vs live 0.5x) | Live DD 2x worse than backtest shows |
| H5 | 🟠 HIGH | Incomplete H1 bar = false sweep | ~$200-400 per false trade |
| H6 | 🟠 HIGH | Window 22-02 data mismatch | 11% of trades unvalidated |
| M7 | 🟡 MEDIUM | BE distance: $0.05 vs $0.30 | Live outperforms backtest slightly |
| M8 | 🟡 MEDIUM | Max-hold: bars vs wall clock | Live exits 1hr earlier on overnights |
| M9 | 🟡 MEDIUM | Equity MA formula mismatch | Risk mult triggers at different levels |
| M10 | 🟡 MEDIUM | Incomplete M3 in engulfing | Rare false engulfing |

---

## RECOMMENDATION

**DO NOT go live without fixing C1, C2, C3.** These are not theoretical — C3 already caused the May 28 duplicate crisis. C1 means the "$400 daily cap" we keep citing is a lie. C2 means any 4-hour trade will permanently lock the system.

**Fix H4 before trusting backtest numbers.** The reported "max DD -24.1%" is artificially low. Real live DD could be -35%+ during a losing streak because position sizing is 2x larger than what was tested.

**H5 and H6 together mean ~15% of live trades have questionable edge** (false sweeps from incomplete bars + unvalidated overnight window). These won't cause catastrophic loss but will erode PF over time.
