# Bias Filter (Variant C) — Analysis & Proof

**Date:** May 28, 2026
**Data:** 20 years (2006-2026), XAU/USD

---

## The Rule

```
Yesterday RED (strong body > 40% of range) → Today only SHORT
Yesterday GREEN (strong body > 40%) → Today only LONG
Yesterday WEAK (body < 40%) → NEUTRAL (both directions allowed)
```

---

## The Intuition

The filter says: **yesterday's direction tends to produce reliable traps today.**

- After a red day → sellers are in control → rallies are fake (short them)
- After a green day → buyers are in control → dips are fake (buy them)

---

## Raw Day-Direction Statistics (20 years, 5,374 trading days)

| Condition | Days | % |
|-----------|:----:|:-:|
| Strong bias days (body > 40%) | 2,943 | 55% |
| Neutral days (body < 40%) | 2,431 | 45% |

### After a Strong GREEN Day (1,610 days):
| Next Day | Count | % |
|----------|:-----:|:-:|
| GREEN (continuation) | 762 | 47.3% |
| RED (reversal) | 848 | **52.7%** |

### After a Strong RED Day (1,333 days):
| Next Day | Count | % |
|----------|:-----:|:-:|
| RED (continuation) | 612 | 45.9% |
| GREEN (reversal) | 721 | **54.1%** |

### Summary:
- **Continuation: 46.7%**
- **Reversal: 53.3%**

**Reversal is actually MORE common!** So why does the continuation-based filter work?

---

## Why the Filter Works Despite Reversal Being More Common

The filter doesn't predict daily direction. It predicts **which sweeps are traps.**

**On continuation days (46.7%):**
- Sweeps against the trend are HIGH QUALITY traps
- These trades win with large R:R (3:1 to 7:1)
- The fake-out is clear, the reversal is strong

**On reversal days (53.3%):**
- Often NO SWEEP PATTERN FORMS (price just trends the other way)
- No sweep = no trade = free pass (no loss)
- When a sweep DOES form on a reversal day = one small SL loss

**The math:**
- Win days: large wins (R:R 3:1+)
- No-trade days: $0 (no loss)
- Loss days: small losses (one SL hit)

The **asymmetry of outcomes** makes it profitable, not the probability of continuation.

---

## Backtest Proof (20 years, Micro Alpha-Sweep only)

| Mode | Trades | WR | PF | P&L | $/year |
|------|:------:|:--:|:--:|:---:|:------:|
| **Filter ON (current)** | **3,066** | **64.4%** | **3.01** | **$915,776** | **$45,789** |
| Filter OFF (neutral) | 4,453 | 55.2% | 1.80 | $567,688 | $28,384 |
| **Filter REVERSED** | **3,892** | **49.7%** | **1.39** | **$150,746** | **$7,537** |

### Year-by-Year (Filter ON wins every year except 2018 by $149):

| Year | Filter ON | Filter OFF | ON wins by |
|------|:---------:|:----------:|:----------:|
| 2008 | $53,005 | $28,142 | +$24,863 |
| 2011 | $86,222 | $52,310 | +$33,912 |
| 2020 | $60,762 | $29,632 | +$31,131 |
| 2024 | $124,728 | $86,628 | +$38,099 |
| 2025 | $112,875 | $37,171 | +$75,704 |

---

## What Happens on Days Like May 28, 2026

**Situation:**
- May 27 (yesterday): Strong red candle ($4,540 → $4,450)
- May 28 (today): Bias = BEARISH (only shorts allowed)
- Price crashed to $4,370 then recovered to $4,508
- A bullish sweep formed (dip below range, snap back up)
- Filter BLOCKED the long signal (bias mismatch)
- Missed $130 recovery

**Was the filter wrong today?** YES — on this one day.

**Is it wrong overall?** NO — across 20 years:
- Filter ON: $915K total
- Filter OFF: $567K total
- The filter earned $348K MORE by avoiding bad signals on thousands of other days

**The tradeoff:**
- Sacrifice: occasional big winners like today (~1-2 per month)
- Gain: avoid many small losses on trend-continuation days (~3-4 per month)
- Net: +$348K over 20 years

---

## The Reversed Filter (Mean-Reversion Bias)

"Yesterday red → today go LONG (expect reversal)"

**Result: CATASTROPHIC**
- PF: 1.39 (barely profitable)
- P&L: $150K (vs $915K with normal filter)
- Win Rate: 49.7% (below coin flip)

Why it fails: After a red day, bullish sweeps (dips below range) are often **real breakdowns** continuing the trend — not traps. Buying them = buying falling knives.

---

## Key Insight

> The filter works because of **outcome asymmetry**, not prediction accuracy.
> 
> - It doesn't need tomorrow to continue (it only does 47% of the time)
> - It needs the TRAPS on continuation days to be larger than losses on reversal days
> - With PF 3.01: every $1 lost makes $3 back
> - That 3:1 payoff ratio overcomes the 47% continuation probability

---

## Decision: Keep Variant C

The data is unambiguous:
- +$348K vs no filter over 20 years
- +$765K vs reversed filter
- 0 losing years with filter ON
- 64.4% win rate (vs 55.2% without)
- PF 3.01 (vs 1.80 without)

**Do not change the filter. Accept the occasional missed day. The math is overwhelmingly in favor of keeping it.**
