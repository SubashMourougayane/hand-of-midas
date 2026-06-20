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

(Future entries get added below as decisions are made.)
