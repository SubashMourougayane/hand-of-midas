# L105 Combo Walk-Forward Validation

Objective: validate the combined SupplyDemand + cross-asset add-on without hindsight. The base is fixed; train years select the add-on variant; test years are then evaluated untouched.

## Selection Rules

- Train only: choose add-on by train `avg_r_year` after gates.
- Gates: enough trades, WR in requested band, PF in requested band, at most one negative train year, max train drawdown no worse than `-25R`.
- Test metrics are never used for selection.
- Add-on trades are de-duplicated against the base by asset, side, and 15-minute entry bucket, with base priority.

## Path Summary

| Path | Trades | R/year | WR | PF | Max DD R | Pos Years | Risk/R for 30K | Risk/R for 100K | PnL/year @ $1000R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top10_stretch__all_cost_models_sanity__expanding | 1286 | 56.21 | 64.15% | 1.63 | -10.16 | 5/5 | $534 | $1,779 | $56,208 |
| top10_stretch__all_cost_models_sanity__rolling | 1286 | 56.21 | 64.15% | 1.63 | -10.16 | 5/5 | $534 | $1,779 | $56,208 |
| top10_stretch__fixed_fee_stretch__expanding | 1286 | 55.96 | 64.00% | 1.63 | -10.28 | 5/5 | $536 | $1,787 | $55,955 |
| top10_stretch__fixed_fee_stretch__rolling | 1286 | 55.96 | 64.00% | 1.63 | -10.28 | 5/5 | $536 | $1,787 | $55,955 |
| top10_stretch__preferred_realistic_units__expanding | 1286 | 55.17 | 62.67% | 1.61 | -10.64 | 5/5 | $544 | $1,813 | $55,168 |
| top10_stretch__preferred_realistic_units__rolling | 1286 | 55.17 | 62.67% | 1.61 | -10.64 | 5/5 | $544 | $1,813 | $55,168 |
| clean_top3__all_cost_models_sanity__expanding | 982 | 52.27 | 67.11% | 1.86 | -13.53 | 5/5 | $574 | $1,913 | $52,270 |
| clean_top3__all_cost_models_sanity__rolling | 982 | 52.27 | 67.11% | 1.86 | -13.53 | 5/5 | $574 | $1,913 | $52,270 |
| clean_top3__fixed_fee_stretch__expanding | 982 | 52.02 | 66.90% | 1.85 | -13.65 | 5/5 | $577 | $1,922 | $52,017 |
| clean_top3__fixed_fee_stretch__rolling | 982 | 52.02 | 66.90% | 1.85 | -13.65 | 5/5 | $577 | $1,922 | $52,017 |
| clean_top3__preferred_realistic_units__rolling | 947 | 48.81 | 64.94% | 1.80 | -14.00 | 5/5 | $615 | $2,049 | $48,811 |
| clean_top3__preferred_realistic_units__expanding | 818 | 43.39 | 64.67% | 1.75 | -12.69 | 5/5 | $691 | $2,305 | $43,393 |

## Monte Carlo

| Path | Net R | Median DD R | 5% DD R | 1% DD R |
|---|---:|---:|---:|---:|
| top10_stretch__all_cost_models_sanity__expanding | 281.04 | -10.13 | -15.10 | -18.47 |
| top10_stretch__all_cost_models_sanity__rolling | 281.04 | -10.05 | -14.89 | -17.75 |
| top10_stretch__fixed_fee_stretch__expanding | 279.78 | -10.19 | -14.81 | -17.85 |
| top10_stretch__fixed_fee_stretch__rolling | 279.78 | -10.19 | -15.31 | -18.42 |
| top10_stretch__preferred_realistic_units__expanding | 275.84 | -10.23 | -15.45 | -17.99 |
| top10_stretch__preferred_realistic_units__rolling | 275.84 | -10.29 | -15.41 | -18.51 |

## Verdict

Best walk-forward path: `top10_stretch__all_cost_models_sanity__expanding` with `56.21R/year`, WR `64.15%`, PF `1.63`. At `$1,000/R`, this is `$56,208/year`; it needs about `$1,779/R` for `$100k/year`.

This is stronger evidence than the L104 full-period combo, but it is still not a small-account `$100k/year` solution. It supports a `30k+` yearly target around `$1,000/R`, and a `$100k/year` target only around the `$2.5k/R` risk level.

## Files

- Selection detail: `/Users/subash/Documents/QUANT/SupplyDemand/research/l105_combo_walk_forward_validation/l105_walk_forward_selection.csv`
- Path summary: `/Users/subash/Documents/QUANT/SupplyDemand/research/l105_combo_walk_forward_validation/l105_walk_forward_path_summary.csv`
- Selected OOS test trades: `/Users/subash/Documents/QUANT/SupplyDemand/research/l105_combo_walk_forward_validation/l105_walk_forward_selected_test_trades.csv`
- Monte Carlo: `/Users/subash/Documents/QUANT/SupplyDemand/research/l105_combo_walk_forward_validation/l105_walk_forward_monte_carlo_summary.csv`