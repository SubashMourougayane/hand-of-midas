# Parity Harness — Plain-Language Explainer + Next-Session Plan

**Audience:** future-Subash, future-collaborators, anyone wondering "what is the parity harness for and what's the plan."
**Companion to:** [PARITY_HARNESS.md](PARITY_HARNESS.md) (operator guide), [PARITY_HARNESS_PLAN.md](PARITY_HARNESS_PLAN.md) (design rationale), [EDGE_FILTERS.md](EDGE_FILTERS.md) (the 17 filter candidates), [EDGE_FILTERS_IMPLEMENTATION.md](EDGE_FILTERS_IMPLEMENTATION.md) (rollout plan).

---

## The two layers, in one minute each

### Layer 1: The strategy code

Hand of Midas runs **two implementations of the same strategy** side by side:

| Path | Where it lives | What it does |
|---|---|---|
| **LIVE** | `backend-oil/scanner/scheduler.py` and 3 siblings | Runs every 3 minutes on the VPS. Reads current market data from MT5. Decides whether to place a real order. Money at stake. |
| **BACKTEST** | `backend/strategies/alpha_sweep.py` and `backend/strategies/micro_alpha_sweep.py` | Walks historical CSV data offline. Decides which trades it would have taken. Produces P&L numbers like "PF 3.5, win rate 80%, $640k over 11 years." |

These are two SEPARATE codebases for the same strategy. Roughly 450 lines duplicated between them. The two should produce the same signals on the same input bars. **They don't, always.**

### Layer 2: The parity harness

The parity harness (`tests/harness/test_22_parity.py`) does one thing:

> For the same input bars, ask both implementations "what signals do you produce?" — and compare.

- LIVE says SHORT @ $4097.27 at 08:30 UTC; BACKTEST says SHORT @ $4097.27 at 08:30 UTC → perfect parity.
- LIVE says SHORT, BACKTEST says nothing → drift.
- LIVE says SHORT, BACKTEST says LONG → strategy-logic bug, the most serious kind.

The harness measures this quantitatively, writes a JSON report, and ships running automatically. Catastrophic drift (parity < 50% or directions flip) fails the test and blocks deploy.

---

## Why drift matters

The entire trading decision is built on backtest numbers. When you cite "PF 3.5, $640k expectancy over 11 years" — that's the BACKTEST claim. **If LIVE is doing something different from BACKTEST, those backtest numbers are lies for predicting your live results.**

In the past 3 weeks, **6 confirmed drift bugs** have hit the system, costing real money:

1. **TDB (Timezone Drift Bug)** — live's `ts.hour` filtered MT5 server hours, backtest used real UTC. 18% live/backtest signal overlap for weeks. ~$1,255 cost over 7 days.
2. **Oil Macro V1-only bias** — live used V1, backtest used Combined V1+V2.
3. **Strategy column VARCHAR(20) overflow** — `'micro_alpha_sweep_oil'` (21 chars) silently truncated, every DB INSERT failed for Oil Micro. 7 orphan trades on June 10.
4. **Phantom-fill BE-ambiguity** — close detected at wrong price; trade GD-MI-cce2a254 reported +$9 vs real +$910.80.
5. **OnTradeTransaction dual-instance gap** (today, twice — `OIL-AS-5434644d` and `OIL-AS-59a94823`) — DB rows stuck open while broker has closed positions because Mac MT5 EA didn't write `closed_orders.json`.
6. **Live ≠ Backtest risk threshold (Filter #17)** — Oil Macro live: `risk < 0.01`; Oil Macro backtest: `risk < 0.3`. **Live takes trades the backtest never simulated.**

Each is the same class of bug: somebody changed strategy logic on one side and forgot to mirror it on the other. The parity harness exists to catch this class automatically.

---

## Status of the parity harness right now

**Built and running.** Today's session shipped Phases 1-6 across 6 commits.

| What | Status |
|---|---|
| All 4 systems wired up | ✅ Gold Macro, Gold Micro, Oil Macro, Oil Micro |
| Test runs in pytest | ✅ `pytest tests/harness/test_22_parity.py -v` |
| Runtime | ~25 seconds for full 4-system run on 7 days of data |
| JSON artifact per run | ✅ written to `tests/harness/parity_reports/` (gitignored) |
| Soft-gate auto-fail | ✅ pytest fails if parity drops below 50% or 5+ direction disagreements |
| Soft-gate warning | ✅ pytest warns if parity below 85% or any disagreement |
| Diagnosis hints per signal | ✅ each diff explains "why does this signal differ" |
| v1 baseline measured | ✅ recorded in `docs/PARITY_HARNESS.md` |

### v1 baseline measurements (May 19-26 2026 data)

| System | Parity | BT signals | Live signals | Both | Direction agreement |
|---|---|---|---|---|---|
| Gold Micro | 60.0% | 5 | 15 | 3 | **3/3 = 100%** |
| Oil Micro | 77.0% | 11 | 11 | 6 | **6/6 = 100%** |
| Gold Macro | 59.9% | 1 | 5 | 1 | **1/1 = 100%** |
| Oil Macro | 57.4% | 1 | 6 | 1 | **1/1 = 100%** |

**Headline finding:** when both paths see the same setup, they agree 100% on direction. The drift is exclusively in WHICH bars produce signals — live polls every M3 bar, backtest walks H1 bars, so live finds more candidate setups. **No catastrophic strategy-logic drift detected at v1.**

---

## What "running numbers" means in the EDGE_FILTERS plan

The parity harness becomes the safety mechanism for shipping the 17 filter ideas in `docs/EDGE_FILTERS.md`. The pattern for every filter (formalized in `docs/EDGE_FILTERS_IMPLEMENTATION.md`):

### Step-by-step for one filter (e.g., #1 — Range Exhaustion)

1. **Add the filter to the LIVE scheduler.** It skips trades when today's range is already >70% of typical ATR.
2. **Add the SAME filter to the BACKTEST module.** Same threshold, same comparison, same skip-reason string.
3. **Run the parity harness.** Two checks:
   - With filter DISABLED: parity_pct must match v1 baseline ±0.5pp. (Validates the filter scaffolding doesn't itself drift.)
   - With filter ENABLED: parity_pct must stay within 5pp of v1. **If parity drops 10pp+ when you turn the filter on, the filter is implemented ASYMMETRICALLY between live and backtest. STOP. Don't ship until they match.**
4. **Run the backtest with the filter on.** Compute 6 metrics: total trades, win rate, profit factor, net P&L, max drawdown, average winner/loser. Compare to filter off.
   - Filter ships only if PF improves by ≥10% on at least 3 of 4 systems, win rate doesn't regress, max DD doesn't worsen by >10%.
   - **These are the "running numbers" the user keeps emphasizing.** Every filter must pay for its existence with measurable backtest improvement.
5. **Shadow-run on live for 7 days.** Filter logs "I would have skipped this" but DOESN'T block it. After 7 days, check whether the would-be-skipped trades had negative average outcome. If yes, filter is sound. If they were 50/50, filter is throwing away decent trades.
6. **Toggle to real-skip mode.** Filter actually blocks trades.

A filter that fails ANY step does not ship. **Realistic count: 5-7 of 17 will pass.** The rest get archived in `docs/EDGE_FILTERS_RESULTS.md` (created on first ship) as "tested, didn't help."

### Why "no fake numbers" matters

The temptation when proposing 17 filters is to write things like "this should improve PF by 30%" based on intuition. **That's not measurement.** The implementation plan forbids it: every filter's PF improvement must come from running the backtest engine on the same input data with and without the filter. No estimates. No simulated thought experiments. Real numbers.

The audit found a meta-bug (#11) that prevents real numbers in the current state: `slippage()` uses unseeded `np.random.uniform`, so two backtest runs on the same data give different P&L. Until that's deterministic, you can't tell "did this filter improve PF" from "did the random number generator just roll favorably this run." That's why Phase 0 fixes #11 BEFORE any filter measurement.

---

## How to verify the harness yourself (canary checks)

These confirm the harness is real and not vibes. Both should be run by next session before any new filter measurement.

### Check 1: Different inputs → different parity numbers

```bash
PARITY_DAYS=7 pytest tests/harness/test_22_parity.py -v -k gold_micro
PARITY_DAYS=30 pytest tests/harness/test_22_parity.py -v -k gold_micro
```

Numbers should differ. If they're identical, the harness isn't actually consuming the date-range parameter.

### Check 2: Intentional drift → harness catches it

1. Edit one threshold value in `backend-micro/config.py` (live side only).
2. Run the harness.
3. Parity should drop, because backtest's threshold no longer matches live's.
4. Revert.
5. Parity recovers.

If neither drop nor recovery happens, the harness has a bug. **Neither check has been adversarially run yet** (only Phase 2's gate-logic synthetic tests). Doing this is the first item in next session.

---

## Next session plan

Strict ordering. Phase 0 must complete and verify before any Phase 1 filter starts.

### Phase 0 — Make the harness measurable (prerequisite for everything else)

#### 0.1 Run the two canary checks above

Confirms the harness is sensitive to inputs and to drift. ~10 minutes.

#### 0.2 Ship Filter #17 (live ↔ backtest risk threshold) — one-line drift fix

- File: `backend-oil/scanner/scheduler.py` lines 285, 299. Change `risk < 0.01` to `risk < 0.3`.
- Mirrors `backend/strategies/alpha_sweep.py:111` which is the backtest threshold.
- Test: parity harness shows oil_macro parity_pct increases (closer to backtest).
- Adversarial: temporarily revert, confirm parity drops, re-apply.
- Acceptance: parity harness still passes; oil_macro parity_pct moves measurably toward 100% on the formerly-drifting subset.

This is the **6th confirmed drift bug** of the past 3 weeks. Closing it shrinks the live↔backtest gap before we measure filter effects.

#### 0.3 Ship Filter #11 (deterministic slippage)

- Pick option: drop random term entirely (`return 0.03 + br * 0.003`) OR seed it per-bar (`np.random.seed(int(bar_timestamp.timestamp()) % 2**31); return 0.03 + br * 0.003 + np.random.uniform(0, 0.02)`).
- Apply identically to all four config files: `backend/config.py:85`, `backend-oil/config.py:51`, `backend-oil-micro/config.py:59`, and `backend-micro/config.py` (verify path).
- Test: run parity harness twice on the same window. Parity_pct must be identical to 4 decimal places. Backtest engines must produce identical P&L on the same input data.
- Acceptance: zero run-to-run variance.

Without this, the parity harness has 1-3pp run-to-run noise from unseeded randomness, which would swamp filter-effect measurement.

#### 0.4 Re-establish the v1 baseline post-fixes

Run the parity harness once. Record the new baseline numbers in `docs/PARITY_HARNESS.md` (append a "v1.1 baseline post-Phase 0" section, don't overwrite v1). All future filter measurements compare to this v1.1 baseline.

### Phase 1 — Three highest-priority alpha filters

Each goes through the full 6-step gate from `EDGE_FILTERS_IMPLEMENTATION.md`. Order:

1. **#1 Range Exhaustion** (today's `OIL-AS-f5e9710a` + `GD-MI-14e2fed1` would have been skipped at threshold 0.7).
2. **#8 Engulfing Close-Strength** (your eye-catch on the wick rejection — `OIL-AS-f5e9710a` close-position estimated 0.60, threshold 0.65 would skip).
3. **#10 Spread-Inside SL** (Oil Macro `sl_buffer=0.03` vs spread ~$0.10 — every Oil Macro stop costs ~$0.07/unit more than backtest predicts). Most complex of Phase 1 because backtest needs spread-tracking infrastructure.

For each filter, expected timeline: ~1 hour to implement live + backtest in parallel, ~30 min for parity harness gate, ~3 hours for backtest runs across 4 systems, then 7-day shadow-run live before real-skip toggle.

### Phase 2 — Defensive / calibration filters

After Phase 1 lands and stabilizes:

- **#12 Engulfing-of-Doji** (no prev-body magnitude check)
- **#16 Raise R:R lower bound** (0.8 → 1.0 absorbs slippage erosion)
- **#9 R:R upper bound** (today's `OIL-AS-59a94823` had R:R 6.53)

### Phase 3 — Execution refinements (calibration)

- **#5 BE 50% → 35%**
- **#13 Engulfing wick-vs-body** (overlaps with #8; ship only if measurably independent)
- **#14 prev=sweep-bar pollution** (require prev to be reversal-direction)
- **#15 Cooldown bypass** (Macro pre-marks _traded_sweeps; defensive)

### Phase 4+ — High-complexity execution changes

- **#6 Trailing SL after BE** (schema change: explicit `be_armed` column)
- **#7 Partial TP at 50%** (multi-leg trade tracking, schema change for `partial_tp_taken`)
- **#3 TP Feasibility** (needs ATR_H1 infrastructure)
- **#4 Anti-Trend-Extension** (heavily overlaps with #1; may be skipped entirely)
- **#2 First-Sweep-of-Day** (likely subsumed by #1; almost certainly never ships)

### Phase 5 — Documentation + post-mortem

After 5+ filters have landed:

- Create `docs/EDGE_FILTERS_RESULTS.md` with one row per shipped/tested filter:

  | Filter | Date | Parity Δ (gm/om/gM/oM) | Backtest PF Δ | Backtest WR Δ | Shadow-skip P&L | Decision |
  
- Update `EDGE_FILTERS.md` with which filters are live and which were shelved.
- Re-run the parity harness baseline; record v2 baseline reflecting the post-filters reality.
- Update memory with the lessons learned, particularly which filters surfaced REAL alpha vs which were intuition that didn't pay out.

### Hard rules across all phases

1. No filter ships on intuition. Every PF claim is from real backtest output.
2. Every filter is implemented in BOTH live and backtest in the same commit. The parity harness rejects asymmetric implementations.
3. The 7-day shadow-run is non-negotiable for any filter that affects entry decisions. Calibration changes (#5, #6) get a shorter validation window because they affect execution, not signal generation.
4. If three consecutive filters fail at Step 1.4 (no backtest improvement), pause the rollout and audit whether the filter ideas are over-fitted to recent losing pattern.
5. If a parity harness run flags >5pp drift after a filter add, treat as a P0 — the filter is asymmetrically implemented; STOP and fix before any further work.

---

## What this plan is NOT

- Not a strategy rewrite. Alpha-Sweep core (sweep + engulfing + bias) stays unchanged.
- Not a "ship all 17." Realistic 5-7. The rest get logged as tested, didn't help.
- Not a backtest curve-fit. Each filter must be motivated by REAL incident data (a trade that lost) before it's tested.
- Not a retroactive justification for today's 5/7 SL pattern. Filters must improve PF on full backtest history, not just recent weeks.

---

## Reference

- Filter list: `docs/EDGE_FILTERS.md` (17 candidates)
- Implementation gate: `docs/EDGE_FILTERS_IMPLEMENTATION.md`
- Operator guide: `docs/PARITY_HARNESS.md`
- Design rationale: `docs/PARITY_HARNESS_PLAN.md`
- Drift-bug history: `docs/LIVE_VS_BACKTEST_PARITY.md`
