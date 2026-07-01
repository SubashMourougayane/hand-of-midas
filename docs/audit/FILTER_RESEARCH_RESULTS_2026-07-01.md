# Loss-Reduction Filter Research — Post-Hoc

Baseline BT: fib_v2_intraday_a_plus_d (run `b6604240-14f4-464f-86b4-0d0e32755838`), 27,950 trades over 22 years XAU, Model B 1.5% sizing.

**Approach**: post-hoc filter on existing trade ledger. NO strategy code changes. For each trade:
1. Look up its entry_timestamp
2. Compute filter value from bars STRICTLY BEFORE that timestamp (causal, no look-ahead)
3. Accept/reject the trade
4. Recompute headline over the surviving subset

Zero look-ahead. No re-BT. Standalone script: `research-baseline/candidate_filters/loss_reduction_filters.py`.

## Critical causality fix (2026-07-01)

**Initial H1 result was CONTAMINATED by look-ahead.** Fixed for all HTF filters.

Issue: `resample('1h', label='left', closed='left')` produces bars labeled by their OPEN time. An H1 bar labeled `12:00` covers `12:00 → 12:59:59`; it **closes at 13:00**, not at 12:00.

Original filter: `keep if h1_ts < entry_ts` — at entry `12:30`, this picks bar labeled `12:00` which is **still forming** (contains 12:00-12:29 already, will contain the M15 bar the trade is entering into at 12:30). That's look-ahead.

Fixed filter: `keep if h1_label + 1h <= entry_ts` — requires bar to be FULLY CLOSED. At entry `12:30`, the last fully-closed H1 bar is `11:00` (which finalised at 12:00).

Same fix applied to H4 (label + 4h ≤ entry) and D1 ATR (label + 24h ≤ entry).

## Results (CAUSAL — post-fix)

| Filter | Trades | WR | Net $ | vs base | PF | MaxDD R |
|---|---:|---:|---:|---:|---:|---:|
| **BASELINE** | 27,950 | 48.92% | **+$850,710** | — | 1.590 | −73.0R |
| A · momentum EMA5 slope aligned | 4,952 | 48.28% | +$141,258 | −83% | 1.551 | −57R |
| B · ATR14 < 0.5× 20d median (skip) | 27,913 | 48.92% | +$847,008 | −0.4% | 1.590 | −73R |
| C · H1 last-closed body aligned | 7,219 | 48.82% | +$219,541 | −74% | 1.583 | −66R |
| D · H4 last-closed body aligned | 14,708 | 49.92% | +$458,550 | −46% | 1.614 | −89R |
| C+D (both H1 & H4 aligned) | 3,685 | 50.28% | +$93,069 | −89% | 1.493 | −60R |
| C ∨ D (either aligned) | 18,242 | 49.41% | +$585,022 | −31% | 1.626 | −73R |
| A+B+C+D (all four) | 1,327 | 51.32% | +$38,391 | −95% | 1.601 | −35R |

## Verdict — all four filters REJECTED

None materially improve PF or reduce drawdown once causality is respected. Every filter cuts winners in nearly 1:1 ratio with losers.

### Why the prior H1 "signal" was fake

Before the fix, the H1 body being "aligned" was reading the **currently-forming** hour — which contains bars that overlap the actual entry decision. That in-progress bar's OHLC is influenced by the near-entry M15 bars, which are correlated with the trade's outcome. Look-ahead.

With causality corrected (bar must be FULLY CLOSED before entry_ts), the H1 body direction over the PRIOR hour has no predictive power for the mean-reversion strategy's next M15 setup.

### Filter-by-filter causality proof

- **A · momentum EMA5**: uses M15 closes at `t-5×15min` and `t-1×15min` where t=entry_ts. Both bars have closed by t. Causal ✓
- **B · ATR compression**: uses D1 bar with `label + 24h ≤ entry_ts`. Causal ✓
- **C · H1 confluence**: uses H1 bar with `label + 1h ≤ entry_ts`. Causal ✓
- **D · H4 confluence**: uses H4 bar with `label + 4h ≤ entry_ts`. Causal ✓

## Conclusion

**Baseline strategy is well-calibrated already.** The 97% full-SL-loss pattern (see LOSS_REDUCTION_ANALYSIS_2026-07-01.md) is **structural**, not filterable via simple HTF trend/momentum/vol proxies.

Real loss-reduction paths (deferred):
1. Refine the ENTRY signal itself (candle patterns, retrace depth) rather than bolt-on HTF filters
2. Volatility-scaled position sizing (not just 1.5% × equity)
3. Correlation break between winners/losers (do losers cluster by hour/day/regime?)
4. Sharpe-optimising sizing (Kelly-fraction of realised WR × avg-R)

None of these are quick post-hoc filters. Each requires a strategy-code experiment behind proper parity guards.

**No production changes recommended.** Strategy stays as-is.

## Follow-up work if pursued

- Cluster losers by session hour → maybe session-filter modification
- Cluster losers by regime → maybe regime-tier ordering
- Look for consecutive-loss streaks correlated with observable state → skip-N-after-loss filter
