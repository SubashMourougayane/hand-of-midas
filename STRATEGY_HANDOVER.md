# Oil Micro Alpha-Sweep — Strategy Specification

A mean-reversion intraday strategy for Brent Crude Oil (BCO/USD) on a 3-minute execution timeframe, using rolling 4-hour consolidation windows on the hourly chart for context.

---

## 1. Concept

The market frequently sets a small range, then probes (sweeps) one edge of that range — running stops or testing liquidity — and reverses back into the range. The strategy waits for that probe-and-reversal pattern, enters at the reversal candle, and targets the opposite end of the range.

Three time frames cooperate:

- **Daily (D1):** sets directional bias for the trade-date.
- **Hourly (H1):** defines the consolidation range and the sweep.
- **3-minute (M3):** confirms the reversal (engulfing candle) and walks the position to its exit.

---

## 2. Strategy logic

### 2.1 Daily bias (filter for direction)

Computed once per day from yesterday's daily bar.

Two heuristics, OR'd together with **bearish-priority** on conflict:

```
prev_range  = high - low
body_pct    = |close - open| / prev_range
close_pos   = (close - low) / prev_range

# V1 — body-strength
if body_pct >= 0.40:
    v1 = "bullish" if close > open else "bearish"
else:
    v1 = "neutral"

# V2 — close position within the range
if close_pos >= 0.80:  v2 = "bullish"
elif close_pos <= 0.20: v2 = "bearish"
else:                   v2 = "neutral"

# Combine — bearish wins ties
if v1 == "bearish" or v2 == "bearish":  bias = "bearish"
elif v1 == "bullish" or v2 == "bullish": bias = "bullish"
else:                                    bias = "neutral"
```

The filter rule:

- `bearish` bias → only short signals fire
- `bullish` bias → only long signals fire
- `neutral` bias → both directions fire

### 2.2 Consolidation window (on H1)

Every 2 hours, look at the previous 4 hours of hourly bars as a candidate consolidation window.

```
consol_hours      = 4 hours
scan_gap_hours    = 2 hours        (windows overlap by 2 hours)
scan_after_hours  = 6 hours        (post-consol scan window for sweep)
```

For each consolidation window:

- `range_high = max(H1 highs in window)`
- `range_low  = min(H1 lows  in window)`
- `range     = range_high − range_low`
- Reject if `range < min_range`.
- Reject windows that overlap the daily market-close hour.

### 2.3 Sweep detection (on H1)

After the consolidation window closes, scan up to 6 more H1 bars for a sweep candle:

- **Bearish sweep** (potential SHORT setup):  
  `bar.high > range_high + sweep_threshold` AND `bar.close < range_high`  
  → wick poked above the range and pulled back inside.
- **Bullish sweep** (potential LONG setup):  
  `bar.low < range_low − sweep_threshold` AND `bar.close > range_low`  
  → wick poked below the range and pulled back inside.

The wick price (`high` for bearish, `low` for bullish) is recorded as `sweep_wick`.

A sweep is consumed once it's used (or once an engulfing fails to appear in time) — it never fires twice.

### 2.4 Engulfing reversal (on M3)

After a valid sweep on H1, watch the next 45 minutes (15 M3 bars) for an engulfing candle in the reversal direction.

For candle `j` against the previous candle `j−1`:

```
ct, cb = max(open, close), min(open, close)        # current top, bottom
pt, pb = max(open[j-1], close[j-1]), min(...)      # previous top, bottom
tol    = engulfing_tolerance

# Bullish engulfing (after bullish sweep)
close > open AND cb <= pb + tol AND ct >= pt - tol

# Bearish engulfing (after bearish sweep)
close < open AND cb <= pb + tol AND ct >= pt - tol
```

The first M3 bar is skipped (start at `j = 2`) — gives the post-sweep reaction time to establish.

### 2.5 Trade construction

When an engulfing fires:

**LONG:**
```
slip  = 0.03 + bar_range * 0.01 + uniform(0, 0.005)
entry = ask_close[engulfing_bar] + slip
sl    = sweep_wick - sl_buffer
risk  = entry - sl
if risk < min_sl:  sl = entry - min_sl;  risk = min_sl
tp    = range_high - tp_structure_buffer
```

**SHORT:** (mirror)
```
entry = bid_close[engulfing_bar] - slip
sl    = sweep_wick + sl_buffer
risk  = sl - entry
tp    = range_low + tp_structure_buffer
```

Reject signal if any of:
- `risk < 0.01`
- `risk > consolidation_range * 0.80`  (SL too wide vs. range)
- reward < `risk * 0.80`               (less than 0.8R reward potential)

### 2.6 Entry execution: limit-order pullback

Rather than entering at market on the engulfing close, place a **limit order** at a small pullback into the engulfing bar:

```
limit_price = entry + limit_offset_pct * risk          # LONG
limit_price = entry - limit_offset_pct * risk          # SHORT
                  (limit_offset_pct is negative — convention)
```

The limit lives for `limit_ttl_bars` M3 bars (= TTL minutes / 3).

Fill rule (loose mode):

- LONG fills the moment any subsequent bar's `bid_low <= limit_price`.
- SHORT fills the moment any subsequent bar's `ask_high >= limit_price`.

If TTL expires without a fill, the signal is dropped (it does not consume the daily-trade-count cap).

### 2.7 Exit walk (on M3, post-fill)

For each subsequent M3 bar up to `max_bars`, check in order:

1. **Stop loss touch** — `bar_low <= current_sl` (LONG) or `bar_high >= current_sl` (SHORT). Exit at `current_sl`.
2. **Partial-TP touch** — if the bar's high (LONG) or low (SHORT) reaches the partial level, bank `partial_tp_size` of the position at `partial_target`, leave the runner in.
3. **Take profit touch** — if the bar reaches `tp`. Exit at `tp`. The position's reported PnL blends the partial bank and the runner exit.
4. **Break-even arming** — if not yet armed and `(bar_high + bar_low) / 2` has crossed `entry + be_trigger_pct * (tp − entry)`, set `current_sl = entry + small_offset`. Future SL checks use this tighter level.
5. **Optional post-BE trail** — if enabled, ratchet `current_sl` toward the high-water mark of price action since BE armed.

If `max_bars` elapse without an exit, close at the M3 close of bar `bar_start + max_bars`.

Notes on order of checks within a single bar:

- SL is checked **before** TP. A bar that touches both SL and TP within its range exits SL.
- Partial-TP is checked between SL and TP — if the bar reaches partial first then TP, the exit is `PARTIAL+TP`.

### 2.8 Same-bar special cases

- **Gap-through SL** at bar open (price opens past the SL level): exit immediately at the bar open price (worst case for a gapped bar).
- **Same-bar SL and TP both touched** (no gap): SL takes priority by the order-of-checks above.

---

## 3. Position sizing & risk

Per-trade risk in dollars:

```
risk_dollar = equity * (strategy_risk_pct / 100) * risk_multiplier
units       = min(risk_dollar / signal.risk, max_units)
```

`risk_multiplier` halves on either of:
- `consecutive_losses >= 3`
- `equity < mean(equity_history[-20:])`  (last-20-trade equity moving average)

Both conditions can stack: 3 consecutive losses **and** below 20-trade equity MA → multiplier 0.25.

`max_units` is a per-position barrel cap regardless of risk.

---

## 4. Per-day & cross-day gates

A signal must pass all of these to fire:

| Gate | Rule |
|---|---|
| Daily filled-trade cap | `day_filled_trades < max_trades_per_day`. Limit-TTL expiries don't count. |
| Cooldown | `now >= last_signal_time + 5 minutes`. |
| One-at-a-time | `now >= position_exit_time` (no overlap with prior open). |
| Equity floor | `equity >= 100`. |
| DD pause counter | If `pause_counter > 0`, decrement and skip. |

After each closed trade, update DD state:

```
if pnl > 0:
    consecutive_losses = 0
else:
    consecutive_losses += 1
    if consecutive_losses >= 5:
        pause_counter = 2          # skip next 2 signals
```

Daily reset (at session boundary):

- `day_filled_trades = 0`
- `daily_pnl = 0`

Yearly reset (Jan 1, optional but used in backtests):

- `equity = starting_capital`
- `consecutive_losses = 0`
- `pause_counter = 0`
- `equity_history = []`

This means yearly P&L numbers are *not compoundable* — each year is an independent account starting at the same capital.

---

## 5. Broker costs (applied to each closed trade)

```
lots               = units / lot_size
commission_dollars = lots * commission_per_lot_round_trip
nights_held        = floor(bars_held * bar_minutes / (24 * 60))     # rounded down
                     + 1 if bars_held crossed a rollover hour
swap_dollars       = -lots * swap_per_lot_per_night * nights_held   # cost is positive
total_cost         = commission_dollars + swap_dollars

pnl_after_costs    = pnl_dollars - total_cost
```

`swap_per_lot_per_night` differs for long vs. short positions.

---

## 6. Numeric parameters (production values)

### Strategy
| Parameter | Value | Unit |
|---|---|---|
| `consol_hours` | 4 | hours |
| `scan_gap_hours` | 2 | hours |
| `scan_after_hours` | 6 | hours |
| `min_range` | 0.33 | USD |
| `sweep_threshold` | 0.13 | USD |
| `sl_buffer` | 0.20 | USD |
| `min_sl` | 0.10 | USD |
| `tp_structure_buffer` | 0.13 | USD |
| `engulfing_tolerance` | 0.01 | USD |
| `engulfing_window_hours` | 0.75 | hours (= 45 min, 15 M3 bars) |
| `skip_first_bar` | true | (start engulfing search at j=2) |
| `max_bars` | 80 | M3 bars (= 4 hours) |
| `market_close_start` | 21 | UTC hour (inclusive) |
| `market_close_end` | 22 | UTC hour (exclusive) |

### Entry mode (limit-order pullback)
| Parameter | Value | Notes |
|---|---|---|
| `entry_mode` | `"limit"` | |
| `limit_offset_pct` | -0.10 | 10% of `risk`, away from entry into structure |
| `limit_ttl_bars` | 5 | M3 bars (= 15 min) |
| `limit_fill_strict` | false | any wick touch fills (no close-confirmation required) |

### Trade management
| Parameter | Value |
|---|---|
| `be_trigger_pct` | 0.35 |
| `partial_tp_at_pct` | 0.50 |
| `partial_tp_size` | 0.50 |
| `partial_arms_be` | false |
| `trail_after_be_pct` | 0.0 (disabled) |

### Sizing
| Parameter | Value |
|---|---|
| Yearly starting capital | 5,000 USD |
| Strategy risk per trade | 4.0 % of equity |
| `max_units` | 5,000 barrels |
| Cooldown between signals | 300 seconds (5 min) |
| `max_trades_per_day` | 3 |

### Drawdown protection
| Trigger | Action |
|---|---|
| `consecutive_losses >= 3` | risk × 0.5 |
| Below 20-trade equity MA | risk × 0.5 (compounds with above → 0.25) |
| `consecutive_losses >= 5` | `pause_counter = 2` (skip next 2 signals) |

### Broker cost model (Brent Crude on ECN)
| Parameter | Value |
|---|---|
| `lot_size` | 100 barrels |
| `commission_per_lot_rt` | 7.00 USD round-trip |
| `swap_long_per_lot_per_night` | -3.00 USD (cost) |
| `swap_short_per_lot_per_night` | -1.00 USD (cost) |

### Slippage model (deterministic)

```
slippage = 0.0325 + bar_range * 0.01
```

Applied in the trade's adverse direction at entry and at SL fills.

---

## 7. Data requirements

Three OHLC streams on the same instrument, indexed by UTC timestamp:

- **D1** (daily) — used for daily bias.
- **H1** (1-hour) — used for consolidation range and sweep detection.
- **M3** (3-minute) — used for engulfing detection, entry, exit walk.

Bars must include both bid and ask sides (or a `mid` derivable from them):
- `bid_open, bid_high, bid_low, bid_close`
- `ask_open, ask_high, ask_low, ask_close`
- `mid_*` = (bid + ask) / 2

**Daily bar timing convention.** If your daily bars are aligned to a non-midnight session anchor (e.g. 21:00 UTC), the bar dated `T` represents the session `T → T+1`. When you compute "yesterday's bias for trade-date `D`", look up the bar dated `D − 1 day`. Mis-aligning this is a silent off-by-one and inflates apparent edge.

---

## 8. Determinism

All random draws (slippage) come from a single seeded PRNG. Same seed + same data → identical trade list bit-for-bit. The seed is the only source of non-determinism.

---

## 9. Inputs / outputs of each component

### `generate_signals(d1, h1, m3, daily_bias) → list[Signal]`
Pure function. Walks H1 day by day, applies sections 2.2–2.5, returns signals sorted by timestamp. Each signal carries `(date, entry, sl, tp, direction, risk, max_bars, metadata)`.

### `execute_trade(m3, bar_start, signal, ...) → Result`
Pure function. Applies sections 2.6 (limit fill if enabled) and 2.7 (exit walk). Returns `(exit_price, pnl_per_unit, exit_reason, bars_held, filled)`.

### `run_backtest(start, end, capital, seed, ...)`
Orchestrator. Loads data, builds daily bias, calls `generate_signals`, walks signals chronologically applying sections 3–5, calls `execute_trade` for each, accumulates trades + stats.

---

## 10. Edge cases and gotchas (anyone re-implementing must handle)

- **Lookahead in consolidation building.** When walking H1 bar `bar_ts`, the consolidation must be `H1[index <= bar_ts]` — never include bars from later in the same calendar date that haven't formed yet. Easy bug to introduce when `range` is computed against a full day's data.
- **Sweep consumption.** A sweep that fires an engulfing within window is consumed. A sweep that does *not* find an engulfing within window is *also* consumed (don't keep retrying it forever on every subsequent M3 bar).
- **Partial-window M3.** When live, the engulfing window can be partial (only a few M3 bars formed since the sweep). If fewer than the expected M3-bar count exist, skip without consuming the sweep — the next iteration will retry with more data. This is a parity contract with backtests, which always have full windows.
- **`day_filled_trades` cap counts only filled trades.** A limit order whose TTL expires without filling does *not* increment the cap.
- **DD pause is 5-then-2:** `consecutive_losses == 5` arms `pause_counter = 2`, then the next two signals decrement and skip without firing. The 8th attempt (post-pause) is the next that can actually fire.
- **Equity-MA gate uses NAV trail, not pnl deltas.** If you implement it as `mean(last_20_pnls)`, current equity will trivially exceed it and the gate becomes dead code.
- **SL is checked before TP in the same bar.** This is conservative — if both touched intra-bar, exit is SL. (Some real exchanges may fill differently; this strategy errs pessimistic.)

---

## 11. Stats reported per backtest

- `total_trades`, `wins`, `losses`, `win_rate`
- `total_pnl`, `gross_wins`, `gross_losses`, `profit_factor`
- `max_drawdown_pct` — computed per-year (because of yearly capital reset), then take the worst across years.
- For limit-order mode: `total_signals`, `filled_signals`, `missed_signals` (TTL expired), and an informational `would_have_won_count` (lookahead-only — never use for ranking).

---

That's the complete strategy. Anyone with these parameters, the three OHLC streams, and a deterministic random source can rebuild it from scratch.
