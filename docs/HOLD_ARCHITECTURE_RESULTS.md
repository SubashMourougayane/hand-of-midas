# Hold Architecture Research — Full Results

**Date:** 2026-05-30  
**Code Path:** Production `micro_alpha_sweep.generate_signals()` + custom `execute_trade_winners_hold()` (same fill logic, configurable exit)  
**Bias:** V1 body% 40% (currently deployed)  
**Period:** 2006-2026  
**Capital:** $5,000/yr, 4% risk, max 100 units  

---

## Priority 1: Winners-Only Hold Variants

**Question:** What happens if we let profitable trades continue past 80 bars?

| Variant | Trades | WR | PF | P&L | DD | Avg Hold | O/N% |
|---------|--------|-----|-----|------|-----|----------|------|
| **A: Current (exit all at 80)** | 2,251 | 79.4% | 4.49 | $676,764 | -23.5% | 49 bars | 0% |
| **B: Winners hold (no limit)** | 2,165 | 77.8% | 5.06 | **$888,254** | -24.8% | 85 bars | 28.8% |
| **C: Winners + BE at 80** | 2,204 | **80.0%** | **5.45** | $862,755 | **-21.5%** | 74 bars | 28.9% |
| **D: Winners + Trailing 50%** | 2,230 | 79.8% | 4.78 | $726,074 | -21.6% | 61 bars | 28.7% |

### Recent 2024-2026:

| Variant | Trades | WR | PF | P&L |
|---------|--------|-----|-----|------|
| A: Current | 536 | 72.9% | 3.46 | $229,381 |
| **B: Winners hold** | 502 | 71.5% | **4.41** | **$342,890** |
| **C: Winners + BE** | 514 | **73.0%** | **4.59** | **$338,559** |
| D: Winners + Trail | 528 | 72.9% | 3.70 | $249,770 |

### Analysis:

**Variant C (Winners + BE at 80 bars) is the winner:**
- Highest PF (5.45) and best DD (-21.5%)
- 80% WR — highest of all variants
- $862K P&L (+$186K over current = +27%)
- Recent: PF 4.59 vs 3.46 current (+33%)
- Logic: at 80 bars, if profitable → move SL to entry+$0.30 and let it run to TP. If losing → exit immediately.

**Variant B (pure winners hold) produces most money ($888K) but worse DD.**

**Variant D (trailing) is weakest — trailing locks profit too early, preventing TP hits.**

**Overnight exposure: ~29% for all extended variants.** This is the cost — 1 in 3 trades will hold overnight.

---

## Priority 2: Session-Aware Hold

**Question:** Should Asia entries get more time than Overlap entries?

| Variant | Trades | WR | PF | P&L | DD | Avg Hold |
|---------|--------|-----|-----|------|-----|----------|
| Current (all=80) | 2,249 | 79.8% | 4.51 | $685,330 | -23.5% | 50 |
| **Session-aware** (Asia=240, London=120, Overlap=80) | **2,178** | **81.1%** | **4.90** | **$826,812** | **-21.9%** | 61 |

### Analysis:

**Session-aware improves everything:**
- PF: 4.51 → 4.90 (+0.39)
- WR: 79.8% → 81.1% (+1.3%)
- P&L: +$141K (+21%)
- DD: -23.5% → -21.9% (better)
- Avg hold only increases by 11 bars (33 min)

This is the **safest improvement** — gives Asia entries time to complete (they're 90% correct per autopsy), keeps Overlap entries fast (they don't need extra time).

---

## Priority 8: Portfolio Interaction (Macro + Micro)

**Question:** Does improving Micro hurt the combined portfolio?

| Variant | Trades | WR | PF | P&L | DD | O/N% |
|---------|--------|-----|-----|------|-----|------|
| Macro only | 1,001 | 82.9% | 7.21 | $347,080 | -12.2% | 0% |
| Micro only (current) | 2,249 | 79.8% | 4.51 | $685,330 | -23.5% | 0% |
| **Macro + Micro (current)** | **2,638** | **80.0%** | **4.59** | **$843,657** | -26.2% | 0% |
| **Macro + Micro (winners-only)** | **2,531** | 78.0% | 4.90 | **$1,017,555** | **-21.2%** | 29.1% |
| **Macro + Micro (session-aware)** | **2,544** | **81.6%** | **4.98** | **$988,976** | **-18.1%** | 16.3% |

### Signal Overlap:

**38% of days have BOTH Macro and Micro signals.** They compete for the same position slot on those days (one-at-a-time rule applies globally).

### Analysis:

**Combined session-aware is the best portfolio configuration:**
- PF 4.98 (highest)
- DD -18.1% (lowest of all combined variants)
- Overnight 16.3% (vs 29% for winners-only — more controlled)
- P&L $988K (only -$29K less than winners-only, but with much better DD)

**Winners-only combined produces most money ($1.017M) but 29% overnight exposure and -21% DD.**

**Macro alone has best PF (7.21) but only $347K — too few trades.**

---

## The Decision Matrix

| Criterion | Current | Winners+BE | Session-Aware | Combined Session |
|-----------|---------|------------|---------------|------------------|
| Full P&L | $676K | $862K | $826K | $988K |
| Recent PF | 3.46 | 4.59 | ~4.5 | ~4.9 |
| Max DD | -23.5% | -21.5% | -21.9% | -18.1% |
| Overnight % | 0% | 29% | ~15% | 16.3% |
| Complexity | Simple | Medium | Medium | Medium |
| Trades/Year | 112 | 110 | 109 | 127 |

---

## Recommendations

### Deploy Now (low risk):
1. **Session-aware hold** — Asia=240, London=120, Overlap/NY=80
   - +21% P&L, better DD, only 15% overnight
   - Zero strategy change, just config per session

### Deploy After Paper (medium risk):
2. **Winners + BE at expiry** (Variant C)
   - At 80 bars: if profitable → move SL to entry+$0.30, keep holding
   - +27% P&L, best PF, 29% overnight
   - Requires code change to fill model / position monitor

### Optimal Combined:
3. **Macro + Micro session-aware** running together
   - $988K combined, PF 4.98, DD -18.1%
   - Both already running on VPS (separate DD states)
   - Just change Micro's max_bars to session-aware

---

## Connection to Hypothesis

> "Modern markets still mean-revert — they simply require more time."

**Confirmed with production numbers:**
- Session-aware (+$141K): Asia entries that got 12h instead of 4h reach TP
- Winners-only (+$186K): profitable trades that continue eventually hit TP
- Combined (+$312K over Micro alone): giving trades time = money

The edge is intact. The execution just needed patience.
