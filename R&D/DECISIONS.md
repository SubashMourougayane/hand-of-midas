# Decisions Log

> Every "I chose X over Y because Z" gets recorded here. Future-us can audit why we made each call. No silent drift.

---

## Format template

```
## D-NNN — Short title (Phase X)

**Date:** YYYY-MM-DD HH:MM UTC
**Decision:** What was chosen.
**Alternatives considered:** A, B, C.
**Reasoning:** Why X over A/B/C.
**Reversibility:** Can this be undone? At what cost?
**Sign-off:** User / Assistant / Both.
```

---

## Decisions

### D-001 — Lab discipline contract locked

**Date:** 2026-06-20 (evening)
**Decision:** Adopt the 6-safeguard contract in `CONTRACT_AND_SAFEGUARDS.md` as the rule book for all R&D work.
**Alternatives considered:**
- Just trust the assistant (rejected — track record of bugs and inflated numbers)
- Outsource entirely to Codex (rejected — same blind spot risk)
- Walk away from algorithmic trading (deferred — user wants to genuinely test if edge exists)
**Reasoning:** The user identified the right concern: the assistant has a track record of bugs. A contract designed assuming the assistant will fail is more honest than promises. Six safeguards specifically counter the failure modes observed in this project's history.
**Reversibility:** User can override any safeguard in writing here. Assistant cannot.
**Sign-off:** User (yes), Assistant (yes).

---

### D-002 — Data split 4/1/1.5 years (LOCKED)

**Date:** 2026-06-20 (evening)
**Decision:** Development = 2019-09-26 → 2023-12-31 (~4.25 years). Validation = 2024 (~1 year). Holdout = 2025-01-01 → 2026-06-19 (~1.5 years).
**Alternatives considered:**
- 5/1/1 split — rejected because it's too easy to cherry-pick a 5-year window
- Random K-fold — rejected because it leaks future-relative-to-past info across folds
- Walk-forward only — deferred to Phase 2's internal structure if useful
**Reasoning:** Dev set is large enough to find structure. Validation gives a single full unseen year to disprove development findings. Holdout is the strictest test — strategy must work on the most recent data with zero contamination.
**Reversibility:** Hard to reverse — once data has been seen, it's seen. The split is hash-locked in `data_split.py`.
**Sign-off:** User (yes), Assistant (yes).

---

### D-003 — No imports from production code

**Date:** 2026-06-20 (evening)
**Decision:** R&D code may NOT import from `backend/`, `backend-micro/`, `backend-oil-micro/`, `backend-oil/`, `backend-general/`. R&D may read CSV files in `data/raw/` only via `R&D/data_split.py`.
**Alternatives considered:**
- Allow imports of "neutral" utilities like `backend/db.py` — rejected because it creates a coupling surface
- Allow imports of `backend/execution/fill_model.py` — rejected because the production fill model has had documented lookahead bugs (BT-LOOKAHEAD); if the fill model is wrong, importing it taints R&D
**Reasoning:** Isolation is the cheapest insurance against accidental contamination. Lab is small enough to re-derive the few utilities it needs.
**Reversibility:** Easy. Just import.
**Sign-off:** User (yes), Assistant (yes).

### D-004 — Override of Safeguard "user marks, not assistant" for Phase 0

**Date:** 2026-06-21 (morning IST)
**Decision:** The user has chosen Option B. The R&D contract clause "the
assistant MUST NOT suggest 'this looks like a setup' while the user is
marking" (CONTRACT_AND_SAFEGUARDS.md, Safeguard 4 anti-contamination
section, and the Phase 0 hypothesis H-001 anti-contamination commitments)
is explicitly OVERRIDDEN for this specific phase, in writing.

The user has authorized the assistant to:
- Render M3 candle screenshots from the development data
- Visually inspect those screenshots (or use a vision-capable tool / MCP
  technical-chart-analyst skill if available)
- Identify candidate institutional-stop-run-plus-reversal setups
- Pre-fill `manual_marks.jsonl` with those candidate marks
- Present the prefilled marks + screenshots to the user for review

The user retains the right to delete, modify, or reject any prefilled mark.

**Alternatives considered:**
- Option A — Build the web app, user marks with their own eye. Rejected
  because the user found the matplotlib UI workflow too friction-heavy
  and decided AI-prefilling-then-review was acceptable risk.
- Option C — Skip Phase 0 entirely, source parameters from external
  references. Rejected because the user wants this strategy to be
  grounded in the actual JM data's structure, not generic textbook values.

**Reasoning given by user:** time pressure, prefers a review workflow
over manual marking from scratch.

**Risks the user is explicitly accepting** (assistant flagged these
before the override; user proceeded anyway):

1. **Vision model bias toward trained patterns.** Any AI looking at
   charts has been trained on retail chart-analysis content (ICT
   diagrams, TV ideas, YouTube screenshots) which is itself
   post-hoc-rationalized. It will "find" patterns where it has been
   taught to find patterns, not necessarily where edge exists in this
   data.

2. **Contamination from prior broken strategy.** The assistant has
   already seen the production strategy's parameters (`min_range: 0.33`,
   `sweep_threshold: 0.13`, `engulfing_window_hours: 0.75`, etc.).
   It cannot un-see those. Any marks the assistant produces will be
   correlated with those parameters even if not consciously matching
   them. This means Phase 1 detection rules tuned against these marks
   may simply re-discover the broken strategy with cosmetic differences.

3. **Phase 0 no longer functions as a discipline gate.** The whole
   point of human-only marking was that the assistant's blind spots
   could not infect Phase 1. Once the assistant marks, Phase 1 is
   downstream of the assistant's pattern recognition, not the user's
   eye. The "honest re-derivation" framing is weakened.

4. **"Review" pressure.** Past sessions have shown the user accepts
   most AI outputs that look plausible. Reviewing 20 prefilled marks is
   psychologically harder than rejecting them. There is real risk that
   marks that "look fine on quick review" become Phase 1's training
   target without being genuinely user-validated.

5. **Project odds (assistant's pre-flagged estimate of finding real
   edge) drop materially.** Pre-override estimate was 20-30%. With this
   override the estimate is closer to 10-15%. The discipline gate was
   load-bearing.

**Mitigations the user MAY adopt to partially offset the risk:**
- Reject any mark on first review; only accept on second pass after
  examining its specific candle context.
- Independently mark 5 setups before reading the assistant's marks,
  then compare. If the lists overlap < 30%, that's a strong signal
  the assistant's marks are biased and need to be discarded.
- Run the random-baseline safeguard test (Safeguard 5) after Phase 1
  with extra suspicion since the input pipeline is contaminated.

**Reversibility:** The marks file `manual_marks.jsonl` can be wiped
and a clean Option A run can replace this. But Phase 1 work built on
top of contaminated marks is harder to roll back.

**Sign-off:**
- User: explicit verbal "option B" given 2026-06-21 morning, with
  acknowledgement of the 5 risks above.
- Assistant: PROCEEDING UNDER PROTEST. Recording disagreement here so
  the audit trail shows the override was granted, not earned by the
  assistant proving it was safe.

**If Phase 0 ends with results that look too good (high time-clustering,
high consolidation rate, high H1 reversal visibility), the assistant's
default reaction must be SUSPICION, not celebration.** The most likely
explanation will be that the AI marker found a pattern it was trained
to find, not a pattern present in the data.

### D-005 — Phase 0 calibration doc approved, marking authorized

**Date:** 2026-06-21 IST
**Decision:** User approved `phase_0_observations/what_real_looks_like_assistant_view.md` as written. Assistant authorized to proceed to the marking pass under the 5-feature criteria + confidence ≥ 4 threshold defined in that doc.
**Alternatives considered:**
- Approve with edits (rejected — user signed "go ahead" without edit list)
- Reject + restart calibration (rejected — discipline gate held; no reason to restart)
- Reject + abandon B1, user marks themselves (rejected — D-004 stands)
**Reasoning:** User has read the calibration doc including the four self-flagged contamination risks and chose to proceed.
**Reversibility:** Marks file `manual_marks.jsonl` is append-only but can be wiped at any time. Phase 0 result can be discarded without code rollback.
**Sign-off:** User: "go ahead" 2026-06-21. Assistant: proceeding under D-004 + D-005.

(Future entries get added below as decisions are made.)
