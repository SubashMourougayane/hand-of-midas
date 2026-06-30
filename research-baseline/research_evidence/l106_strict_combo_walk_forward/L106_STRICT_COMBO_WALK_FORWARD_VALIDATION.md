# L106 Strict Combo Walk-Forward Validation

Strict rerun of L105. If no add-on passes train gates, the selector falls back to base-only. This removes the loose best-ineligible selection path.

## Path Summary

| Path | Trades | R/year | WR | PF | Max DD R | Pos Years | Risk/R for 30K | Risk/R for 100K | @ $1000/R | @ $2000/R | @ $2050/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top10_stretch__fixed_fee_stretch__rolling_strict | 1251 | 53.35 | 63.39% | 1.60 | -10.28 | 5/5 | $562 | $1,874 | $53,350 | $106,700 | $109,367 |
| top10_stretch__fixed_fee_stretch__expanding_strict | 1220 | 52.17 | 63.20% | 1.59 | -10.40 | 5/5 | $575 | $1,917 | $52,172 | $104,344 | $106,953 |
| clean_top3__fixed_fee_stretch__expanding_strict | 982 | 52.02 | 66.90% | 1.85 | -13.65 | 5/5 | $577 | $1,922 | $52,017 | $104,034 | $106,635 |
| clean_top3__fixed_fee_stretch__rolling_strict | 982 | 52.02 | 66.90% | 1.85 | -13.65 | 5/5 | $577 | $1,922 | $52,017 | $104,034 | $106,635 |
| top10_stretch__preferred_realistic_units__rolling_strict | 1180 | 50.32 | 62.12% | 1.58 | -9.52 | 5/5 | $596 | $1,987 | $50,319 | $100,638 | $103,153 |
| clean_top3__preferred_realistic_units__rolling_strict | 907 | 47.39 | 64.39% | 1.79 | -12.94 | 5/5 | $633 | $2,110 | $47,390 | $94,779 | $97,149 |
| top10_stretch__preferred_realistic_units__expanding_strict | 1122 | 47.33 | 61.94% | 1.55 | -9.52 | 5/5 | $634 | $2,113 | $47,331 | $94,663 | $97,029 |
| clean_top3__preferred_realistic_units__expanding_strict | 818 | 43.39 | 64.67% | 1.75 | -12.69 | 5/5 | $691 | $2,305 | $43,393 | $86,786 | $88,956 |

## Recommended Path

Recommended clean path: `clean_top3__preferred_realistic_units__rolling_strict`. It produces `47.39R/year`, WR `64.39%`, PF `1.79`, max DD `-12.94R`, and `5/5` positive OOS years. At `$1,000/R`, that is `$47,390/year`; at `$2,050/R`, it is `$97,149/year`.

## Monte Carlo

| Path | Net R | Median DD R | 5% DD R | 1% DD R |
|---|---:|---:|---:|---:|
| clean_top3__fixed_fee_stretch__expanding_strict | 260.08 | -8.16 | -11.81 | -14.30 |
| clean_top3__fixed_fee_stretch__rolling_strict | 260.08 | -8.14 | -11.77 | -14.31 |
| clean_top3__preferred_realistic_units__rolling_strict | 236.95 | -8.35 | -12.57 | -15.25 |
| top10_stretch__fixed_fee_stretch__expanding_strict | 260.86 | -10.36 | -15.12 | -18.13 |
| top10_stretch__fixed_fee_stretch__rolling_strict | 266.75 | -10.36 | -15.28 | -18.72 |
| top10_stretch__preferred_realistic_units__rolling_strict | 251.59 | -10.42 | -15.48 | -19.01 |

## Files

- Selection: `/Users/subash/Documents/QUANT/SupplyDemand/research/l106_strict_combo_walk_forward/l106_strict_walk_forward_selection.csv`
- Path summary: `/Users/subash/Documents/QUANT/SupplyDemand/research/l106_strict_combo_walk_forward/l106_strict_walk_forward_path_summary.csv`
- Selected test trades: `/Users/subash/Documents/QUANT/SupplyDemand/research/l106_strict_combo_walk_forward/l106_strict_walk_forward_selected_test_trades.csv`
- Monte Carlo: `/Users/subash/Documents/QUANT/SupplyDemand/research/l106_strict_combo_walk_forward/l106_strict_walk_forward_monte_carlo_summary.csv`