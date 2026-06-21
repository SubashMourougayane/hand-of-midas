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

---

## H-001 — Brent stop-runs are visually identifiable on H1 (Phase 0)

**Date written:** 2026-06-20 10:37 UTC (16:07 IST)
**Git commit:** uncommitted (will be hashed after this entry is locked into HYPOTHESES.md)
**SHA256 of this hypothesis block:** `704366bfc96ce1aeb55ac59ff0f5ef0827fedcbf366672cc6ec2a1d4bbc354d4` (computed 2026-06-20 10:42 UTC; if you re-hash the H-001 block from the next `## H-001` line through the matching `---`, you should get this exact value. If you don't, the hypothesis was edited.)

### Hypothesis

When a human (the user) manually scrolls through Brent (BCO_USD) H1 charts in the development window (2019-09-26 → 2023-12-31), they can identify a class of price patterns that look like "institutional stop-runs followed by reversal" — and these patterns share visible common structural features (e.g. clustering at certain hours, prior-day range characteristics, post-sweep reversal velocity) that DO NOT match what would be expected from random noise.

### Prediction

Specific things we predict the manual marks will show:

1. **The user can mark at least 20 setups in the development window without strain.** If the user can't find 20 in 4+ years of H1 data, the pattern doesn't exist often enough to trade.

2. **The marks will cluster at specific hours of day (UTC).** Prediction: ≥ 60% of marks fall in the windows 12:00–16:00 UTC (London/NY overlap) and 19:00–22:00 UTC (NY close volatility) combined. If marks are uniformly distributed across all 24 hours, the pattern has no temporal structure — strong evidence it's not real.

3. **The marks will show pre-setup consolidation visible to the eye.** Prediction: ≥ 70% of marks have a prior 4-12 hour range that the user describes as "tight relative to recent ATR" without being told to look for that. If marks fire on trending bars with no prior consolidation, our concept is wrong.

4. **Reversal direction will be visible on the H1 sweep bar itself.** Prediction: ≥ 80% of marks have an H1 candle whose close is on the opposite side of its midpoint from where the wick poked. If the reversal isn't visible at H1 close, the live system can never detect it in time.

### Metric

Three numbers, all measurable without code:

- `marks_found` — integer, count of setups the user marked. Target: 20.
- `time_clustering_pct` — percentage of marks falling in 12:00–16:00 OR 19:00–22:00 UTC. Target: ≥ 60%.
- `prior_consolidation_pct` — percentage of marks where user reports a tight prior range. Target: ≥ 70%.
- `h1_reversal_visible_pct` — percentage of marks where the H1 sweep bar's close is on the reversal side. Target: ≥ 80%.

### Pass threshold

Phase 0 passes if ALL FOUR are true:
- marks_found ≥ 20
- time_clustering_pct ≥ 60%
- prior_consolidation_pct ≥ 70%
- h1_reversal_visible_pct ≥ 80%

### Fail threshold

Phase 0 fails (and the project pauses for re-evaluation) if ANY of:
- marks_found < 10 (the pattern is too rare to trade)
- time_clustering_pct < 40% (no temporal structure)
- prior_consolidation_pct < 50% (no consolidation precondition)
- h1_reversal_visible_pct < 60% (the reversal isn't visible on H1 — live can't catch it)

If results land between fail and pass thresholds, that's INCONCLUSIVE — the user decides whether to proceed cautiously or stop.

### Test plan

1. The user manually pulls 5-10 examples of "institutional stop-runs" from public sources (TradingView ideas, FX education content, ICT-style annotations) — DEFINING what we're looking for IN THE USER'S OWN WORDS, not from the prior strategy spec. Output: `phase_0_observations/external_examples.md`.

2. The user opens a simple Brent H1 chart viewer (script written below in Step 2) and scrolls through the development window (2019-09-26 → 2023-12-31) sequentially.

3. For each pattern that LOOKS like the external examples, the user clicks/types to mark it with: timestamp, direction (long/short), 1-5 confidence score, free-text "what makes this look real".

4. Stop when 20 setups marked OR after 90 minutes of search, whichever first.

5. Aggregate the marks. Compute the 4 metrics above. Compare to thresholds.

6. Write `phase_0_observations/what_real_looks_like.md` based on the observed common structure across the 20 marks.

### Anti-contamination commitments (signed by both)

- The user MUST NOT consult the existing strategy parameters (`min_range: 0.33`, `sweep_threshold: 0.13`, etc.) during marking. The current parameters were tuned with the lookahead bug — they encode what the broken BT thinks is a setup, not what the eye sees.
- The user MUST NOT look at validation (2024) or holdout (2025-2026) data. The chart viewer will be hard-locked to development data only.
- The assistant MUST NOT suggest "this looks like a setup" while the user is marking. The user's eye is the ground truth in Phase 0; the assistant's pattern recognition is contaminated by knowledge of the previous broken strategy.
- The assistant MUST NOT reveal the existing strategy's hour ranges, ATR multipliers, or consolidation rules until AFTER marking is complete and `what_real_looks_like.md` is written.

---

### RESULT (filled in AFTER marking is complete)

**Date run:** (pending)
**Outcome:** (pending)
**Number observed:**
- marks_found: (pending)
- time_clustering_pct: (pending)
- prior_consolidation_pct: (pending)
- h1_reversal_visible_pct: (pending)

**Reasoning:** (filled in after observation)

**Did this match the prediction?** (filled in after observation)

