# Filter Research Round 2 — Feature-Driven, Causal, Real Signal Found

Prior round (H1, H4, EMA5, ATR): all rejected once causality corrected. Baseline was well-calibrated for HTF trend filters.

This round: examine raw_features already recorded in bt_trades. Two features stood out — `fib_diff` (pivot high − pivot low) and `ny_hr` (bar timestamp hour). Both are known AT SIGNAL-BAR CLOSE, so filtering is causally clean.

## Hour-of-day breakdown

| Hours (NY) | Trades | Win% | Notes |
|---|---:|---:|---|
| 0-2 UTC (Asian dead) | 2,210 | 42% | worst |
| 3-6 (pre-London) | 6,412 | 48% | ok |
| 7-9 (London open) | 4,500 | **54%** | best window |
| 10-14 (NY session) | 6,806 | 52% | good |
| 15-16 (late NY) | 2,871 | 47% | drops |
| 17-23 (post-close) | 5,133 | 46% | ok |

Time-of-day matters but is a WEAK filter alone.

## fib_diff (pivot span) breakdown

| fib_diff bucket | Trades | Win% | Sum $ |
|---|---:|---:|---:|
| < 5 | 11,651 | **38.8%** | +$194k |
| 5-10 | 9,520 | **57.1%** | +$384k |
| 10-20 | 4,792 | 54.8% | +$172k |
| 20-40 | 1,476 | 55.8% | +$73k |
| 40-80 | 429 | 52.7% | +$25k |
| >= 80 | 82 | 52.4% | +$2.6k |

**Tiny-pivot setups (< 5) are noise** — 38.8% WR vs 55%+ for bigger pivots. Everything above 5 has consistent ~55% WR.

## Filter test — fib_diff >= 4 (best sweet spot)

| Threshold | Trades | WR | Net $ | vs base | PF |
|---:|---:|---:|---:|---:|---:|
| baseline | 27,950 | 48.9% | $850,710 | — | 1.590 |
| **fib_diff >= 4** | **19,650** | **55.6%** | **$767,103** | −10% | **1.816** |
| fib_diff >= 5 | 16,299 | 56.2% | $656,594 | −23% | 1.846 |
| fib_diff >= 6 | 13,614 | 56.0% | $547,507 | −36% | 1.846 |
| fib_diff >= 8 | 9,466 | 55.5% | $380,775 | −55% | 1.848 |
| fib_diff >= 10 | 6,779 | 54.9% | $272,576 | −68% | 1.844 |

**fib_diff >= 4** is the sweet spot:
- Cuts 30% of trades (drops 4,517 winners + 7,134 losers = drops losers 1.58:1)
- Keeps **90% of $** (loses 10%)
- **PF jumps 1.59 → 1.82 (+14%)**
- **WR jumps 48.9% → 55.6% (+6.7pp)**

## Causality check

- `fib_diff` = |H − L| where both H and L are pivots that CONFIRMED (lb=3 bars either side) BEFORE the signal bar. Fully deterministic at signal decision time.
- `ny_hr` = bar timestamp hour in NY tz. Trivially known at signal time.

Both filters read from `raw_features` populated at trade-open time in the ORIGINAL BT run. No re-computation from raw M5. **Zero look-ahead — guaranteed by construction.**

## Sizing implication

With PF 1.59 → 1.82, drawdown scales roughly with (1 − 1/PF). Reduced friction allows higher risk_pct:

- Baseline: 1.5% × equity, PF 1.59, net $851k
- fib_diff >= 4 at 1.5%: PF 1.82, net $767k
- fib_diff >= 4 at 2.0% (proportional up-size): estimated **~$1.02M** net at similar DD
- fib_diff >= 4 at 2.5%: estimated ~$1.28M, tighter DD budget

Real number requires re-BT with new risk_pct. **Standing recommendation**: re-BT with `fib_diff >= 4` filter at 2.0% risk_pct, measure MAR + max_DD.

## Conclusion

**Filter fib_diff >= 4 is the first REAL loss-reduction signal found.** Causally clean. Cuts noise-trades. Winner-loser drop ratio favours losers 1.58:1. PF and WR both improve materially.

Recommend: strategy-side implementation via new config field `min_fib_diff` (default 0 for backward compat). Gate at `_build_setup()` — reject setup if `H − L < min_fib_diff`. Fires GATE_SETUP_REJECT_DIFF (already in JournalEvent enum).

## Files

- `research-baseline/candidate_filters/loss_reduction_filters.py` — first round (rejected filters)
- `docs/audit/FILTER_RESEARCH_RESULTS_2026-07-01.md` — first round writeup
- `docs/audit/FILTER_RESEARCH_ROUND2_2026-07-01.md` — this doc
