# Addendum — Priority 8: Portfolio Interaction Test

## Why This Exists

The latest research introduced a new risk:

Improving Micro by extending hold duration may reduce total portfolio returns by competing with Macro.

This changes the problem from:

```text
Single strategy optimization
```

to:

```text
Portfolio optimization
```

---

## Research Question

Does improving Micro reduce combined portfolio performance?

---

## Test Matrix

| Variant |
|---------|
| Macro only |
| Micro only |
| Macro + Current Micro |
| Macro + Winners-only |
| Macro + Session-aware |
| Macro + ATR Hold |

---

## Metrics

Track:

* Combined PF
* Combined WR
* Combined P&L
* Combined DD
* Capital utilization
* Trade overlap %
* Opportunity cost
* Avg exposure duration

---

## Overlap Analysis

Measure:

```text
Trade overlap %
```

Questions:

* Are both systems entering same direction?
* Are positions overlapping?
* Is Macro blocked by Micro?
* Is Micro stealing Macro trades?

---

## Capital Lock Audit

Measure:

```text
capital_locked_time
```

Questions:

* % time unavailable
* signals skipped
* return per deployed hour

---

## Decision Rules

If:

```text
Improved Micro
+
Lower combined P&L
```

→ Reject improvement.

If:

```text
Improved Micro
+
Higher combined PF
+
Lower DD
```

→ Accept.

---

## Pass Criteria

Combined:

* PF > Current
* DD ≤ Current
* P&L > Current
* Trade overlap < 20%

---

## Final Question

Should:

```text
Macro = overnight reversal engine
Micro = intraday reversal engine
```

remain independent,

or

should they merge into a single execution framework?
