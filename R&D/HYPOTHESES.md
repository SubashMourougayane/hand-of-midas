# Hypotheses Log

> Every test that runs in this lab gets a hypothesis entry written and committed BEFORE the test runs. Once written, the hypothesis content is never edited. Results are appended below.

---

## Format template

```
## H-NNN — Short title (Phase X)

**Date written:** YYYY-MM-DD HH:MM UTC
**Git commit:** <sha or "uncommitted">
**SHA256 of this hypothesis block:** <hash>

### Hypothesis
One sentence stating what we believe is true.

### Prediction
Specific numerical prediction. What outcomes would be consistent with the hypothesis.

### Metric
PF / WR / total P&L / DD / signal count / etc. — the single number that decides this.

### Pass threshold
The exact numerical threshold for "pass". No vague language.

### Fail threshold
What number means "this hypothesis is wrong". May overlap with pass.

### Test plan
1. ...
2. ...

---

### RESULT (filled in AFTER test runs)

**Date run:** YYYY-MM-DD HH:MM UTC
**Outcome:** PASS / FAIL / INCONCLUSIVE
**Number observed:** <value>
**Reasoning:** Why this outcome means pass or fail.

**Did this match the prediction? Yes / No.** Honest answer, no rationalization.
```

---

## Hypotheses

(empty until Phase 0 starts)
