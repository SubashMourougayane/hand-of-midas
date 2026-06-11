# EDGE_FILTERS — Results Log

One row per filter that has been measured. **No filter ships to live without numbers in this file.** No fake numbers, no phantom fills, no assumptions.

For the candidate catalog see [EDGE_FILTERS.md](EDGE_FILTERS.md). For the 6-step gate see [EDGE_FILTERS_IMPLEMENTATION.md](EDGE_FILTERS_IMPLEMENTATION.md).

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

