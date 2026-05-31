# Alpha-Sweep — Post Expiry-Autopsy Research Plan V2

## Executive Summary

The Expired Trade Autopsy fundamentally changes the direction of research.

Previous assumption:

```text
Entries need improvement.
```

New evidence:

```text
Entries are mostly correct.
Exits are terminating profitable trades too early.
```

The current bottleneck is no longer entry quality.

The bottleneck is:

* Hold architecture
* Session-aware exit design
* Capital efficiency
* Exit timing

---

## Current System Problem

Current:

```text
max_bars = 80
```

Observed:

* 35% of trades expire
* 70% later reach TP
* 80% are profitable when expired
* Median extra time required = ~10 hours

Interpretation:

```text
Signal → Correct
Exit → Incorrect
```

The strategy appears directionally correct but operationally impatient.

---

## Priority 1 — Winners-Only Hold Extension

### Hypothesis

If profitable trades continue after expiry, allow winners to continue.

Current:

```python
if bars_held >= 80:
    exit()
```

Test:

```python
if bars_held >= 80:
    if pnl > 0:
        continue
    else:
        exit()
```

### Variants

| Variant | Rule |
|---------|------|
| Current | Exit all at 80 bars |
| A | Hold winners indefinitely |
| B | Hold winners until BE hit |
| C | Hold winners until TP hit |
| D | Hold winners with trailing SL |

### Metrics

* PF
* WR
* P&L
* DD
* Overnight exposure
* Avg hold duration
* Capital utilization

### Success Criteria

* PF > 5
* DD < 30%
* Overnight < 20%
* Recent PF > 4

---

## Priority 2 — Session-Aware Hold

### Hypothesis

Sessions revert at different speeds.

Current:

```text
All sessions = 80 bars
```

Test:

```python
if entry_session == "asia":
    max_bars = 240
elif entry_session == "london":
    max_bars = 120
else:
    max_bars = 80
```

### Variants

| Session | Hold (bars) | Hold (hours) |
|---------|-------------|--------------|
| Asia | 120 | 6h |
| Asia | 240 | 12h |
| London | 120 | 6h |
| Overlap | 80 | 4h |
| NY | 80 | 4h |

### Metrics

* PF per session
* Avg hold per session
* Expired-later-TP % per session
* Capital lock time

### Success Criteria

* Capture >50% missed TP
* DD stable or improving
* Overnight exposure controlled

---

## Priority 3 — ATR-Based Hold Logic

### Hypothesis

Fixed time is wrong. Volatility should determine exit.

### Variants

**ATR Exit:**
```text
Exit when: price moves < 0.25 × ATR in last 20 bars (momentum exhaustion)
```

**Momentum Exit:**
```text
Exit when: 3 consecutive opposite-direction candles
```

**Session Exit:**
```text
Exit at session boundary (if entered in Asia, exit at London open)
```

### Metrics

* Avg hold
* PF
* Profit captured vs current
* Time-to-TP distribution

---

## Priority 4 — Expiry Distance Study

### Question

Were expired trades close to TP?

### Data (from autopsy)

| Distance from TP | Count | % of expired |
|------------------|-------|--------------|
| < $2 | 50 | 4% |
| $2–$5 | 223 | 20% |
| $5–$10 | ~227 | ~20% |
| > $10 | ~636 | ~56% |

Mean: $12.51, Median: $8.18

### Goal

Determine whether:
* Dynamic TP reduction (lower TP after N bars) captures more
* Partial exits (50% at halfway, 50% at TP) smooth P&L
* Session-close exit (exit at end of session instead of timer)

---

## Priority 5 — Capital Efficiency Audit

### Question

Longer hold may reduce trade frequency (one-at-a-time blocks new signals).

### Measure

* Concurrent positions (always 0 or 1 — one-at-a-time)
* Opportunity cost: signals skipped because position was open
* Capital utilization: % of time capital is deployed
* Return per hour held

### Compare

| Variant | Trades | Avg Hold | Capital Utilization | P&L/Hour |
|---------|--------|----------|---------------------|----------|
| 80 bars | ? | ? | ? | ? |
| 120 bars | ? | ? | ? | ? |
| 200 bars | ? | ? | ? | ? |
| Unlimited | ? | ? | ? | ? |

---

## Priority 6 — Recent Market Verification

Run 2024-2026 ONLY with each variant.

| Variant | 2024 PF | 2025 PF | 2026 PF | Hold Duration | Expiry % | Overnight % |
|---------|---------|---------|---------|---------------|----------|-------------|
| Current (80) | ? | ? | ? | ? | ? | ? |
| Winners-only | ? | ? | ? | ? | ? | ? |
| Session-aware | ? | ? | ? | ? | ? | ? |

Question: Is slower mean reversion accelerating year over year?

---

## Priority 7 — Final Nuclear Validation

Apply simultaneously:

* Winners-only hold (or best variant from P1)
* Hour filter (remove 04/19/20)
* Entry delay +15 min
* 2× costs (+$1/unit slippage)
* 2025–2026 only

### Pass Criteria

* PF > 2
* DD < 30%
* Positive expectancy
* Positive P&L

---

## Decision Tree

```
If winners-only dominates:
  → Deploy winners-only hold logic

Else if session-aware dominates:
  → Deploy session-specific max_bars

Else if ATR-based dominates:
  → Replace fixed hold entirely

Else:
  → Keep 120 bars (safe incremental improvement)
```

---

## Connection to Macro

The expired trade data shows Asia entries need 12+ hours. This is EXACTLY what Gold Macro captures naturally:
- Fixed 8-hour Asia range (00-08 UTC)
- Scan window 08-20 UTC (12 hours to complete)
- Result: PF 7.21, 83% WR

The question becomes: **Should Micro evolve toward Macro's hold logic for Asia entries, or should both systems run independently on the same account?**

Current architecture (both running):
- Macro catches slow overnight reversals (50 trades/year, PF 7.21)
- Micro catches fast intraday reversals (112 trades/year, PF 4.48)
- Combined: ~160 trades/year, ~$1M/20yr

The risk of making Micro hold longer: it starts competing with Macro for the same trades. The two systems would overlap.

---

## Final Thought

This is no longer a signal discovery problem.

It is becoming an **execution architecture** problem.

The strongest evidence now suggests:

> Modern markets still mean-revert.
> They simply require more time to complete the move.

The strategy is directionally correct 70-80% of the time. The question is purely: how long do we give it?
