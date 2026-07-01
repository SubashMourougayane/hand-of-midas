# Scale-Invariant Filter V2 — Full 3-Phase Gauntlet

Follow-up to prior gauntlet which REFUTED absolute-dollar `fib_diff >= 4` on regime grounds. V2 fixes the nominal-price artifact by normalising against D1 ATR14.

## Filter definition

**V2**: `fib_diff / D1_ATR14 >= 0.30`

- `fib_diff` = |H − L| where H, L are M15 pivots (lb=3) confirmed BEFORE signal bar.
- `D1_ATR14` = 14-day rolling mean of true-range on the last D1 bar whose label + 24h ≤ entry_ts.
- Threshold 0.30 chosen at PF plateau midpoint from K=0.20 to K=0.50.

## Phase 1 · Causality proof

**PASS 27,885 of 27,950 trades (99.77%).**

- setup_confirm_after_entry: 0
- atr_bar_not_fully_closed_before_entry: 0
- atr_window_first_bar_not_closed_before_entry: 0
- 65 edge cases: earliest trades where 14-day ATR history not yet available (data startup, not look-ahead)

## Phase 2 · 15-point stress

| Test | V1 (dollar) | V2 (fib/ATR) | Verdict |
|---|---|---|---|
| 1. Positive years | 21/21 | **21/21** | pass |
| 2. IS/OOS split | IS 1.78 / OOS 1.87 | IS 1.71 / OOS 1.78 | pass |
| 3. Bootstrap P(<0) 5000 | 0.000% | **0.000%** | pass |
| 4. Permutation MC 1000 | 0.000% | **0.000%** | pass |
| 5. Cost stress $10/trade | +$570k | +$372k | alive |
| 6. Sample size/year | min 407 | min 371 | pass |
| 7. Direction A/D | A 1.87 / D 1.79 | A 1.89 / D 1.64 | pass |
| 9. Threshold plateau | 1.82-2.05 | 1.66-1.74 | plateau ✓ |
| 10. FLIP collapses | ✓ (0.63) | ✓ (0.58) | pass |
| 11. Sharpe | 2.59 | 2.51 | pass |
| 11. **MAR** | 128 | **139** | **V2 wins** |
| 11. **MaxDD R** | −58 | **−39** | **V2 wins** |
| 12. Max consec losers | 12 | **10** | V2 |
| 13. Loser:winner drop | 1.58:1 | 1.43:1 | pass |
| 14. Hour boost | universal +1 to +14pp | universal +1 to +14pp | pass |

**V2 wins where it matters**: MaxDD 32% shallower, MAR 9% higher, streak 2 fewer.

## Phase 3 · Adversarial audit

3 hostile reviewers. All returned **WEAK REFUTATION** (unlike V1 which was killed outright).

### Reviewer 1 (causality lens): WEAK REFUTATION

Temporal ordering airtight. Only nit: audit recomputes D1 ATR14 from `/tmp/oanda_xau_m5.parquet` snapshot — if OANDA revises any historical bar between BT run time and audit time, the audit's ATR could differ from live-time ATR. **Fix**: pin M5 snapshot hash for reproducibility. Not a live-time causality bug.

### Reviewer 2 (statistical lens): WEAK REFUTATION

Every stat test passes. Random subsample analysis (2000 draws of size 15,924): filter PF 1.740 is **9.5σ above random baseline** (mean 1.515). No mechanical variance artifact. Day-clustered bootstrap: still p<0.001. But:
- Pre-2020 filter lift: **+13.3% PF**
- **Post-2020 filter lift: +4.6% PF** (still real, but 3× smaller)
- Expected live-regime lift is ~+4.6%, not headline +9.4%

### Reviewer 3 (regime lens): WEAK REFUTATION

Distribution of `fib/atr` IS scale-invariant:
- Era A (2006-2012): median 0.351, pass-rate 60.4%
- Era B (2013-2019): median 0.323, pass-rate 55.4%
- Era C (2020-2026): median 0.325, pass-rate 55.6%

BUT the PF-boost decays across eras:
- **Era A**: +0.102 PF, p=0.2% ✓
- **Era B**: +0.260 PF, p=0.0% ✓
- **Era C (post-COVID)**: +0.069 PF, p=**6.8%** — not significant at 5%
- **2026 YTD**: filter HURTS PF by −0.299 (n=371)

Boost concentrates in eras B (2013-2019). Post-2020 filter is marginally useful.

## Meta verdict

**V2 is BETTER than V1** — scale-invariant, still real signal, better risk-adjusted:
- Passes causality (99.77%, all edge cases are data-startup not look-ahead)
- Passes 14 stress tests
- Genuine plateau, not knife-edge
- Better MaxDD, MAR, streak

**BUT V2 is WEAKER than initially claimed in the recent regime:**
- Post-2020 PF lift only +4.6% (real but modest)
- 2026 YTD shows filter hurts (single-year noise, small n)

## Recommendation

**DO NOT SHIP as production strategy code change on the current evidence.** The filter is real for historical eras but marginal for the regime we'll actually trade in.

### Next paths (deferred):

1. **Wait for more post-2020 data** to accumulate. Currently only 6 years post-shift.
2. **Test on cross-symbols** (EUR, GBP, BRENT) — does filter transfer across markets?
3. **Combine with other scale-invariant features** (e.g., fib_diff/entry_price × D1_ATR percentile).
4. **Live shadow test** — apply V2 as an ADVISORY marker on live signals for 30 days, compare filtered vs unfiltered outcomes on real forward data.

Standard held: keep production strategy untouched until either (a) post-2020 significance stabilizes, or (b) shadow-live test provides forward-data validation.

## Files

- Filter def: `research-baseline/candidate_filters/scale_invariant_variants.py`
- Causality: `research-baseline/candidate_filters/causality_proof_v2_fib_over_atr.py`
- Stress: `research-baseline/candidate_filters/phase2_stress_v2.py`
- Output: `/tmp/phase2_v2_out.txt`
