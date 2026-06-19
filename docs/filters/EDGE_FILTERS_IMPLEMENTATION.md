# EDGE_FILTERS — Detailed Implementation Plan

**Status:** Pre-implementation — no filter shipped to live yet.
**Source of filters:** [docs/EDGE_FILTERS.md](EDGE_FILTERS.md) — 17 candidates total (#1-#9 user/eye-discovered, #10-#17 audit-discovered 2026-06-11).
**Hard rule:** No filter ships to live until backtest numbers + parity harness numbers + 1-week shadow-run numbers all confirm improvement on real data. **No fake numbers, no phantom fills, no assumptions.**

---

## Why this plan exists

Today's 8-of-9-recent-trades-losing pattern in Oil Macro/Micro forced a hard look at the strategy's entry quality. The user's eye caught Filter #8 (engulfing close-strength on a wick rejection) that the deterministic gate code missed. A follow-up audit surfaced 8 more candidates. **Past attempts to "improve the strategy" in this repo have caused 5+ live↔backtest drift bugs.** Every change to gate logic must therefore be:

1. **Implemented in BOTH live and backtest paths simultaneously** (the duplicate-code reality of this repo).
2. **Measured by the parity harness** to ensure both paths produce the same skip decisions on the same inputs.
3. **Backtested over 6+ months** of real M3 data across all 4 systems before any go-live.
4. **Shadow-run for 1 week** in production: the filter logs skip events but does NOT block trades, so we can see what it WOULD have skipped against actual outcomes.
5. **Evaluated with a numeric improvement bar:** parity_pct stays within 5pp of v1 baseline, total backtest PF improves, win rate improves, max drawdown does not worsen.

A filter that fails any of those steps does NOT ship.

---

## The 17 candidate filters (priority order)

Priority is determined by: (a) severity of the bug it would fix vs the alpha it would unlock, (b) implementation cost, (c) parity-harness risk.

| # | Filter | Type | Priority | Severity | Backtest Cost |
|---|---|---|---|---|---|
| **#17** | Live ≠ Backtest risk threshold (Oil Macro) | **Drift bug** | **0** | CRITICAL | 0 (1-line fix) |
| **#11** | Non-deterministic slippage (random term) | **Parity blocker** | **0** | CRITICAL for measurement | Low |
| #1  | Range Exhaustion | Signal-gen filter | 1 | High alpha | Low |
| #8  | Engulfing close-strength (user-discovered) | Signal-gen filter | 2 | High alpha | Low |
| #10 | Spread-Inside SL (Oil Macro) | Signal-gen / sizing | 3 | Medium alpha | Medium (needs spread tracking) |
| #12 | Engulfing-of-Doji | Signal-gen filter | 4 | Medium alpha | Low |
| #16 | Raise R:R lower bound to 1.0+ | Calibration | 5 | Medium alpha | Low |
| #9  | R:R Upper Bound 4.0 | Signal-gen filter | 6 | Low alpha | Low |
| #13 | Engulfing wick-vs-body | Signal-gen filter | 7 | Low alpha (overlaps #8) | Low |
| #5  | BE 50% → 35% | Calibration | 8 | Medium alpha | Low |
| #14 | prev=sweep-bar pollution | Signal-gen filter | 9 | Low-Medium alpha | Low |
| #4  | Anti-Trend-Extension | Signal-gen filter | 10 | Likely subsumed by #1 | Medium |
| #3  | TP Feasibility | Signal-gen filter | 11 | Low alpha | Medium |
| #15 | Cooldown bypass (Macro pre-mark) | Bug fix | 12 | Defensive | Low |
| #6  | Trailing SL after BE | Calibration | 13 | Medium alpha, high complexity | High |
| #7  | Partial TP at 50% | Calibration | 14 | High complexity | Highest |
| #2  | First-Sweep-of-Day | Signal-gen filter | 15 | Likely redundant w/ #1 | Low |

**Drift bugs first (#17, #11), then alpha generators (#1, #8, #10), then defensive/calibration (#16, #12, #9, #5, #13, #14), then complex execution changes (#6, #7).** This ordering makes each phase's results interpretable: by the time we measure #1's effect, the parity harness numbers won't be polluted by #11's randomness, and the live≠backtest drift in #17 won't shift #1's measured skip rate.

---

## Phase Plan

### Phase 0 — Fix the parity-blockers BEFORE measuring any filter

These two fixes don't ADD any strategy logic. They just make the system measurable.

#### 0.1 — Ship Filter #17 (live↔backtest risk threshold)

- **Edit:** `backend-oil/scanner/scheduler.py:285,299` and `backend-oil/scanner/scheduler.py` mirrored locations in `_run_alpha_sweep_core`. Change `risk < 0.01` to `risk < 0.3`.
- **Test:** Run parity harness. Expected: oil_macro parity_pct increases (closer to backtest) because live now matches backtest's stricter floor.
- **Adversarial test:** Construct a synthetic ParityScore where pre-fix oil_macro had a "live signal that backtest skipped because of risk<0.3" — confirm the diff disappears post-fix.
- **Acceptance:** Parity harness still passes (no regression on Gold/Oil Micro/Gold Macro). Oil Macro's parity_pct moves toward 100% on the formerly-drifting subset.

#### 0.2 — Ship Filter #11 (deterministic slippage)

Two options. Pick one based on backtest sensitivity:

**Option A (simplest):** Drop the random term entirely. `slippage(br) = 0.03 + br * 0.003`.

**Option B (preserves variance modeling):** Seed the random term per-bar. `np.random.seed(int(bar_timestamp.timestamp()) % 2**31); return 0.03 + br * 0.003 + np.random.uniform(0, 0.02)`. Each bar gets a deterministic but trade-specific slippage value.

- **Edit:** `backend/config.py:85`, `backend-oil/config.py:51`, `backend-oil-micro/config.py:59`, `backend-micro/config.py` (verify same shape). Apply the same option to all four — symmetry is critical for parity.
- **Test:** Run the parity harness twice on the same window without changing anything else. Without the fix, parity_pct can vary by 1-3pp run-to-run. With the fix, parity_pct must be identical to 4 decimal places.
- **Acceptance:** Two consecutive harness runs produce identical parity_pct. Backtest engines produce identical P&L on the same input data.

**Why this matters:** if we measure "filter #1 dropped parity_pct by 5pp" but the harness itself has 3pp run-to-run noise, we can't distinguish filter effect from harness noise. Phase 0.2 must land before any Phase 1+ measurement.

---

### Phase 1 — Each Filter Goes Through The Same 5-Step Gate

For each filter from priority list (starting #1), execute the following pipeline. **No shortcuts. No assumptions.** A filter that fails any step does not ship.

#### Step 1.1 — Implement in LIVE path

- Add the filter to the live scheduler core function (`_run_alpha_sweep_core` for Macro, `_run_micro_sweep_core` for Micro) inside an `if EDGE_FILTERS.get("X_enabled", False):` guard. Default disabled.
- Fail-mode: if the filter logic itself raises, log the error and treat as "filter not triggered" (don't crash signal generation).
- Add a dedicated `skip_reason` string (`"edge_filter:range_exhaustion"`, `"edge_filter:engulfing_close_too_weak"`, etc.) that's distinguishable in `gd_signals`.
- Verify via py_compile + run existing harness (test_22_parity, test_15, test_19, etc.). All must still pass.

#### Step 1.2 — Implement in BACKTEST path

- Mirror the SAME logic in `backend/strategies/<module>.py:generate_signals()`. Same threshold values, same comparison operators, same skip-reason string.
- This is the step where past drift bugs have happened — `grep` for the gate's variable names in BOTH paths and verify the values, comparisons, and ordering are identical.

#### Step 1.3 — Parity Harness Gate

- Run `pytest tests/harness/test_22_parity.py -v`.
- **With filter DISABLED (default):** parity_pct must match v1 baseline ±0.5pp on all 4 systems. (Validates the filter scaffolding doesn't itself drift.)
- **With filter ENABLED via env var:** parity_pct must STAY ABOVE v1 baseline minus 5pp on all 4 systems. (Filter that drops parity by >5pp is asymmetrically implemented.)
- **Direction agreements** must remain at 100% on the overlapping signals. (A filter that flips even one signal is a strategy logic divergence, not a filter.)
- Adversarial check: temporarily change one threshold value in live but not backtest. Re-run harness. Parity must drop. Revert. Parity recovers. (Confirms the harness itself is sensitive to filter divergence.)

**If parity drops >5pp after filter enable:** STOP. Investigate the live↔backtest divergence in the new filter code. Don't proceed.

#### Step 1.4 — Backtest Numbers (the alpha measurement)

- Run backtest on each system over **at least 6 months** of M3 data. Suggest May 2026 - Nov 2026 if available, otherwise full history.
- Compute the 6 canonical metrics WITH and WITHOUT the filter:
  - Total trades
  - Win rate
  - Profit factor
  - Net P&L
  - Max drawdown
  - Average winner / average loser

Output format (one row per system per filter):

```
System         Filter Off                     Filter On
gold_micro     PF=4.58, WR=80%, N=4163, DD=$X PF=Y, WR=Z%, N=N', DD=$X'
oil_micro      ...                            ...
gold_macro     ...                            ...
oil_macro      ...                            ...
```

**Improvement bar (filter ships only if all hold):**
- PF improves by ≥10% on at least 3 of 4 systems
- Win rate improves OR stays flat (no system regresses by >2pp)
- Max DD does not worsen by >10% on any system
- Total trades: -10% to -30% reduction is acceptable; >40% reduction is a red flag (curve-fit suspicion)

**If the backtest numbers don't clear the bar:** STOP. The filter doesn't add edge in aggregate. Don't ship.

#### Step 1.5 — Shadow-Run on Live for 7 Days

- Deploy the filter to the VPS with `_enabled: True` BUT with a `_shadow_mode: True` flag that LOGS the skip event but does NOT block trade execution.
- For 7 days, every signal that the filter WOULD HAVE skipped is recorded in a new journal event type (`EDGE_FILTER_SHADOW_SKIP`) but the trade still fires.
- After 7 days, query the journal: for every shadow-skipped trade, did the actual outcome (TP/SL/MAX_HOLD) match the filter's hypothesis?
  - If filter hypothesis was "this trade would have been a loss," and actual outcome was a loss → filter judgement validated.
  - If filter would have skipped winners → filter is too aggressive, recalibrate or kill.
- Acceptance: the shadow-skipped subset must have a NEGATIVE expected value across the 7-day sample. Otherwise the filter is skipping winners as well as losers.

#### Step 1.6 — Ship to live (real skip)

- Toggle `_shadow_mode: False` so the filter actually blocks trades.
- Continue monitoring journal for `EDGE_FILTER_SKIP` events.
- Weekly cadence: review skipped trades vs taken trades, confirm no asymmetric impact (e.g. only Gold Micro signals being skipped, or only LONG signals).

---

## Per-Filter Implementation Notes

(Each filter's specifics. Cross-reference with `docs/EDGE_FILTERS.md` for full rationale.)

### Phase 0 — Pre-requisites

#### #17 (live ≠ backtest risk threshold) — 1 file change
- File: `backend-oil/scanner/scheduler.py` lines 285, 299.
- Change: `risk < 0.01` → `risk < 0.3` (match backtest at `backend/strategies/alpha_sweep.py:111`).
- Test: parity harness shows oil_macro parity_pct converging to backtest.

#### #11 (deterministic slippage) — 4 file changes
- Files: `backend/config.py:85`, `backend-oil/config.py:51`, `backend-oil-micro/config.py:59`, `backend-micro/config.py` (verify path).
- Test: run parity harness twice consecutively; identical parity_pct to 4 decimals.

### Phase 1 — Highest priority alpha filters

#### #1 (Range Exhaustion)
- Live impl: `backend-oil/scanner/scheduler.py:_run_alpha_sweep_core` after sweep+engulfing detection but before SL/TP/risk computation.
- Backtest impl: `backend/strategies/alpha_sweep.py:generate_signals` at the same logical position.
- Threshold candidates: 0.6, 0.7, 0.8, 0.9 of ATR_20.
- Today's `OIL-AS-f5e9710a` would have been skipped at threshold 0.7.

#### #8 (Engulfing close-strength)
- Live impl: inside the existing engulfing detector loop, after the `cb <= pb + tol AND ct >= pt - tol` check passes.
- Backtest impl: same mirror.
- Threshold candidates: 0.55, 0.60, 0.65, 0.70, 0.75.
- Today's `OIL-AS-f5e9710a` engulfing was estimated close-position 0.60 — threshold 0.65 would skip.

#### #10 (Spread-Inside SL)
- Live impl: at SL computation (`sl = sweep_wick - cfg["sl_buffer"]`), replace with `sl_buffer_effective = max(cfg["sl_buffer"], 1.5 × current_spread)`.
- Backtest impl: backtest doesn't currently model spread per-bar — needs adding. Read `bid_close - ask_close` from the M3 candle dict.
- This is the most complex of the Phase-1 set because backtest needs spread-tracking infrastructure that doesn't exist yet.

### Phase 2+ — Subsequent priority filters

Cover the remaining filters with the same 5-step gate. Each filter's implementation goes in its own commit with its own backtest-numbers commit message.

---

## Numbers Tracking

A new file `docs/EDGE_FILTERS_RESULTS.md` will be created when the first filter passes Phase 0. Each row records:

| Filter | Date Tested | Parity Δ (gold_micro / oil_micro / gold_macro / oil_macro) | Backtest PF Δ | Backtest WR Δ | Shadow-run Skip P&L | Decision |
|---|---|---|---|---|---|---|

This is the single source of truth for "did this filter actually improve numbers." If a future drive-by attempt to ship a filter doesn't have a row here, it doesn't ship.

---

## Verification — How To Tell If This Plan Is Working

The plan is a success when:

1. **Filter #17 + #11 ship cleanly:** parity harness numbers stabilize (no run-to-run drift), oil_macro parity_pct converges to its true value.
2. **Filter #1 ships with measurable backtest improvement** (PF up, no DD regression). Live shadow-run validates the skipped trades were net-negative.
3. **At least 4 of the 9 user-discovered filters ship within 60 days.** Each leaves a row in EDGE_FILTERS_RESULTS.md.
4. **No new live↔backtest drift bugs surface during the rollout.** The parity harness catches divergence at Step 1.3 BEFORE backtest measurement.

The plan fails (and we revisit) if:

- Three consecutive filters fail at Step 1.4 (backtest doesn't show alpha) → the filter ideas may be over-fitted to recent losing pattern; broader review needed.
- The parity harness routinely flags >5pp drift after a filter add → filter implementation is asymmetric in subtle ways (config dict vs hardcoded, etc.); need stronger code review.
- A shadow-run shows the filter would skip >50% of trades → too aggressive, the filter is rejecting setups that were OK on average.

---

## What This Plan Is NOT

- **Not a strategy rewrite.** Alpha-Sweep core (sweep + engulfing + bias) stays unchanged. We add quality filters around it.
- **Not a "ship all 17."** Realistic shipping list is 5-7 filters that meaningfully add edge. The rest get shelved as "tested, didn't help."
- **Not a backtest curve-fit.** Each filter must be motivated by REAL incident data (a trade that lost) before it's tested. We're not trying random thresholds and keeping winners.
- **Not a retroactive justification for today's losses.** The 5/7 SL pattern is information, not a regime to fit against. Filters must improve PF on the FULL backtest history, not just recent weeks.

---

## Open questions

These are deferred to implementation. Don't pretend to answer them now.

1. **Where does `EDGE_FILTERS` config live?** New section in `backend/config.py`, or per-system in each `backend-*/config.py`? Per-system is more flexible but harder to keep in sync.
2. **How is the per-filter `_enabled` flag exposed?** Env var? Config file edit + restart? Hot-reload via API endpoint?
3. **Shadow-mode storage:** does `EDGE_FILTER_SHADOW_SKIP` go in `gd_journal` or its own `gd_shadow_skips` table?
4. **Backtest engine spread modeling for #10:** does the M3 CSV data contain bid/ask separately or only mid? Need to verify before sizing #10's effort.
5. **What's the canonical backtest replay window?** 6 months / 1 year / full history? Trade-off between statistical power and regime relevance.

---

## Reference

- Filter list: `docs/EDGE_FILTERS.md`
- Parity harness: `docs/PARITY_HARNESS.md` and `tests/harness/test_22_parity.py`
- Drift-bug history: `docs/LIVE_VS_BACKTEST_PARITY.md` and memory `[[project-live-backtest-parity-gap]]`
- Audit transcript that surfaced #10-#17: ran 2026-06-11, captured in this doc's #10-#17 sections
