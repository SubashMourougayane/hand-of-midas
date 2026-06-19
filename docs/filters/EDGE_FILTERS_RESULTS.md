# EDGE_FILTERS — Results Log

One row per filter that has been measured. **No filter ships to live without numbers in this file.** No fake numbers, no phantom fills, no assumptions.

For the candidate catalog see [EDGE_FILTERS.md](EDGE_FILTERS.md). For the 6-step gate see [EDGE_FILTERS_IMPLEMENTATION.md](EDGE_FILTERS_IMPLEMENTATION.md).

---

## Filter #1 — Range Exhaustion (rejected 2026-06-12, threshold sweep)

**Status:** ❌ REJECTED. Tested across 5 thresholds × 4 systems = 20 backtests. NOT shipped.

**Type:** Alpha filter (skip when today's range is large vs typical recent ATR).

### Motivation

Live trade `GD-MI-09314bdd` (Gold Micro SHORT, -$1,012 SL on 2026-06-11) entered late in the session after Asia range was already wide. Hypothesis: late-day entries after the day has "burned its fuel" tend to be mean-reversion bets that get caught when the day's true direction reasserts.

### What was tested

For each engulfing entry, compute:
- **ATR_20** = average true range over the LAST 20 daily bars before trade-date (true range = max(day_high - day_low, |day_high - prev_close|, |day_low - prev_close|))
- **today_range** = today's H1 high minus today's H1 low (so far)
- **ratio** = today_range / ATR_20

Skip the trade if `ratio > threshold`.

**Bug found mid-session:** Initial implementation computed ATR over H1 bars (wrong) — single-bar true range averages ~ 1/4 of a daily range, so ratios came out ~5× too high. Fixed by computing ATR over DAILY bars. Without the fix, even threshold=0.5 rejected ~99% of trades. (Logged here so we don't repeat the mistake.)

After fix, distribution of `today_range / ATR_20` (Gold H1, 6,320 days):
- median 0.94, mean 1.02
- pct ≥ 0.7: 70%, pct ≥ 1.1: 37%, pct ≥ 2.0: 6.3%

Sensible thresholds: 0.9, 1.1, 1.3, 1.5, 2.0.

### Results — PF Δ vs baseline

| Threshold | Gold Macro | Gold Micro | Oil Macro | Oil Micro | Improved | Regressed |
|---|---|---|---|---|---|---|
| 0.9 | 2.78 (+0.22) | 2.53 (+0.11) | **1.99 (-0.67)** | 3.76 (+1.07) | 3 | 1 |
| 1.1 | 2.79 (+0.23) | 2.81 (+0.39) | **2.35 (-0.31)** | 3.40 (+0.71) | 3 | 1 |
| 1.3 | 2.71 (+0.15) | 2.81 (+0.39) | **2.37 (-0.29)** | 3.06 (+0.37) | 3 | 1 |
| 1.5 | 2.63 (+0.07) | 2.67 (+0.25) | **2.48 (-0.18)** | 2.87 (+0.18) | 3 | 1 |
| **2.0** | 2.65 (+0.09) | 2.55 (+0.13) | **2.69 (+0.03)** | 2.80 (+0.11) | **4** | **0** |

### Results — Net P&L Δ% vs baseline

| Threshold | Gold Macro | Gold Micro | Oil Macro | Oil Micro |
|---|---|---|---|---|
| 0.9 | **-63%** | -76% | -88% | -75% |
| 1.1 | -38% | -52% | -69% | -45% |
| 1.3 | -25% | -38% | -50% | -26% |
| 1.5 | -15% | -29% | -33% | -16% |
| 2.0 | **-3%** | -14% | -10% | -4% |

### Verdict — REJECT (despite formal pass at thr-2.0)

**Threshold 2.0 formally passes the gate** (PF improves on all 4 systems, no regression). But the trade-off is bad:
- ✅ Modest PF improvement (+0.03 to +0.13)
- ❌ Every system loses Net P&L (-3% to -14%)
- ❌ The skipped trades are net positive on average — strategy still profits from them
- ❌ Wouldn't catch the motivating live loss `GD-MI-09314bdd`: that trade's ratio was ~1.12, well below the thr-2.0 cutoff

**The hypothesis is rejected on its own data.** Late-day entries after wide-range days don't have systematically worse expected value. The motivating trade was an unlucky outcome from a normal-distribution setup, not a structural pattern.

Tighter thresholds (0.9-1.5) DO catch the motivating trade but regress Oil Macro PF and slash total P&L by 25-88%. None of those passes the gate spirit.

### Lessons captured

1. **Formal gate vs spirit gate**: a filter that improves PF marginally but loses 10%+ of total P&L is not making the strategy "better" — it's making it more risk-averse at the cost of expected value. Updated my mental model: the gate should require BOTH (PF improves) AND (Net P&L within ~5% of baseline).
2. **Eye-pattern motivations don't generalize.** The "exhausted range = bad entry" intuition felt strong from one trade. 21-yr data says it's wrong.
3. **Bug in metric definition is the silent killer.** ATR-on-H1 vs ATR-on-Daily produces 5x different ratios; threshold sensitivity flipped completely. Always sanity-check distribution before threshold sweep (mean ≈ 1.0 expected for "ratio of equivalent-timeframe ranges").

### Status

- All 4 modified files reverted clean.
- Parity harness re-verified (22 tests pass).
- Gold Macro baseline backtest reproduces exact post-#11 numbers ($346,196 / PF 2.56).

---

## Filter #11 — Deterministic slippage (shipped 2026-06-12, commit `d6896b4`)

**Status:** ✅ Shipped hard. No shadow mode.

**Type:** Measurement infrastructure / parity prerequisite.

### What changed

```python
# Before (all 4 systems):
def slippage(bar_range): return 0.03 + br*X + np.random.uniform(0, Y)
# After:
def slippage(bar_range): return (0.03 + Y/2) + br*X
```

Per-system Y values: 0.02 for Gold/Oil Macro/Micro, 0.005 for Oil Micro. Mean slippage preserved exactly.

### 21-yr backtest pre/post

| System | Pre PF | Post PF | Pre Net P&L | Post Net P&L | Pre Trades | Post Trades |
|---|---|---|---|---|---|---|
| Gold Macro | 2.56 | **2.56** | $346,863 | $346,196 | 2,242 | 2,242 |
| Gold Micro | 2.42 | **2.42** | $239,898 | $240,254 | 1,855 | 1,855 |
| Oil Macro | 2.64 | **2.66** | $625,996 | $645,588 | 1,605 | 1,609 |
| Oil Micro | 2.69 | **2.69** | $2,010,717 | $2,010,717 | 4,425 | 4,425 |

All within 1% on PF, identical or near-identical trade counts. Mean preserved.

### Parity harness pre/post (7-day window)

| System | Pre | Post |
|---|---|---|
| Gold Micro | 79.9% | **80.0%** |
| Oil Micro | 86.1% | **86.1%** |
| Gold Macro | 79.9% | **80.0%** |
| Oil Macro | 74.2% | **75.0%** |

All systems retained 100% direction agreement on overlaps.

### Acceptance gates (all passed)

1. ✅ Two consecutive harness runs **byte-identical** (was ~0.07pp noise)
2. ✅ All 4 systems within 1% on 21-yr PF
3. ✅ All 4 systems same trade count ±0.3%
4. ✅ Parity inched up everywhere (deterministic entry-price-delta noise removed from 20% weight)

### Verdict

✅ **Keep.** Drops run-to-run noise without changing strategy outcomes. Future filter A/B tests now reproducible.

---

## Filter #8 — Engulfing Close-Strength (rejected 2026-06-12, threshold sweep)

**Status:** ❌ REJECTED at all 5 thresholds tested. NOT shipped.

**Type:** Alpha filter (require engulfing candle to close in upper/lower fraction of range).

### Motivation

Live trade `GD-MI-09314bdd` (Gold Micro SHORT, -$1,012 SL) entered on a doji-engulfing-doji setup that the user spotted visually. Hypothesis: filter out engulfings whose close lies near mid-range.

### What was tested

Sweep across 5 thresholds (lower/upper for bearish/bullish close-position):
- strict-25: bearish ≤ 0.25, bullish ≥ 0.75
- med-30: bearish ≤ 0.30, bullish ≥ 0.70
- default-35: bearish ≤ 0.35, bullish ≥ 0.65 (the spec default)
- loose-40: bearish ≤ 0.40, bullish ≥ 0.60
- vloose-45: bearish ≤ 0.45, bullish ≥ 0.55

Each threshold ran the full 21-yr backtest on all 4 systems. Filter applied to BOTH live and backtest signal-gen via env var (`FILTER8_THRESH=X`); reverted after measurement.

### Results — PF Δ vs baseline

| Threshold | Gold Macro | Gold Micro | Oil Macro | Oil Micro | Improved | Regressed |
|---|---|---|---|---|---|---|
| strict-25 | 2.52 (-0.04) | 2.44 (+0.02) | **2.31 (-0.35)** | 2.58 (-0.11) | 1 | 3 |
| med-30 | 2.54 (-0.02) | 2.44 (+0.02) | 2.45 (-0.21) | 2.57 (-0.12) | 1 | 3 |
| default-35 | 2.55 (-0.01) | 2.47 (+0.05) | 2.45 (-0.21) | 2.61 (-0.08) | 1 | 3 |
| loose-40 | 2.56 (flat) | 2.48 (+0.06) | 2.54 (-0.12) | 2.63 (-0.06) | 1 | 2 |
| vloose-45 | 2.56 (flat) | 2.47 (+0.05) | 2.55 (-0.11) | 2.64 (-0.05) | 1 | 2 |

### Results — Net P&L Δ% vs baseline

| Threshold | Gold Macro | Gold Micro | Oil Macro | Oil Micro |
|---|---|---|---|---|
| strict-25 | -21% | -15% | **-46%** | -33% |
| med-30 | -12% | -11% | -35% | -27% |
| default-35 | -10% | -4% | -31% | -21% |
| loose-40 | -7% | -1% | -24% | -15% |
| vloose-45 | -6% | **+1%** | -17% | -11% |

### Verdict — REJECT at all thresholds

**The pattern is uniform across all 5 thresholds:**
- ✅ Gold Micro PF improves (+0.02 to +0.06) — single system that benefits
- ❌ Oil Macro PF regresses on every threshold (-0.11 to -0.35)
- ❌ Oil Micro PF regresses on every threshold (-0.05 to -0.12)
- ⚠️ Gold Macro flat-to-down on every threshold
- 💸 Net P&L drops on EVERY system × EVERY threshold (only Gold Micro vloose-45 squeezes +1% P&L)

**Acceptance criteria** ("PF must improve on ≥3 of 4 with NO regression on any") fails at every tested threshold. Even the loosest threshold (45/55) regresses 3 of 4 systems.

### Why the filter doesn't work

The doji-like engulfings the user's eye flagged as "weak" are actually **NET PROFITABLE** in the 21-yr distribution. Our intuition that "doji = bad signal" doesn't hold up against 10,000+ trades. Especially on Oil where the wider spread relative to volatility makes most engulfings score lower on close-position.

### Lessons captured

1. **Eye-pattern recognition does NOT predict edge in the long tail.** A losing trade that looks "weak" may still be from a profitable distribution.
2. **Per-system structural differences matter.** Gold and Oil have different spread/volatility ratios. A filter calibrated on one can hurt the other. Future filters should be threshold-tunable PER system, not single-threshold-across-all.
3. **"No shadow mode" works.** We caught the regression in 30 minutes via 21-yr backtest sweep, not 7 days of live shadow data. The honest backtest is the strongest gate.

### Status

- All 4 modified files reverted to pre-Filter-#8 state.
- Parity harness re-verified at 75-86% post-revert.
- Filter #8 archived as "tested across 5 thresholds × 4 systems = 20 backtests, never improved ≥3 of 4 systems."

---

## Drift bug #6 fix — daily_bias keying off-by-one (all 4 systems)

**Status:** ✅ Shipped (commit `80ba0d3`, 2026-06-12).

**Type:** Critical drift bug (live↔backtest). NOT an edge filter — fixing this UNCOVERED that the strategies are weaker than previously believed.

### What changed

Every backtest engine and the parity harness keyed `daily_bias` with `oil_d.index[i].date()`, but OANDA daily bars use dailyAlignment=21: a bar timestamped `T 21:00` represents the `(T → T+1)` trading session, so its `.date()` is one day BEFORE the session it represents. Two compounding errors:

1. **Off-by-one:** BT's "yesterday" (`oil_d[i-1]`) actually represented the trade-date's OWN session.
2. **Missing days:** trade-dates that didn't appear as a daily-bar `.date()` (e.g., **all Fridays** — `Friday 21:00` starts the weekend, no bar emitted) silently skipped because `daily_bias.get(date, 'none')` returned `'none'` which the strategy treated as a directional bias nothing matches → 18% of recent days emitted ZERO BT signals.

Fix:
```python
# Before:
d = oil_d.index[i].date()           # bar.date() — wrong by 1 day, also misses Fridays
# After:
d = (oil_d.index[i] + pd.Timedelta(days=1)).date()  # = trade_date for which oil_d[i-1] is true yesterday
```

Files (5 total):
- `backend/backtest/engine.py:101`
- `backend/backtest/engine.py` (Gold Macro full portfolio)
- `backend-oil/backtest/engine.py:79`
- `backend-micro/backtest/engine.py:55`
- `backend-oil-micro/backtest/engine.py:347`
- `tests/harness/parity/runner.py:_build_daily_bias`

### 21-year backtest impact

| System | Pre-fix Trades | Pre-fix WR | Pre-fix PF | Pre-fix Net | Pre-fix DD | Post-fix Trades | Post-fix WR | Post-fix PF | Post-fix Net | Post-fix DD |
|---|---|---|---|---|---|---|---|---|---|---|
| Gold Macro | 1,752 | 71.5% | 4.33 | $520,356 | -13.4% | 2,242 | 65.4% | **2.56** | $346,863 | -25.5% |
| Gold Micro | 1,511 | 77.2% | 4.29 | $385,995 | -12.5% | 1,855 | 68.2% | **2.42** | $239,898 | -21.9% |
| Oil Macro | 1,291 | 69.6% | 5.58 | $1,828,136 | -23.2% | 1,605 | 54.2% | **2.64** | $625,996 | -36.9% |
| Oil Micro | 4,150 | 80.0% | 4.93 | $4,598,912 | -18.2% | 4,425 | 69.9% | **2.69** | $2,010,717 | -20.6% |
| **Totals** | **8,704** | — | — | **$7,333,399** | — | **10,127** | — | — | **$3,223,474** | — |

**The buggy backtest reported numbers ~2.3× too rosy across all 4 systems.** Real PF range 2.42–2.69 (was 4.29–5.58); real WR 54–70% (was 70–80%); real max DD up to -37% (was -23%).

### Parity harness improvement (7-day window)

| System | Pre-fix parity | Post-fix parity | Δ |
|---|---|---|---|
| Gold Micro | 60.0% | **79.9%** | +19.9pp |
| Oil Micro | 77.0% | **86.1%** | +9.1pp |
| Gold Macro | 59.9% | **79.9%** | +20.0pp |
| Oil Macro | 57.4% | **74.2%** | +16.8pp |

All 4 systems retained 100% direction agreement on overlaps. **Oil Micro now clears the 85% warning threshold.**

### Caveats

- The post-fix backtest is the AUTHORITATIVE baseline. All previous PF/WR/P&L claims (CLAUDE.md table, conversation references, prior planning docs) were inflated by the bug.
- Even the post-fix numbers may overstate edge slightly (slippage is unseeded; see Filter #11). But they're in the right ballpark.
- The remaining live↔BT parity gap (~15-25%) is largely STRUCTURAL (live polls every M3, BT walks H1) — not strategy-logic drift.

### Verdict

✅ **Keep.** Closes drift bug #6. The new baseline is materially weaker than what was previously believed, but it's the TRUE baseline. Future EDGE_FILTERS measurements ride on top of these post-fix numbers.

### Lessons captured

1. **Trust verifies — for backtests too.** "PF 5.58" was treated as a known fact for weeks. It was wrong by ~2x. Question authoritative numbers when they look unusually clean (54-80% WR, PF 4-6 across all 4 systems was suspicious in retrospect).
2. **Parity harness was right.** It flagged 17 live-only Oil Macro signals over 30 days; investigating those signals (instead of dismissing them as "harness artifact") surfaced this bug. **Always investigate parity gaps; never assume they're noise.**
3. **OANDA timestamp conventions matter.** Live and BT both pass through OANDA data, but they consume it differently. Live uses `daily_candles[-2]` (positional, robust to date-keying issues); BT used `daily_bias[trade_date]` (keyed, brittle to convention). Live was right by accident.

---

## Filter #17 — Oil Macro live `risk<0.01` → `risk<0.3` (rejected — was not a bug)

**Status:** ❌ REVERTED. Originally shipped commit `a5dc3e1` (2026-06-12 morning). Reverted commit `5b1252d` (2026-06-12 afternoon, same day).

**Type:** Was claimed as drift fix; turned out to be incorrect strategy change.

### What happened

The audit on 2026-06-11 listed Filter #17 as the **6th confirmed live↔backtest drift bug**, claiming:
- Oil Macro live: `risk < 0.01`
- Oil Macro backtest: `risk < 0.3`
- Therefore live takes trades backtest never simulates → ship the fix

I shipped the fix on that premise. Production-data analysis seemed to support it (8 trades, +$513 saved, PF 0.63→0.78). I committed and updated docs.

**The audit was wrong.** Verified in this session:

| Path | File | Risk floor (current after revert) |
|---|---|---|
| Gold Macro live | `backend/scanner/scheduler.py:574,601` | 0.3 |
| Gold Macro backtest | `backend/strategies/alpha_sweep.py:111,135` | 0.3 |
| **Oil Macro live** | `backend-oil/scanner/scheduler.py:285,299` | **0.01** |
| **Oil Macro backtest** | `backend-oil/strategies/alpha_sweep.py:121,139` | **0.01** |

Oil Macro has its own parallel `strategies/alpha_sweep.py` (separate from Gold's). Both Oil sides have always been at 0.01. The audit checked only the Gold backtest copy at `backend/strategies/alpha_sweep.py:111` and inferred drift that didn't exist. **Oil live and Oil backtest were already in agreement.**

### 21-year Oil Macro backtest (2006-01-03 → 2026-05-22, ~2M M3 bars)

The honest measurement of whether 0.01 or 0.3 is the right threshold for Oil:

| Metric | risk < 0.01 (current) | risk < 0.3 (Filter #17) | Δ |
|---|---|---|---|
| Trades | 1,291 | 1,194 | -97 |
| Wins | 898 | 788 | -110 |
| Losses | 393 | 406 | +13 |
| Win rate | 69.6% | 66.0% | **-3.6pp** |
| **Profit Factor** | **5.58** | **4.47** | **-1.11** |
| **Net P&L** | **$1,828,136** | **$1,026,805** | **-$801,331 (-44%)** |
| Max DD | -23.2% | -23.2% | 0 |

**The 0.01 threshold is correct for Oil.** The lower floor is consistent with Oil's lower per-unit volatility (`min_sl=0.10` for Oil vs `5.00` for Gold). 97 small-risk trades over 20 years contribute net very positively. Removing them costs $801k of historical edge.

### Production data measurement (revisited)

Original analysis: 8 closed trades, Filter #17 would have skipped 1 (`OIL-AS-f557abc0` -$513.12), producing PF 0.63 → 0.78.

**This measurement was misleading.** N=8 is way too small to dispute a 1,291-trade backtest signal. The production data we have happened to include one losing 0.24-risk trade; the backtest contains hundreds of profitable small-risk trades that never made it to production. **The correct interpretation:** small N can show *anything*; the 21-year backtest is the authoritative answer.

### Parity harness impact

The harness reported parity improved 57.4% → 59.0% (7d) and 64.0% → 64.6% (30d) after Filter #17. **The harness was wrong** because it compared live against the GOLD backtest (`backend.strategies.alpha_sweep`) — but it should have compared against the OIL backtest (`backend-oil/strategies/alpha_sweep`). The harness `oil_macro` system config does point to the right Oil backtest, but the **measurement still went up** because changing live to be MORE restrictive than its real backtest counterpart reduced the "live-only" signal count, which is a bigger weight in the parity_pct formula than entry-price-delta. Coverage improved at the cost of correctness.

This is a **lesson about the parity harness**: parity_pct going up does NOT mean the change is correct. It only means live and backtest agree on more signals. They could be agreeing for the wrong reason (both wrong, or one was correct and the other got artificially constrained).

### Verdict

❌ **Filter #17 was reverted.** The 0.01 risk floor is the correct Oil Macro calibration. The audit's claim of "6th drift bug" was based on a partial code search — only the Gold backtest copy was checked, missing the Oil-specific copy.

### Lessons captured (will be added to memory)

1. **Every "drift bug" audit must enumerate ALL parallel copies before claiming a mismatch.** This codebase has multiple parallel implementations of strategy logic (Gold backtest, Gold live, Oil backtest, Oil live). A claim of "live ≠ backtest" requires checking the right backtest counterpart, not the most familiar one.
2. **Production-data sample sizes (N=8) cannot validate or reject decisions that should be tested against 20 years of history.** Small samples can produce arbitrary signs.
3. **Parity_pct going UP after a code change is NOT proof the change is correct.** Parity is a coverage measurement, not a correctness measurement. A change that reduces live signals will mechanically push parity up if the dominant component is coverage. The 21-year backtest is the correctness check.
4. **Every filter — even "1-line drift fixes" — must run the full backtest.** I bypassed this for Filter #17 thinking it was tautological. It wasn't. The user's "no fake numbers" principle was correct.

---

## Filter #11 — Deterministic slippage (deferred from Phase 0)

**Status:** ⏭️ Deferred to Phase 1.

**Reason:** Empirical run-to-run noise on parity_pct measured at ~0.07pp across three back-to-back gold_micro runs (parity = 0.599078, 0.599364, 0.599710). The "1-3pp noise" claim from `PARITY_HARNESS_EXPLAINED.md` was overstated. At the harness's current 1-decimal display granularity, the noise is invisible. Will be needed when Phase 1 alpha filters require backtest-PF comparison runs.

No action taken; no code change.

---

## Template for future filter results

For each filter measured (whether shipped or rejected):

```markdown
## Filter #N — Title

**Status:** ✅ Shipped / ❌ Rejected / ⏭️ Deferred (commit, date)

**Type:** Drift fix / Alpha filter / Calibration

### What changed
(diff or description)

### Production data (if applicable, prior real trades)
(N trades, P&L delta from real broker outcomes — NEVER as the sole basis for a decision)

### Full historical backtest (REQUIRED for any change to a strategy gate)
| System | Trades | WR | PF | Net P&L | Max DD | Δ vs baseline |
|---|---|---|---|---|---|---|
| (system) | ... | ... | ... | ... | ... | ... |

Run on the full available data span (BCO_USD_M3 = 20+ years for Oil; equivalent for other instruments).
ALWAYS run before AND after the change. Revert the source file after measurement; commit only when ready.

### Parity harness impact
| Window | Pre parity | Post parity | Δ |

Remember: parity_pct going up does NOT prove the change is correct. It's a coverage measurement.

### Caveats
(small N, one-at-a-time gate, missing measurement, anything not quantified)

### Verdict
✅ Keep / ❌ Revert / ⏭️ Recalibrate

### Next action
```

