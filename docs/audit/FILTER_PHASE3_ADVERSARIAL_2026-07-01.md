# Phase 3 — Adversarial Audit on fib_diff Filter

3 independent hostile reviewers, distinct lenses. Each attempts to REFUTE.

## Reviewer 1 — Causality / look-ahead lens

**Verdict: NO REFUTATION FOUND**

Read the code + audit + docs. Traced `fib_diff` from PivotTracker emission through `_build_setup` through `_finalize_entry` through DB `raw_features`. Confirmed: pivots require `bar[i+lb]` closed before emission, `fib_H`/`fib_L` frozen at build time, no mutation, no future-bar peek.

Caveats raised (not causality):
- `cost_r = cost_usd / risk_units` scales inversely with `risk`. Small `fib_diff` → tiny `risk_units` → cost_r explodes → net_r crashes. Part of the 38.8% WR for tiny-pivot bucket is **cost-model artifact**, not market alpha.
- K=4 chosen after sweep across K=1..20 → mild post-hoc selection risk.

## Reviewer 2 — Sample size / statistical robustness lens

**Verdict: NO REFUTATION FOUND**

Observed statistic sits ~21σ above permutation null. Even with:
- Bonferroni across 11 threshold values
- 10× effective-N deflation for trade dependency
- OOS re-validation on top

...significance survives. Statistical case rock solid.

## Reviewer 3 — Regime concentration lens — **REFUTED**

**Verdict: REFUTED**

XAU rose 8× over the 22-year run ($500 → $4000). `fib_diff` measured in **absolute dollars**. So K=4 threshold behaves radically differently per era:

| Era | Trades passing K≥4 | Median fib_diff |
|---|---:|---:|
| 2006-2012 | 68.1% | $5.55 |
| 2013-2019 | 57.4% | $4.47 |
| **2020-2026** | 87.4% | $9.07 |
| 2025 | 98.8% | $16.47 |
| **2026** | **100.0%** | $35.05 |

The filter **is a no-op in the last 3 years**. Yet Phase 2 gave it credit for the 22-year edge.

Era-decomposition of PF boost:

| Era | Base PF | Filt PF | pct dropped |
|---|---:|---:|---:|
| Pre-2020 | 1.504 | 1.767 | 37.7% |
| Post-2020 | 1.771 | 1.885 | 12.6% |

The "filter boost" is really: hard work in the cheap-XAU era where noise dominated, essentially free-riding on already-strong PF in expensive-XAU era.

### Within-year quintile analysis (real signal)

Rank fib_diff WITHIN year (removes nominal-drift):

| Quintile | PF |
|---:|---:|
| Q1 (lowest) | **1.17** |
| Q2 | 1.70 |
| Q3 | 1.72 |
| Q4 | 1.74 |
| Q5 (highest) | 1.77 |

**The edge is Q1-vs-rest, not graded across all quintiles.**
Cutting bottom 20% within-year captures the actual "noise tier" without the nominal-price artifact.

## Meta verdict — FILTER REJECTED IN CURRENT FORM

The `fib_diff >= 4` filter, as tested, exploits a **nominal-price scale artifact**. It:
- Kills noise-tier trades in early years (good)
- Turns into a no-op in recent years (bad — no protection when we need it)
- Correlated with era, not with per-trade quality after normalising for XAU price level

## Real path forward

Use a **scale-invariant** version of the noise-cutoff:

1. **Relative filter**: `fib_diff / entry_price > threshold_pct` (e.g. 0.1%)
2. **ATR-normalized**: `fib_diff / D1_ATR14 > threshold` (per-vol filter)
3. **Within-year quantile**: `fib_diff > 20th_percentile_of_year` (rank-based)

Any of these should preserve the noise-cutoff signal AND survive across price regimes.

Rerun Phase 2 stress on a normalized-threshold variant before accepting.

## Overall verdict — RESEARCH INCOMPLETE

- Causality: ✓ Clean
- Statistical significance: ✓ Robust
- **Regime robustness: ✗ FAIL** (Reviewer 3)

**No production strategy code change.** Rerun with normalized threshold before implementation.
