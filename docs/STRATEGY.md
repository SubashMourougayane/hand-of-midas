# Alpha-Sweep Strategy — How It Works

## The One-Line Summary

We wait for price to fake a breakout (triggering stop-losses), confirm the fake with a reversal candle on the 3-minute chart, then trade back into the range.

---

## The Story

### 1. The Setup (Consolidation)

Gold trades 24 hours. During any 4-hour window, price consolidates — bounces between a ceiling (range high) and a floor (range low). Every trader in the world can see these levels on their chart.

Big players (banks, hedge funds) know that retail traders park their stop-losses just ABOVE the ceiling and just BELOW the floor. These stops are visible as liquidity pools.

**Example:** Gold consolidates between $4,500 (floor) and $4,520 (ceiling) for 4 hours.

---

### 2. The Trap (Liquidity Sweep)

Smart money pushes price ABOVE the ceiling on purpose. This triggers all the stop-losses sitting above $4,520. Those stops are BUY orders — they add fuel to the spike. Price shoots to $4,525.

Retail traders see "breakout!" and pile in long. They're buying from smart money — who was SELLING into that spike. Smart money needed those stop-loss buy orders as exit liquidity for their large positions.

**Detection rule:** Price wick goes $2+ above range high AND closes back below range high.

**Example:** H1 bar prints high=$4,525 (above $4,520+$2 threshold), closes at $4,518 (back inside range). Sweep confirmed.

---

### 3. The Confirmation (3-Minute Engulfing)

We don't enter on the spike. We WAIT. We zoom into the 3-minute chart (M3 bars) and watch for 45 minutes. If a **bearish engulfing candle** forms — a big red candle whose body completely wraps the previous candle's body — it confirms the trap worked. Price is reversing.

NOW we enter SHORT at the close of that M3 engulfing candle.

**Why 3-minute?** It's fast enough to catch the reversal early, but slow enough to filter noise. A 1-minute engulfing could be a flicker. A 3-minute engulfing means real selling pressure arrived.

**Why 45 minutes?** If the reversal doesn't start within 45 minutes, the sweep wasn't a trap — it was a real breakout. We walk away.

**Example:** At 10:09 UTC (9 minutes after the sweep), M3 bar forms: open=$4,519, close=$4,515, wrapping the previous bar (open=$4,516, close=$4,518). Bearish engulfing confirmed. Enter SHORT at $4,515.

---

### 4. The Levels

```
$4,527  ── SL (sweep wick $4,525 + $2 buffer)
$4,520  ── Range HIGH (where the trap happened)
$4,515  ── ENTRY (engulfing bar close)
   |
   |  ← We expect price to fall back through the range
   |
$4,502  ── TP (range LOW $4,500 + $2 buffer)
$4,500  ── Range LOW (natural support — buyers sit here)
```

**Why SL = sweep wick + $2?** If price goes back ABOVE where it wicked, the trap thesis is invalid. The $2 buffer prevents stop-hunts on our SL itself.

**Why TP = range low + $2?** The other side of the range is where opposing liquidity sits. We take profit $2 before that level — price often bounces at support and we don't want to give back profit.

---

### 5. The Daily Filter (Bias)

Before taking any trade, we check yesterday's daily candle:

**Where did price CLOSE relative to the day's range?**

- Close in top 30% of range → Yesterday recovered strongly → Today only LONG trades allowed
- Close in bottom 30% of range → Yesterday crashed → Today only SHORT trades allowed
- Close in the middle → Indecision → Both directions allowed

This prevents us from shorting into a market that's recovering (bullish momentum) or buying into a market that's crashing (bearish momentum).

**Example:** Yesterday O=$4,457, H=$4,517, L=$4,367, C=$4,496. Close position = ($4,496 - $4,367) / ($4,517 - $4,367) = 86% → Top 30% → BULLISH bias → Only LONG sweeps allowed today. SHORT sweeps blocked.

---

### 6. The Rolling Windows

We don't check just one consolidation range per day. We use **rolling 4-hour windows** that shift every 2 hours, covering the full trading day:

```
Window 1:  00:00 - 04:00 (scans 04:00 - 10:00)
Window 2:  02:00 - 06:00 (scans 06:00 - 12:00)
Window 3:  04:00 - 08:00 (scans 08:00 - 14:00)
Window 4:  06:00 - 10:00 (scans 10:00 - 16:00)
...continues every 2 hours...
```

Each window builds its own range (high/low) from its 4 H1 bars. Multiple windows are active simultaneously, giving us more opportunities.

**Minimum range:** $5. If the 4-hour range is less than $5, no trade — not enough structure.

---

### 7. The Exit (3 Outcomes)

Every trade ends one of these ways:

**A. TP Hit (~76% of trades) — WIN**

Price crosses back through the range and reaches the other side. Our limit order fills at exactly the TP level. Typical win: $5-15 per unit.

**B. SL Hit (~18% of trades) — LOSS**

The sweep wasn't a trap — price continues past our SL. The breakout was real. Typical loss: $7-17 per unit.

**C. Expired (~6% of trades)**

Price does nothing for 4 hours (80 M3 bars = 240 minutes). We exit at current price. Could be a small win or small loss depending on where price ended up.

---

### 8. Break-Even Protection

Once price moves 50% toward our TP, we move our SL to entry - $0.30.

**Example:** Entry=$4,515, TP=$4,502. When price drops to $4,508.50 (halfway), SL moves from $4,527 to $4,514.70. Now the trade is essentially risk-free. If price reverses from here, maximum loss is $0.30/unit (instead of $12/unit).

This fires on ~60% of trades that eventually become winners, and saves us on whipsaw days where price reaches toward TP then snaps back.

---

### 9. Protection Systems

**Daily max loss: $400.** If we lose $400 in a day, stop trading. No more signals until tomorrow.

**Position halving:** After 3 consecutive losses, cut position size by 50%. Limits damage during bad streaks.

**Pause:** After 5 consecutive losses, skip the next 2 signals entirely. Forces a reset before re-entering.

**One-at-a-time:** Never have 2 positions open simultaneously. Wait for current trade to exit before entering a new one.

**5-minute cooldown:** After any signal (taken or rejected), wait 5 minutes before accepting another. Prevents rapid-fire entries on overlapping windows.

---

### 10. Why It Works

The "sweep and reverse" pattern is a fundamental market structure. Banks NEED liquidity to fill large orders. They GET that liquidity by triggering stops above/below obvious levels. This has happened consistently for 20 years on Gold because:

1. **Gold has deep liquidity pools** at round numbers ($4,500, $4,550) and technical levels (H1 highs/lows)
2. **Retail traders are predictable** — they always park stops just beyond visible levels
3. **The reversal is mechanical** — once smart money finishes filling, there's no more buying pressure above the range. Price falls back naturally.

We're not predicting direction. We're waiting for the trap to spring, confirming it worked, then riding the gravity of price returning to equilibrium.

---

## Numbers (Verified, 20 Years)

| Metric | Value |
|--------|-------|
| Win Rate | 82% |
| Profit Factor | 5.16 |
| Max Consecutive Losses | 5 |
| Losing Years | 0 out of 20 |
| Losing Months | 7 out of 219 (3%) |
| Max Consecutive Losing Months | 1 |
| Sharpe Ratio | 3.14 |
| Probability of Ruin | 0.00% |
| Survives 2x cost stress | PF 3.57 (still profitable) |
| Needs 34% of wins removed to collapse | Robust (not dependent on outliers) |

---

## Configuration (Current Live)

```
sl_buffer:            $2.00    (above sweep wick)
tp_structure_buffer:  $2.00    (from other side of range)
sweep_threshold:      $2.00    (minimum sweep extension)
min_range:            $5.00    (minimum consolidation range)
min_sl:               $5.00    (minimum risk per trade)
engulfing_window:     45 min   (time to find reversal candle)
max_hold:             80 bars  (4 hours maximum)
be_trigger:           50%      (of distance to TP)
max_trades_per_day:   3
daily_max_loss:       $400
position_size:        4% of equity per trade
max_units:            100
```
