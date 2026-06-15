# Filter #4 — Anti-Trend-Extension (v2 sweep, 2026-06-15) — STASHED

## Status

**STASHED 2026-06-15.** Aggregate +0.1-0.2% best case = noise, not edge.

This is the **second sweep** of Filter #4. Prior sweep (2026-06-14, branch
`archive-filter-04`) used `anti_trend_threshold` kwarg with ATR_14 H1 and
sweep range {1.5, 2.0, 2.5}, and lost -$462k aggregate at 1.5×.

This v2 sweep uses a different filter shape:
- **Lookback:** 4 hours of H1 bars before sweep_time
- **Move metric:** close-vs-open over the lookback window
- **ATR:** computed in-window from those H1 bars
- **Range:** 0.0 (baseline) / 0.5 / 1.0 / 1.5 / 2.0

Both shapes share the same hypothesis (reject entries when prior move is
in same direction as entry). Both are stashed — confirms the underlying
hypothesis is wrong, not just the parameterization.

## Aggregate by mult

| mult | ΔP&L (21yr, all 4 systems) | % of baseline | Verdict |
|---|---|---|---|
| 0.5 | -$227,164 | -4.7% | 🟡 |
| 1.0 | -$79,257 | -1.7% | 🟡 |
| 1.5 | **+$6,860** | +0.1% | 🟡 noise |
| 2.0 | **+$7,892** | +0.2% | 🟡 noise |

## Per-system

| System | Baseline | mult=0.5 | mult=1.0 | mult=1.5 | mult=2.0 |
|---|---|---|---|---|---|
| Gold Macro | $427,598 | -$36,631 | -$16,373 | -$9,692 | -$1,153 |
| Gold Micro | $361,660 | -$21,890 | -$15,111 | -$2,489 | **+$719** |
| Oil Macro | $825,879 | -$103,265 | -$36,018 | **+$4,341** | +$1,456 |
| Oil Micro | $3,177,780 | -$65,378 | -$11,754 | **+$14,701** | +$6,871 |

## Why stashed

- Best aggregate (mult=2.0) gains +0.2% which is within stochastic variance
- Per-system best (Oil Micro mult=1.5: +$14,701) divided over 21yr = $700/yr
- Selective ship to Oil Macro+Micro at mult=1.5 = +$19k/21yr = $900/yr
- Live-side impl + parity check + per-system config keys cost > the edge gained
- Pattern matches 7 prior signal-pruning filters (#1, #16, #2, #10, #13, #14, #3): high prior of failure

## Pattern confirmation

**Signal-pruning filter score: 0/8 ship rate.** Across two different filter
shapes (#4 ATR_14 H1 close-to-close AND 4h H1 close-vs-open in-window ATR),
both stashed. The H1 sweep's directional bias is sufficient — reducing
signal volume by any "extension" or "freshness" criterion underperforms.

Saving the live-side impl, parity check, and selective per-system config
work — this branch was BT-side only and is preserved on
`archive-filter-04-stashed-v2` if reactivation is ever wanted.

## Files

- Implementation (BT-side only, kwargs `anti_trend_atr_mult` / `anti_trend_lookback_hours`):
  - `backend/strategies/alpha_sweep.py:11+` (`_trend_extended` helper)
  - `backend/strategies/micro_alpha_sweep.py:42+` (`_trend_extended_micro` helper)
  - `backend-oil/strategies/alpha_sweep.py:30+`
  - `backend-oil-micro/backtest/engine.py:71+`
- Engine threading: 4 `run_backtest()` signatures
- Runner: `scripts/run_filter_04.py`
- Output: `scripts/output/filter_04_results.json`

See [[project-edge-filters]] [[project-filter-sweep-workflow]].
