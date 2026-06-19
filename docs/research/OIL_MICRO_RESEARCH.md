# Oil Micro Alpha-Sweep Research — May 29, 2026

## Summary

Running the same Micro rolling 4hr logic (from Gold Micro) on Oil (BCO/USD) with scaled parameters produces **better results than Gold** on every metric.

## Parameters (scaled 15.2x from Gold)

| Param | Gold | Oil | Scaling |
|-------|------|-----|---------|
| asia_min_range | $5.00 | $0.33 | 15.2x |
| sweep_threshold | $2.00 | $0.13 | 15.2x |
| sl_buffer | $2.00 | $0.13 | 15.2x |
| min_sl | $5.00 | $0.33 | 15.2x |
| tp_multiplier | 2.0 | 2.0 | same |
| max_bars | 80 | 80 | same |
| engulfing_window | 0.75hr | 0.75hr | same |
| max_units | 100 | 1000 | Oil = smaller per-unit |

**Scaling basis:** Gold 4hr mean range = $15.71, Oil = $1.04. Ratio = 15.2x.

## Results (2020-2026, $5K capital, 4% risk)

| Metric | Gold Micro | Oil Micro | Oil Macro (current) |
|--------|-----------|-----------|---------------------|
| Trades | 1,051 | **1,287** | ~400 |
| WR | 67.3% | **69.4%** | ~65% |
| PF | 3.97 | **4.37** | ~3.5 |
| P&L | $439K | **$468K** | ~$180K |
| Max DD | -24.0% | **-20.4%** | ~-25% |
| Losing years | 0 | **0** | 0 |

## Year-by-Year

| Year | Trades | WR | PF | P&L | DD |
|------|--------|-----|-----|-----|-----|
| 2020 | 174 | 70.7% | 5.06 | $47,077 | -11.7% |
| 2021 | 209 | 71.3% | 4.40 | $61,975 | -11.3% |
| 2022 | 255 | 63.1% | 3.91 | $130,027 | -11.5% |
| 2023 | 231 | 72.7% | 5.48 | $93,557 | -7.9% |
| 2024 | 188 | 71.3% | 4.63 | $61,717 | -8.0% |
| 2025 | 145 | 73.8% | 4.93 | $43,049 | -5.1% |
| 2026 | 85 | 60.0% | 2.97 | $31,321 | -20.4% |

## Code Path (verified)

- Signal gen: `backend/strategies/micro_alpha_sweep.generate_signals(oil_h1, oil_m3, daily_bias)`
- Fill model: `backend/execution/fill_model.execute_trade()` on `oil_m3`
- DD protection: same DDState, same get_risk_multiplier, same $400 daily max
- One-at-a-time: enforced
- 5-min cooldown: enforced
- No phantom fills — same fill model as Gold

## Why Oil Works Better

1. **More consistent consolidation ranges** — Oil's 4hr ranges are tighter relative to moves (less noise)
2. **Cleaner sweeps** — Oil liquidity grabs reverse more reliably than Gold
3. **Lower DD** — Oil's moves are more proportional (fewer $50+ spikes that destroy Gold positions)
4. **More opportunities** — 1,287 vs 1,051 trades despite same logic

## Implementation Notes (for when we build it)

- Same architecture as `backend-micro/` (port 5056?)
- Instrument: BCO_USD
- All dollar-value params need Oil scaling (divide Gold by 15.2)
- Oil daily CSV has `open/high/low/close` columns (not bid/ask) — need mapping in data loader
- Oil M3 has bid/ask (standard format) — works directly
- Max units should be 1000 (Oil lots are smaller per-unit value than Gold)
- Oil market close: different hours than Gold? Need to verify

## Decision

**Not building now.** Current Oil Macro is live and profitable ($1,152 running trade today). 
When ready to upgrade: replace Oil Macro with Oil Micro for +2.6x more P&L.
