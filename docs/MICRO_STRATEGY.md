# Gold Micro Alpha-Sweep — Live Code Path (Audit Document)

**Last updated:** May 28, 2026
**Service:** `backend-micro/` (port 5055)
**Instrument:** XAU_USD (Gold)
**Broker:** JustMarkets MT5 (Demo, USD account)
**Execution:** DWX Bridge (EA writes JSON files, Python reads/writes commands)

---

## 1. Scheduler Entry Point

**File:** `backend-micro/scanner/scheduler.py`
**Trigger:** APScheduler cron job `minute="*/3"` (every 3 minutes, 24/7)

```python
scheduler.add_job(micro_sweep_job, "cron", minute="*/3", id="micro_sweep_poll")
scheduler.add_job(position_monitor_job, "cron", minute="*", id="micro_position_monitor")
```

**Two jobs:**
- `micro_sweep_job()` — signal detection (every 3 min)
- `position_monitor_job()` — SL/TP/MaxHold monitoring (every 1 min)

---

## 2. Signal Detection Flow (`micro_sweep_job`)

### Step 2.1: Market Close Check

```python
close_start = cfg["market_close_start"]  # 21 UTC
close_end = cfg["market_close_end"]      # 22 UTC

if close_start <= current_hour < close_end:
    return []  # No scanning during 21:00-22:00 UTC (3:00-3:30 AM IST)
```

### Step 2.2: Daily Max Loss Check

```python
if DD_PROTECTION["daily_max_loss"] and _daily_state["pnl"] <= -DD_PROTECTION["daily_max_loss"]:
    return  # Stop trading after losing $400 in a day
```

- `daily_max_loss = $400`
- `_daily_state` resets at midnight UTC
- This is a circuit breaker — once hit, NO more signals for the rest of the day

### Step 2.3: Get Active Windows

```python
active_windows = _get_active_windows(now)
```

**`_get_active_windows(now)` logic:**

```python
for start_hour in range(0, 24, 2):  # Every 2 hours: 0, 2, 4, ..., 22
    end_hour = (start_hour + 4) % 24  # 4-hour consolidation
    scan_end_hour = (start_hour + 4 + 6) % 24  # 6-hour scan phase after

    # Skip if consolidation includes market close hour (21)
    consol_hours = _hours_in_range(start_hour, end_hour)
    if 21 in consol_hours:
        continue  # Skips windows 18-22 and 20-00

    # Consolidation must be done
    if not _hour_past(current_hour, end_hour):
        continue

    # Scan window must not be expired
    if _hour_past(current_hour, scan_end_hour):
        continue

    windows.append(...)
```

**Windows generated (10 total):**
```
22-02, 00-04, 02-06, 04-08, 06-10, 08-12, 10-14, 12-16, 14-18, 16-20
```

**Windows skipped (2):**
```
18-22 (hour 21 in consolidation), 20-00 (hour 21 in consolidation)
```

**`_hours_in_range(start, end)` — handles midnight wrap:**
```python
if start < end:
    return set(range(start, end))  # Normal: {8,9,10,11}
return set(range(start, 24)) | set(range(0, end))  # Wrap: {22,23,0,1}
```

**`_hour_past(current, target)` — handles midnight wrap:**
```python
diff = (current - target) % 24
return 0 < diff <= 12  # Past if within last 12 hours
```

### Step 2.4: Max Trades Per Day Check

```python
existing = execute(
    "SELECT COUNT(*) FROM gd_trades WHERE trade_ref LIKE 'GD-MI-%' AND entry_time::date = %s",
    (today,)
)
if trades_today >= 3:  # max_trades_per_day
    return
```

- Queries DB for today's Micro trades
- Maximum 3 trades per calendar day (UTC)
- Applies BEFORE any signal processing

### Step 2.5: Fetch H1 Candles (from MT5 via DWX)

```python
h1_candles = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA")
              if c.get("complete", True)]
```

- Gets last 24 completed H1 bars
- Bid/Ask prices (not just mid)
- Only complete bars (current bar excluded)

### Step 2.6: Daily Bias Calculation (Variant C)

```python
daily_candles = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
yesterday = daily_candles[-2]  # Use yesterday, not today (incomplete)

mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
mid_high = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
mid_low = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
prev_range = mid_high - mid_low

if prev_range <= 0:
    bias = "neutral"
elif abs(mid_close - mid_open) / prev_range < 0.4:
    bias = "neutral"  # Weak body = indecisive day → allow both
else:
    bias = "bullish" if mid_close > mid_open else "bearish"
```

**Variant C rules:**
- Body ratio < 40% of day range → NEUTRAL (allow both sweep directions)
- Strong green body (≥40%) → BULLISH (only bullish sweeps trade)
- Strong red body (≥40%) → BEARISH (only bearish sweeps trade)

### Step 2.7: Build Consolidation Range (per window)

```python
consol_hours = _hours_in_range(window["consol_start"], window["consol_end"])
consol_bars = [c for c in h1_candles if parse_ts(c["timestamp"]).hour in consol_hours]

range_high = max(c["mid_high"] for c in consol_bars)
range_low = min(c["mid_low"] for c in consol_bars)
consol_range = range_high - range_low

if consol_range < 5.0:  # min_range
    continue  # Skip — range too narrow
```

- Uses MID prices: `(bid + ask) / 2`
- Minimum 2 bars required
- Range must be ≥ $5.00

### Step 2.8: Sweep Detection

```python
bearish_level = range_high + 2.0  # sweep_threshold
bullish_level = range_low - 2.0

# Check all H1 bars in scan phase
scan_hours = _hours_in_range(window["consol_end"], window["scan_until"])
for bar in h1_candles:
    if bar.hour in scan_hours:
        if bar["mid_high"] > bearish_level and bar["mid_close"] < range_high:
            sweep = ("bearish", bar["mid_high"])
        elif bar["mid_low"] < bullish_level and bar["mid_close"] > range_low:
            sweep = ("bullish", bar["mid_low"])
```

**Sweep conditions:**
- **Bearish sweep**: H1 bar HIGH > range_high + $2 AND CLOSE < range_high (wick above, snap back)
- **Bullish sweep**: H1 bar LOW < range_low - $2 AND CLOSE > range_low (wick below, snap back)
- Uses MID prices for detection

### Step 2.9: Bias Filter

```python
if bias != "neutral":
    if sweep_dir == "bullish" and bias != "bullish":
        continue  # BLOCKED: bullish sweep on bearish day
    if sweep_dir == "bearish" and bias != "bearish":
        continue  # BLOCKED: bearish sweep on bullish day
```

- Neutral bias → ALL sweeps pass
- Directional bias → only matching sweeps pass
- **This is why today (May 28) has 0 trades**: bearish bias + bullish sweep = mismatch

### Step 2.10: M3 Engulfing Detection

```python
m3_candles = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")

# Filter to 2-hour window after sweep
sweep_time = parse_ts(sweep_bar["timestamp"])
window_end = sweep_time + timedelta(hours=2)  # engulfing_window_hours
relevant_m3 = [c for c in m3_candles if sweep_time < ts <= window_end]

if len(relevant_m3) < 3:
    continue  # Not enough bars

# Skip first 2 M3 bars (skip_first_bar = True)
for j in range(2, len(relevant_m3)):
    co = (c["bid_open"] + c["ask_open"]) / 2
    cc = (c["bid_close"] + c["ask_close"]) / 2
    po = (prev["bid_open"] + prev["ask_open"]) / 2
    pc = (prev["bid_close"] + prev["ask_close"]) / 2

    ct, cb = max(co, cc), min(co, cc)  # current body top/bottom
    pt, pb = max(po, pc), min(po, pc)  # previous body top/bottom

    tol = 0.10  # ENGULFING_TOLERANCE ($0.10 for Gold)

    # Bullish engulfing: green candle wraps previous
    if sweep_dir == "bullish":
        if cc > co and cb <= pb + tol and ct >= pt - tol:
            → ENGULFING FOUND

    # Bearish engulfing: red candle wraps previous
    if sweep_dir == "bearish":
        if cc < co and cb <= pb + tol and ct >= pt - tol:
            → ENGULFING FOUND
```

**Engulfing rules:**
- Current candle body must WRAP previous candle body
- Tolerance: $0.10 (sub-spread noise allowed)
- Must be correct color (green for bullish sweep, red for bearish)
- Window: 2 hours after sweep bar closes
- First 2 M3 bars after sweep are skipped (volatility settling)

### Step 2.11: Entry / SL / TP Calculation

**Bullish entry:**
```python
bar_range = (c["ask_high"] + c["bid_high"]) / 2 - (c["ask_low"] + c["bid_low"]) / 2
entry = c["ask_close"] + slippage(bar_range)  # Buy at ASK + slippage
sl = sweep_wick - 0.30  # $0.30 below the trap wick
risk = entry - sl

if risk < 5.0:  # min_sl
    sl = entry - 5.0
    risk = 5.0

if risk < 0.3 or risk > consol_range * 0.8:
    continue  # Skip: risk too small or too large

tp = entry + consol_range * 2.0  # tp_multiplier = 2×
if tp - entry < risk * 0.8:
    continue  # Skip: reward too small
```

**Bearish entry:**
```python
entry = c["bid_close"] - slippage(bar_range)  # Sell at BID - slippage
sl = sweep_wick + 0.30
risk = sl - entry
tp = entry - consol_range * 2.0
```

**Slippage model:**
```python
def slippage(bar_range):
    return 0.03 + bar_range * 0.003 + random.uniform(0, 0.02)
```

---

## 3. Trade Execution (`execute_signal`)

**File:** `backend-micro/scanner/live_engine.py`

### Step 3.1: DD Protection Skip Check

```python
dd_state = _get_dd_state()  # Reads gd_dd_state WHERE id=3

if dd_state["pause_counter"] > 0:
    pause_counter -= 1
    return skip("paused_after_5_losses")
```

### Step 3.2: Daily Max Loss Check (again)

```python
if DD_PROTECTION["daily_max_loss"] and daily_pnl <= -400:
    return skip("daily_max_loss")
```

### Step 3.3: Account Equity Fetch

```python
acct = get_account_summary()  # Reads MT5 account_info.json via DWX
equity_usd = acct.get("nav_usd") or acct.get("nav") or acct.get("balance", 10000)
```

- Fetches LIVE account balance from MT5
- Fallback chain: nav_usd → nav → balance → 10000

### Step 3.4: Position Sizing

```python
risk_mult = _get_risk_multiplier(dd_state, equity_usd)
# 1.0 normal, 0.5 after 3 consecutive losses, 0.25 if equity below 20-trade MA

risk_pct = 4.0  # STRATEGY_RISK["micro_alpha_sweep"]
risk_dollar = equity_usd * (4.0 / 100) * risk_mult
units = int(min(risk_dollar / sl_distance, 100))  # MAX_UNITS = 100

if units < 1:
    return skip("units_too_small")
```

**Risk multiplier logic:**
```python
mult = 1.0
if consecutive_losses >= 3:
    mult = 0.5
# Equity MA: compare live NAV vs last 20 trades
if nav_usd < equity_ma_of_last_20_trades:
    mult *= 0.5
```

### Step 3.5: Place Market Order on MT5

```python
oanda_units = units if direction == "long" else -units

result = place_market_order(
    instrument="XAU_USD",
    units=oanda_units,
    sl=sl_price,
    tp=tp_price,
    comment="micro_alpha_sweep|GD-MI-abc12345",
)
```

**MT5 execution path:**
1. Python writes command file: `commands/cmd_1716894600000.txt` → `"OPEN|BUY|XAUUSD.ecn|0.67|4390.50|4385.20|4420.50|micro_alpha_sweep|GD-MI-abc12345"`
2. DWX EA reads command, calls `OrderSend()` with `ORDER_FILLING_FOK`
3. EA writes `last_response.json`: `{"success": true, "ticket": 1988736586, "fill_price": 4390.54, ...}`
4. Python reads response via `_wait_response(timeout=10)`

### Step 3.6: Persist to Database

```python
# Log signal
INSERT INTO gd_signals (strategy='micro_alpha_sweep', direction, entry_price, sl_price, tp_price, taken=True, trade_ref='GD-MI-...')

# Log trade
INSERT INTO gd_trades (trade_ref='GD-MI-...', strategy='micro_alpha_sweep', side='LONG/SHORT', entry_time=NOW(), entry_price, sl_price, tp_price, units, oanda_trade_id=ticket)

# Log journal event
INSERT INTO gd_journal (trade_ref, strategy='micro_alpha_sweep', event_type='ENTRY_FILLED', price, context={...})
```

### Step 3.7: Telegram Notification

```python
notify.trade_filled(trade_ref, "XAU_USD", direction, fill_price, units, sl_price, tp_price)
```

---

## 4. Position Monitoring (`position_monitor_job`)

**Runs:** Every 1 minute, 24/7

### Step 4.1: Fetch Open Micro Trades

```python
open_trades = execute(
    "SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL AND trade_ref LIKE 'GD-MI-%'"
)
```

### Step 4.2: Check Each Trade Against MT5

```python
oanda_open = get_open_trades()  # Reads open_orders.json
oanda_open_ids = {t["trade_id"] for t in oanda_open}

for trade in open_trades:
    if trade.oanda_id in oanda_open_ids:
        # Still open — check max hold
        bars_held = (now - entry_time).total_seconds() / 180  # M3 bars
        if bars_held >= 80:  # max_bars
            → Force close (MAX_HOLD)
    else:
        # Closed on MT5 side — detect exit reason
        → Fetch trade details, classify as SL/TP/CLOSED
```

### Step 4.3: Max Hold (80 M3 bars = 4 hours)

```python
if bars_held >= 80:
    result = close_trade(oanda_id)
    exit_reason = "MAX_HOLD"
```

### Step 4.4: SL/TP Detection

```python
details = get_trade_details(oanda_id)
fill_price = details["price"]

if abs(fill_price - sl_price) < 2:   # ±$2 tolerance
    exit_reason = "SL"
elif abs(fill_price - tp_price) < 2:
    exit_reason = "TP"
else:
    exit_reason = "CLOSED"
```

### Step 4.5: DD State Update After Exit

```python
if realized_pl > 0:
    consecutive_losses = 0
else:
    consecutive_losses += 1
    if consecutive_losses >= 5:
        pause_counter = 2  # Skip next 2 signals

UPDATE gd_dd_state SET consecutive_losses, pause_counter WHERE id=3
```

---

## 5. Break-Even Management (`check_alpha_sweep_breakeven`)

**Trigger:** Every 1 minute (part of position_monitor_job)

```python
for trade in open_micro_trades:
    entry = trade.entry_price
    tp = trade.tp_price
    sl = trade.sl_price

    if side == "LONG":
        if tp <= entry or sl >= entry:
            continue  # Already at BE or invalid
        target_50 = entry + (tp - entry) * 0.5
        if current_bid >= target_50:
            new_sl = entry + 0.30  # Lock in $0.30 profit
            modify_stop_loss(trade_id, new_sl)

    if side == "SHORT":
        if tp >= entry or sl <= entry:
            continue
        target_50 = entry - (entry - tp) * 0.5
        if current_ask <= target_50:
            new_sl = entry - 0.30
            modify_stop_loss(trade_id, new_sl)
```

**Break-even fires ONCE** — when SL is already at/above entry (LONG) or at/below entry (SHORT), it's skipped.

---

## 6. Configuration (`backend-micro/config.py`)

```python
MICRO_ALPHA_SWEEP = {
    "consol_hours": 4,              # Each window = 4 hours consolidation
    "scan_gap_hours": 2,            # New window every 2 hours
    "scan_after_hours": 6,          # Scan for 6 hours after consolidation
    "min_range": 5.0,               # Skip if range < $5
    "sweep_threshold": 2.0,         # Wick must break by $2+
    "sl_buffer": 0.30,              # SL sits $0.30 beyond wick
    "min_sl": 5.0,                  # Minimum $5 SL distance
    "tp_multiplier": 2.0,           # TP = 2× consolidation range
    "be_trigger_pct": 0.50,         # Break-even at 50% to TP
    "max_bars": 80,                 # Force close after 80 M3 bars (4 hours)
    "skip_first_bar": True,         # Skip first 2 M3 bars after sweep
    "engulfing_window_hours": 2,    # Search engulfing within 2 hours
    "max_trades_per_day": 3,        # Maximum 3 entries per day
    "market_close_start": 21,       # Market close starts 21:00 UTC
    "market_close_end": 22,         # Market close ends 22:00 UTC
}

ENGULFING_TOLERANCE = 0.10          # $0.10 body-wrap tolerance
STRATEGY_RISK = {"micro_alpha_sweep": 4.0}  # 4% risk per trade
MAX_UNITS = 100                     # Never more than 100 oz
TRADE_REF_PREFIX = "GD-MI-"         # Trade reference prefix
DD_STATE_ID = 3                     # DB row for Micro DD state

DD_PROTECTION = {
    "daily_max_loss": 400,          # Stop after $400 daily loss
    "half_after_consecutive": 3,    # Half risk after 3 losses
    "consecutive_loss_pause": 5,    # Pause after 5 losses
    "pause_signals": 2,             # Skip 2 signals during pause
}
```

---

## 7. Database Tables Used

| Table | How Micro Uses It |
|-------|-------------------|
| `gd_trades` | `trade_ref LIKE 'GD-MI-%'` — all Micro trades |
| `gd_signals` | `strategy = 'micro_alpha_sweep'` — all signal attempts |
| `gd_journal` | `trade_ref LIKE 'GD-MI-%'` — all events |
| `gd_dd_state` | `id = 3` — Micro-specific DD state |
| `gd_backtest_runs` | `strategies @> ['micro_alpha_sweep']` — Micro backtests |
| `gd_backtest_trades` | `run_id` from above — backtest trade details |

---

## 8. Isolation From Gold Macro and Oil

| Aspect | Gold Macro | Gold Micro | Oil |
|--------|:---------:|:----------:|:---:|
| Port | 5053 | 5055 | 5054 |
| Trade prefix | GD-AS- | GD-MI- | OIL- |
| DD state ID | 1 | 3 | 2 |
| Strategy name | alpha_sweep | micro_alpha_sweep | alpha_sweep_oil |
| Scan hours | 08:00-20:00 UTC | 22:00-21:00 UTC | 08:00-20:00 UTC |
| API prefix | /api/gold/ | /api/micro/ | /api/oil/ |

All three services share the same MT5 account but NEVER interfere:
- Each only modifies trades it created (filtered by trade_ref prefix)
- Each has its own DD state row
- Position monitor only checks its own trades
- Break-even only modifies its own SL

---

## 9. Fill Model Parity (Backtest = Live)

The backtest uses `backend/execution/fill_model.py` which implements:

```
Order of checks per bar:
1. Gap-through SL (open past SL) → fill at open price (worst case)
2. TP touch (bar high/low reaches TP) → fill at TP (OANDA/MT5 limit behavior)
3. SL touch (bar low/high reaches SL) → fill at SL + adverse slippage
4. Break-even check (if enabled)
5. Max bars → exit at close
```

**Same logic applies live:**
- MT5 server-side SL/TP orders execute on touch
- Gap-through fills at market open (same as backtest)
- Break-even modifies SL via DWX command

---

## 10. What Makes This Strategy NOT Trade

The strategy correctly sits out when:
1. **No sweep pattern** — price stays inside consolidation range (most common)
2. **Bias mismatch** — sweep direction conflicts with yesterday's candle
3. **No engulfing** — sweep detected but no reversal candle within 2 hours
4. **Risk too large** — SL distance > 80% of consolidation range
5. **Risk too small** — SL distance < $0.30
6. **Reward too small** — TP - entry < 80% of risk
7. **Daily max loss** — already lost $400 today
8. **Paused** — 5 consecutive losses, skipping 2 signals
9. **Max trades** — already 3 trades today
10. **Market closed** — 21:00-22:00 UTC (3:00-3:30 AM IST)
11. **Range too small** — consolidation < $5 (not tradeable)
12. **One-way move** — price crashes without bouncing (no sweep can form)

---

## 11. Backtest vs Live Parity Status

| Aspect | Backtest | Live | Match |
|--------|:--------:|:----:|:-----:|
| Window generation | 0-22 with midnight wrap | 0-22 with midnight wrap | ✅ |
| Market close skip | hour 21 excluded | hour 21 excluded | ✅ |
| Bias filter (Variant C) | 0.4 ratio threshold | 0.4 ratio threshold | ✅ |
| Max trades/day | 3 (in-memory) | 3 (DB query) | ✅ |
| Engulfing tolerance | $0.10 | $0.10 | ✅ |
| Engulfing window | 2 hours | 2 hours | ✅ |
| Sweep threshold | $2.00 | $2.00 | ✅ |
| SL buffer | $0.30 | $0.30 | ✅ |
| TP multiplier | 2× range | 2× range | ✅ |
| Break-even | 50% trigger | 50% trigger | ✅ |
| Max hold | 80 M3 bars | 80 M3 bars | ✅ |
| Daily max loss | $400 | $400 | ✅ |
| Half after 3 losses | ✅ | ✅ | ✅ |
| Fill model | SL before TP, gap-through | Server-side SL/TP | ≈ (same logic) |
| Slippage | 0.03 + BR×0.003 + rand | Real broker slippage | ≈ (conservative) |

**Known difference:** Backtest is ~22% conservative on trade count (point-in-time vs retrospective scanning). Live catches slightly more overlapping-window setups.

---

## 12. Verified May 28, 2026

**System correctly produced 0 trades because:**
- Gold crashed $60+ (4450 → 4390) without any upward bounce
- Daily bias = BEARISH (yesterday strong red candle)
- Only bearish sweeps allowed, but bearish sweep needs price to go UP first then fail
- One bullish sweep detected (wick $4443) but blocked by bias_mismatch
- Backtest would produce same result on this day

**MT5 execution verified May 28, 2026 01:00 IST:**
- Place order: PASS ✓ (FOK fill mode)
- Modify SL: PASS ✓
- Close trade: PASS ✓ (with stale response clearing)
