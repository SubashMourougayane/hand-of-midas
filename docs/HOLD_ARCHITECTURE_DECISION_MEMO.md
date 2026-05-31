# Hold Architecture Results — Decision Memo (Post Validation)

Reference: Hold Architecture Research Results

## Executive Summary

This research produced the clearest result so far.

The bottleneck was correctly identified:

```text
Not signal quality.
Not entry quality.

Exit architecture.
```

The previous hypothesis:

```text
Modern markets still mean-revert.
They simply require more time.
```

is now strongly supported by production-path testing.

---

## What Changed

Before:

```text
Signal
→ Enter
→ Hold 80 bars
→ Forced Exit
```

Now:

```text
Signal
→ Enter
→ Adaptive Hold
→ TP Capture
```

The strategy appears directionally correct more often than previously realized.

---

## Primary Findings

### 1. Winners + Break-Even at Expiry Wins Micro

Variant:

```text
At 80 bars:
If profitable:
    move SL → entry + 0.30
    continue

If losing:
    exit
```

Results:

| Metric | Current | Winners + BE |
|--------|---------|--------------|
| PF | 4.49 | 5.45 |
| P&L | $676K | $862K |
| DD | -23.5% | -21.5% |
| Recent PF | 3.46 | 4.59 |

Interpretation:

The previous BE logic was too early.

BE at expiry behaves differently:

```text
Let winners prove themselves first.
Then protect.
```

This preserves trend continuation.

---

### 2. Session-Aware Hold Is The Lowest-Risk Improvement

Variant:

```python
if session == "asia":
    max_bars = 240

elif session == "london":
    max_bars = 120

else:
    max_bars = 80
```

Results:

| Metric | Current | Session |
|--------|---------|---------|
| PF | 4.51 | 4.90 |
| WR | 79.8 | 81.1 |
| P&L | $685K | $826K |
| DD | -23.5 | -21.9 |

Interpretation:

This is elegant.

Asia receives enough time.

Overlap remains fast.

No complicated trade management.

---

### 3. Portfolio Results Are More Important Than Strategy Results

Portfolio results:

| Variant | PF | P&L | DD |
|---------|-----|------|-----|
| Macro only | 7.21 | $347K | -12.2% |
| Macro + Current | 4.59 | $844K | -26.2% |
| Macro + Winners | 4.90 | $1.018M | -21.2% |
| Macro + Session | 4.98 | $989K | -18.1% |

Interpretation:

This completely changes optimization priorities.

The target is now:

```text
Portfolio PF
```

not:

```text
Micro PF
```

---

## Decision Framework

### Immediate Deploy Candidate

**Session-Aware Hold**

Reason:

* +21% P&L
* Lower DD
* Controlled overnight exposure
* Minimal code change

Confidence: **HIGH**

---

### Paper Trade Candidate

**Winners + BE**

Reason:

* Best Micro PF
* Strong recent improvement

Risk:

* Overnight exposure ≈ 29%

Confidence: **MEDIUM**

---

### Portfolio Candidate

**Macro + Session-Aware**

Reason:

* Best balance

Metrics:

* PF 4.98
* DD -18.1%
* Overnight 16%

Confidence: **VERY HIGH**

---

## Remaining Research (Only 4 Left)

### Research 1

Can Winners + BE become Session + BE?

Test:

```text
Asia → 240 + BE at expiry
London → 120 + BE at expiry
Else → 80
```

---

### Research 2

Capital Lock Study

Measure:

* Signals skipped due to position open
* Return per hour held
* Exposure % of total time

---

### Research 3

Recent Only

Run 2025-2026 with:

* Current
* Session
* Winners

---

### Research 4

Live Replay

Replay:

* Exact production fills
* Exact VPS execution

Measure:

* Slippage vs backtest
* Latency impact
* Overnight gap exposure

---

## Final Recommendation

If deploying next week:

Deploy:

```text
Macro
+
Micro Session-Aware
```

Do not deploy winners-only yet.

Reason:

The incremental return is not large enough to justify doubling overnight exposure.

---

## Final Conclusion

This is no longer a signal-generation project.

This is now an **execution and portfolio-construction** project.

Your edge survived.

Your exit logic evolved.

Your next gains will likely come from:

* portfolio interaction
* execution timing
* capital allocation

—not from finding new entries.
