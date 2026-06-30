# EMA8 + Stack24h + NY/Overlap Causality Stress

Generated: 2026-06-29

No production code was changed. This recomputes `same_dir_intraday_overlap_24h` from the raw intraday zone universe and tests stricter time-availability variants.

## Stack Definition Audit

Source definition counts same-direction overlapping intraday zones with `created_timestamp` in `[entry - 24h, entry]`, excluding the current zone id/spec. This is available by entry time. It does not use trade outcome.

Potential subtlety: zones created after the original zone but before entry are included. That is causal at entry, but not known at zone creation. For live entry filtering, entry-time availability is acceptable; for zone-time filtering, it is not.

## Recalculation Check

- Candidate pre-stack rows (`ema8_aligned + ny_main_or_overlap`): 3,516
- Matrix stack true: 2,936
- Recomputed entry-time stack true: 2,936
- Matrix vs recomputed boolean mismatches: 0
- Matrix vs recomputed count mismatches: 0
- Strict `< entry` stack true: 2,916
- Known by touch stack true: 2,915
- Known by original zone creation stack true: 2,724

## Variant Metrics

| Variant | Trades | Net R | R/yr | WR | PF | DD | MAR | Years | Months |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `matrix_intraday_stack_24h` | 2,936 | +382.56 | +54.35 | 59.7% | 1.31 | -18.01 | 3.02 | 8/8 | 63/85 |
| `recalc_entry_right_ge1` | 2,936 | +382.56 | +54.35 | 59.7% | 1.31 | -18.01 | 3.02 | 8/8 | 63/85 |
| `strict_entry_left_ge1` | 2,916 | +377.39 | +53.61 | 59.6% | 1.31 | -18.01 | 2.98 | 8/8 | 63/85 |
| `known_by_touch_ge1` | 2,915 | +374.64 | +53.22 | 59.6% | 1.30 | -18.88 | 2.82 | 8/8 | 63/85 |
| `known_by_zone_creation_ge1` | 2,724 | +328.72 | +46.70 | 59.2% | 1.28 | -17.62 | 2.65 | 8/8 | 62/85 |

## 5k Monthly Reset PnL

| Variant | Risk | Total PnL | Positive Months | Worst Month | Worst DD |
|---|---:|---:|---:|---:|---:|
| `matrix_intraday_stack_24h` | 1% | $19,725.04 | 63/85 | $-426.26 | $-598.26 |
| `matrix_intraday_stack_24h` | 2% | $40,730.36 | 63/85 | $-835.54 | $-1,178.60 |
| `matrix_intraday_stack_24h` | 3% | $63,154.55 | 63/85 | $-1,225.87 | $-1,738.62 |
| `matrix_intraday_stack_24h` | 4% | $87,148.83 | 62/85 | $-1,595.72 | $-2,335.06 |
| `matrix_intraday_stack_24h` | 5% | $112,877.83 | 59/85 | $-1,943.90 | $-3,104.52 |
| `recalc_entry_right_ge1` | 1% | $19,725.04 | 63/85 | $-426.26 | $-598.26 |
| `recalc_entry_right_ge1` | 2% | $40,730.36 | 63/85 | $-835.54 | $-1,178.60 |
| `recalc_entry_right_ge1` | 3% | $63,154.55 | 63/85 | $-1,225.87 | $-1,738.62 |
| `recalc_entry_right_ge1` | 4% | $87,148.83 | 62/85 | $-1,595.72 | $-2,335.06 |
| `recalc_entry_right_ge1` | 5% | $112,877.83 | 59/85 | $-1,943.90 | $-3,104.52 |
| `strict_entry_left_ge1` | 1% | $19,443.13 | 63/85 | $-426.26 | $-598.26 |
| `strict_entry_left_ge1` | 2% | $40,117.68 | 63/85 | $-835.54 | $-1,178.60 |
| `strict_entry_left_ge1` | 3% | $62,159.01 | 63/85 | $-1,225.87 | $-1,738.62 |
| `strict_entry_left_ge1` | 4% | $85,715.19 | 62/85 | $-1,595.72 | $-2,335.06 |
| `strict_entry_left_ge1` | 5% | $110,947.64 | 59/85 | $-1,943.90 | $-3,104.52 |
| `known_by_touch_ge1` | 1% | $19,299.84 | 63/85 | $-426.26 | $-598.26 |
| `known_by_touch_ge1` | 2% | $39,818.89 | 63/85 | $-835.54 | $-1,178.60 |
| `known_by_touch_ge1` | 3% | $61,691.54 | 63/85 | $-1,225.87 | $-1,738.62 |
| `known_by_touch_ge1` | 4% | $85,064.96 | 62/85 | $-1,595.72 | $-2,335.06 |
| `known_by_touch_ge1` | 5% | $110,099.83 | 60/85 | $-1,943.90 | $-3,104.52 |
| `known_by_zone_creation_ge1` | 1% | $16,878.50 | 61/85 | $-413.44 | $-520.27 |
| `known_by_zone_creation_ge1` | 2% | $34,705.92 | 59/85 | $-810.43 | $-1,019.41 |
| `known_by_zone_creation_ge1` | 3% | $53,584.82 | 59/85 | $-1,189.34 | $-1,496.81 |
| `known_by_zone_creation_ge1` | 4% | $73,626.37 | 58/85 | $-1,548.86 | $-1,952.13 |
| `known_by_zone_creation_ge1` | 5% | $94,950.71 | 56/85 | $-1,888.01 | $-2,571.59 |

## Verdict

The `intraday_stack_24h` feature passes this entry-time recomputation check: the matrix matches independent reconstruction from raw zones.

Important nuance:

- Entry-time stack is causal for a live entry filter.
- Touch-time stack is stricter and still preserves most of the result if similar.
- Zone-creation-time stack is much stricter and is only required if we want to decide zone eligibility at creation time rather than at entry.

Remaining live caveat: this validates stack timing, not the full event-generation pipeline. Next clean gate is raw-bar replay parity for the whole candidate.