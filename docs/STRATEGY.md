# Alpha-Sweep Strategy — How It Works (Start to Finish)

## The Core Idea

> Asia session (00:00-08:00 UTC) creates a range. When London/NY breaks below or above that range and snaps back (a "sweep"), we look for a reversal engulfing candle on the 3-minute chart and trade back into the range with a 2× Asia Range target.

---

## Step 1: Asia Range Formation (00:00 – 08:00 UTC)

Every day, price consolidates during the quiet Asian session. The system records:

```
asia_high = highest price in 00:00-08:00 UTC
asia_low  = lowest price in 00:00-08:00 UTC
asia_range = asia_high - asia_low
```

**Skip if:** Asia range < $5 (too narrow, not tradeable)

**Example:** Gold consolidates between $4,495 and $4,538
- asia_high = $4,538.65
- asia_low = $4,495.90
- asia_range = $42.75

---

## Step 2: Daily Bias Filter (Variant C)

Checks yesterday's daily candle to filter sweep direction:

```
body_ratio = |close - open| / (high - low)

If body_ratio >= 0.4:
   Green candle → bias = "bullish" (only allow bullish sweeps)
   Red candle   → bias = "bearish" (only allow bearish sweeps)
If body_ratio < 0.4:
   bias = "neutral" (allow BOTH directions)
```

**Example:** Yesterday closed red with strong body (ratio 0.6) → bias = "bearish" → only bearish sweeps allowed today.

---

## Step 3: Sweep Detection (08:00 – 20:00 UTC, every 3 min)

Sweep = price wicks beyond Asia range but closes back inside.

**Bearish Sweep** (price spikes above Asia):
```
H1 bar high > asia_high + $2.00 (sweep threshold)
AND H1 bar close < asia_high (snapped back inside)
```

**Bullish Sweep** (price dips below Asia):
```
H1 bar low < asia_low - $2.00
AND H1 bar close > asia_low (snapped back inside)
```

**Example:** At 11:00 UTC, an H1 bar:
- Wicks down to $4,481.82 (below $4,493.90 sweep level)
- Closes back at $4,498 (above asia_low $4,495.90)
- → **Bullish sweep detected!**

**Skip if:** Sweep direction doesn't match daily bias (bias_mismatch)

---

## Step 4: Engulfing Bar Search (2-hour window after sweep)

After a sweep, the system watches 3-minute (M3) bars for a reversal engulfing pattern.

**What's an engulfing?**
```
Current candle's body completely wraps previous candle's body
(with $0.10 tolerance for gold, $0.01 for oil)
```

**Bullish engulfing** (after bullish sweep):
- Current bar closes green (close > open)
- Current body-bottom ≤ previous body-bottom + $0.10
- Current body-top ≥ previous body-top - $0.10

**Bearish engulfing** (after bearish sweep):
- Current bar closes red (close < open)
- Same body wrapping logic

**Window:** Only checks bars 2+ (skips first 2 M3 bars after sweep)

**Skip if:** No engulfing found within 2 hours → sweep expires

---

## Step 5: Entry / SL / TP Calculation

Once engulfing is confirmed:

**Bullish Trade (long):**
```
entry = engulfing bar ask_close + slippage
sl    = sweep_wick - $0.30 (below the trap wick)
tp    = entry + asia_range × 2.0

risk = entry - sl
If risk < $5.00 → widen SL to $5.00 minimum
```

**Bearish Trade (short):**
```
entry = engulfing bar bid_close - slippage
sl    = sweep_wick + $0.30 (above the trap wick)
tp    = entry - asia_range × 2.0
```

**Example (bullish):**
```
entry = $4,498.30
sl    = $4,481.82 - 0.30 = $4,481.52
tp    = $4,498.30 + (42.75 × 2) = $4,583.80
risk  = $4,498.30 - $4,481.52 = $16.78
```

**Skip if:**
- risk > asia_range × 0.8 (SL too wide)
- reward < risk × 0.8 (R:R too low)

---

## Step 6: Position Sizing

```
risk_pct = 4% of account
equity   = $10,000 (from broker)
risk_mult = 1.0 (normal), 0.5 (after 3 losses), 0.25 (3 losses + equity below MA)

risk_dollar = $10,000 × 4% × 1.0 = $400
units = min($400 / $16.78, 100) = min(23.8, 100) = 23 units
```

**Max units cap:** 100 (gold), 5000 (oil)

---

## Step 7: Order Execution

```
→ OANDA/MT5 market order: BUY 23 units XAU_USD
  SL: $4,481.52
  TP: $4,583.80
  Comment: "alpha_sweep|GD-AS-abc123"
```

Logged to DB: `gd_signals` (taken=true), `gd_trades`, `gd_journal` (ENTRY_FILLED)

---

## Step 8: Break-Even Management (every 1 min while in position)

When price reaches **50% of the way to TP**, SL moves to entry + $0.30:

```
target_50 = entry + (tp - entry) × 0.5
          = $4,498.30 + ($4,583.80 - $4,498.30) × 0.5
          = $4,541.05

When bid >= $4,541.05:
  new_sl = $4,498.30 + $0.30 = $4,498.60  (guaranteed small profit)
  → Modify SL on OANDA/MT5
```

---

## Step 9: Exit (one of these happens)

| Exit | Trigger | Example |
|------|---------|---------|
| **TP** | Price hits take-profit | Exits at $4,583.80 (+$85.50) |
| **SL** | Price hits stop-loss | Exits at $4,481.52 (-$16.78) |
| **BE** | Price hits break-even SL | Exits at $4,498.60 (+$0.30) |
| **MAX_HOLD** | 80 M3 bars = 4 hours | Force close at market price |

**Detection:** Every 1 minute, system checks if OANDA/MT5 closed the trade:
- Trade disappears from open positions → fetch exit details
- Classify: near SL → "SL", near TP → "TP", 80+ bars → force close

---

## Step 10: Drawdown Protection (after exit)

```
If WIN:  consecutive_losses = 0
If LOSS: consecutive_losses += 1

If consecutive_losses >= 3: next trade = HALF size (0.5× risk)
If consecutive_losses >= 5: PAUSE for 2 signals (skip next 2 trades)

equity += pnl_usd
peak_equity = max(peak_equity, equity)
```

---

## Full Timeline Example (One Trade Day)

```
00:00 UTC  Asia forms: $4,495.90 – $4,538.65 (range $42.75)
           Sweep levels: Bearish > $4,540.65, Bullish < $4,493.90

08:00 UTC  Scanning begins (every 3 min)
           Yesterday was red (bias = bearish → only bearish sweeps pass)

11:00 UTC  H1 bar wicks to $4,481.82 < $4,493.90 ✓ closes at $4,498 > $4,495.90 ✓
           → Bullish sweep detected!
           BUT bias = bearish, sweep = bullish → BIAS MISMATCH → SKIPPED

           (If bias were neutral or bullish, trade would have been taken)

20:00 UTC  Scan window closes. No trade today.
```

---

## Key Parameters (Gold)

| Parameter | Value | What it means |
|-----------|-------|---------------|
| Asia Min Range | $5.00 | Don't trade if Asia was too flat |
| Sweep Threshold | $2.00 | Wick must break level by $2+ |
| SL Buffer | $0.30 | SL sits $0.30 beyond the sweep wick |
| Min SL | $5.00 | Never risk less than $5 per unit |
| TP Multiplier | 2× | Target = 2× Asia range from entry |
| BE Trigger | 50% | Move SL to entry when halfway to TP |
| Max Hold | 80 bars | Force close after 4 hours (80 × 3min) |
| Engulfing Window | 2 hours | Must get engulfing within 2h of sweep |
| Max Trades/Day | 3 | Maximum 3 entries per day |
| Risk per Trade | 4% | Risk 4% of account balance |
| Max Units | 100 | Never more than 100 oz regardless |
| Engulfing Tolerance | $0.10 | Body-wrap allows $0.10 noise |
| Bias Body Ratio | 0.4 | <40% body/range = neutral bias |

---

## Oil Differences

| Parameter | Gold | Oil |
|-----------|------|-----|
| Sweep Threshold | $2.00 | $0.02 |
| SL Buffer | $0.30 | $0.01 |
| Min SL | $5.00 | $0.10 |
| Engulfing Tolerance | $0.10 | $0.01 |
| Max Units | 100 | 5000 |
| BE offset | $0.30 | $0.01 |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Every 3 min (08:00-20:00 UTC):                         │
│    1. Fetch H1 candles → detect Asia range              │
│    2. Fetch D1 candle → compute daily bias              │
│    3. Scan H1 bars → detect sweep                       │
│    4. Fetch M3 candles → find engulfing                 │
│    5. Calculate entry/SL/TP                             │
│    6. → execute_signal() in live_engine.py              │
│                                                          │
│  Every 1 min (24/7):                                    │
│    1. check_open_positions() → detect SL/TP closure     │
│    2. check_alpha_sweep_breakeven() → move SL to BE     │
│    3. Check MAX_HOLD → force close after 80 bars        │
│                                                          │
│  22:00 UTC Daily:                                       │
│    1. Cross-Market consensus check                      │
│    2. Mean-Rev dip-buy check                            │
│                                                          │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 LIVE ENGINE (live_engine.py)              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  execute_signal(strategy, direction, entry, sl, tp):    │
│    1. Load DD state from DB                             │
│    2. Check skip conditions (bias, pause, 50-MA)        │
│    3. Fetch account equity from broker                  │
│    4. Calculate risk_mult (DD protection)               │
│    5. Calculate units (position size)                   │
│    6. Place market order on OANDA/MT5                   │
│    7. Log to gd_signals, gd_trades, gd_journal         │
│                                                          │
│  check_open_positions():                                │
│    1. Query DB for open trades (exit_time IS NULL)      │
│    2. Check if still open on broker                     │
│    3. If closed → determine exit reason (SL/TP/CLOSED) │
│    4. Update DD state (win resets, loss increments)     │
│    5. Log to gd_journal                                 │
│                                                          │
│  check_alpha_sweep_breakeven():                         │
│    1. For each open alpha_sweep trade                   │
│    2. If SL already at/above entry → skip              │
│    3. Calculate 50% target                              │
│    4. If price >= target → modify SL to entry+buffer   │
│                                                          │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              EXECUTOR (oanda_executor / mt5_executor)     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  get_current_price(instrument)                          │
│  get_candles(instrument, granularity, count)            │
│  get_account_summary()                                  │
│  place_market_order(instrument, units, sl, tp)          │
│  modify_stop_loss(trade_id, new_sl)                     │
│  close_trade(trade_id)                                  │
│  get_open_trades(instrument)                            │
│  get_trade_details(trade_id)                            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `gd_signals` | Every signal generated (taken or skipped, with skip_reason) |
| `gd_trades` | Every trade from entry to exit (entry/exit price, SL, TP, PnL) |
| `gd_journal` | Every event (ENTRY_FILLED, EXIT_FILLED, BREAK_EVEN, ORDER_FAILED) |
| `gd_dd_state` | Drawdown state (consecutive_losses, pause_counter, equity) |

---

## Backtest Results (2020-2025, $5,000 start, 4% risk)

| Metric | Gold | Oil |
|--------|------|-----|
| Total Trades | ~1,200 | ~1,800 |
| Win Rate | 42-45% | 40-43% |
| Profit Factor | 3.0-3.5 | 2.5-3.0 |
| Annual Return | ~$100K+ | ~$80K+ |
| Max Drawdown | ~15% | ~18% |
