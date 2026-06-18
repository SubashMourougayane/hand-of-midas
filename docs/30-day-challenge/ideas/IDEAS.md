# Ideas Parking Lot — 30-Day Challenge

> P2 thoughts. Park here. **DO NOT ACT during freeze (Phase 0–2).**
> Re-read at Phase 2 (Decide, Day 15–21) for ranking.

---

## Format

```markdown
### YYYY-MM-DD — <one-line idea title>
- **Phase noticed:** Phase X, Day N
- **Source:** postmortem / observation / chat / external read
- **Cost to investigate:** <1hr / 1d / 1wk>
- **Why it matters:** <1-2 sentences>
- **Why I'm not acting now:** <freeze rule / not enough data / unclear edge>
```

---

## Inherited from pre-challenge (carried over)

### 2026-06-17 — F30: SMC PDH/PDL bias replacement
- **Phase noticed:** Pre-challenge
- **Source:** F28 research raised "what's a smarter bias signal?" — SMC liquidity-sweep concept
- **Cost to investigate:** ~5hr BT sweep + research write-up
- **Why it matters:** F28 disable was net-positive. SMC bias may beat both V1+V2 and neutral.
- **Why I'm not acting now:** Phase 0 freeze. Research doc exists at `docs/FILTER_30_SMC_BIAS_RESEARCH.md`.

### 2026-06-17 — F31: DXY anti-correlation confirmation (Gold-only)
- **Phase noticed:** Pre-challenge
- **Source:** External read on Gold's USD-denominated math
- **Cost to investigate:** ~3hr BT sweep
- **Why it matters:** If DXY moves up ≥ X bps in N minutes, suppress Gold LONG entries.
- **Why I'm not acting now:** Phase 0 freeze. Parked behind F30. Doc at `docs/FILTER_31_DXY_CONFIRMATION_RESEARCH.md`.

### 2026-06-17 — F29: Bar-aware BE check
- **Phase noticed:** Pre-challenge (GD-AL-4af2d62d postmortem)
- **Source:** Trade reached 60.8% to TP but BE never armed
- **Cost to investigate:** Phase 1 instrumentation (~1hr) + BT sweep (~2hr) after data collected
- **Why it matters:** If BE-arm logic is missing fast moves, every winning trade loses optionality.
- **Why I'm not acting now:** Need live BE_PROGRESS journal events first. Defer to Phase 3 ship slot if data warrants.

### 2026-06-17 — Backend `is_latest` race + `/backtest/latest` API drift
- **Phase noticed:** Day 1 (Jun 18 night) frontend crash investigation
- **Source:** Concurrent BT runs from UI raced UPDATE statement → 0 rows with is_latest=TRUE
- **Cost to investigate:** ~30min — single-row enforcement via tx + unify wrap shape across 4 services
- **Why it matters:** Frontend crashed. Workaround shipped (commit b014083). Real fix deferred.
- **Why I'm not acting now:** P1, not bleeding. Phase 3 ranking candidate.

### 2026-06-17 — F28 audit Phase 2 items (H4/M1/M2/M3/M5)
- **Phase noticed:** Pre-challenge
- **Source:** Sherlock audit of F28 ship
- **Cost to investigate:** ~90min total
- **Why it matters:** H4 (BIAS_MODE re-read at scan time) enables hot-flip without restart. M5 (single-seed disclaimer) is honesty about validation strength.
- **Why I'm not acting now:** Phase 0 freeze. None are bleeding. Phase 3 ranking candidate.

---

## Phase 0 ideas (Days 1–7)

_(append below as ideas arise — DO NOT ACT)_

### 2026-06-18 — 🟠 P1: F28 NOT wired into BT routes (all 4 systems)
- **Phase noticed:** Phase 0, Day 1
- **Source:** User ran Gold Micro BT from UI, saw same numbers as pre-F28 → suspected F28 inactive in BT
- **Verified:** All 4 BT routes (`backend/routes/backtest.py`, `backend-oil/routes/backtest.py`, `backend-micro/routes/backtest.py`, `backend-oil-micro/routes/backtest.py`) call `run_backtest()` WITHOUT `bias_mode` kwarg → engine resolves `None → "production"` (via `resolve_bias_mode` in `backend/backtest/neutral_bias.py`) → V1+V2 bias filter ON.
- **Live impact:** ZERO. Live scheduler reads `BIAS_MODE` from config correctly. Live trades still fire under neutral (F28 active live).
- **BT impact:** BT dashboard shows production numbers regardless of `BIAS_MODE` env var. UI badge would say neutral but BT result is production. Misleading.
- **Cost to investigate:** Already investigated. Cost to fix ≈ 30min (4 route files: read `BIAS_MODE` from config, pass to `run_backtest`).
- **Why it matters:** Phase 2 (DECIDE) F28 verdict relies on BT-as-baseline comparison. If BT can't run neutral, comparison is harder.
- **Why I'm not acting now:** This is M1 from `docs/FILTER_28_AUDIT_BACKLOG.md` — already known, already scoped, already documented. Discipline test: parked even though it's "small" and "I already know how." Phase 3 ranking candidate.
- **Workaround during freeze:** Live data is the source of truth for F28 verdict, not BT. The 5-seed multi-seed BT validation already done (Path B clean kwarg) covers the BT-side evidence. BT dashboard mismatch is annoying, not blocking.

---

## Phase 1 ideas (Days 8–14)

_(append below as postmortems reveal patterns)_

---

## Phase 2 ranking (Day 15–21)

_(when Phase 2 begins, rank items above by frequency / severity / fixability / confidence)_

---

## Anti-patterns to watch for

- 🚫 Adding 5 ideas a day — that's not parking, that's planning. Limit to 1-2 high-signal items per day.
- 🚫 Writing the idea AND researching it — research is acting. Park, don't research.
- 🚫 "Just a quick BT" — every 5hr sweep is "quick" until it's done. Sweep cost = time + biases the data.
- 🚫 Bundling ideas — keep entries atomic. One idea per entry even if related.
