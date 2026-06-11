# EDGE_FILTERS — Results Log

One row per filter that has been measured. **No filter ships to live without numbers in this file.** No fake numbers, no phantom fills, no assumptions.

For the candidate catalog see [EDGE_FILTERS.md](EDGE_FILTERS.md). For the 6-step gate see [EDGE_FILTERS_IMPLEMENTATION.md](EDGE_FILTERS_IMPLEMENTATION.md).

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

