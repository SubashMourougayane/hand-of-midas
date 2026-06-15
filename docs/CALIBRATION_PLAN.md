# Live-Calibrated Backtest — Planned Project

**Status:** ⏸️ Deferred until 2-4 weeks of clean live data accumulated
**Trigger to start:** Once we have ≥30 clean live trades post-2026-06-15 audit fixes (phantom fill, orphan cascade, dedup bug, all 24 audit issues).

---

## Why we're waiting

The 2009/2022 postmortems confirmed the backtest is mechanically honest, but the headline percentages (4673%, 8776%) don't survive contact with live execution drag. We need a **calibrated** layer that shows realistic expected P&L alongside the theoretical.

Currently we don't have enough clean live data to set the calibration parameters empirically. Today's session alone contains:
- Phantom-fill bug class (May 22)
- Orphan-trade cascade (June 10)
- Dedup-typo duplicate trades (June 15)
- DWX EA dual-instance issues
- Telegram silent failures (Issue #13)

Calibration built on this data would lock in the bugs as parameters. We need 2-4 weeks of post-fix runtime first.

---

## Three-layer dashboard concept

| Layer | What it shows | Source |
|---|---|---|
| **Theoretical** | Pure strategy on historical OHLC, zero drag | Current `run_backtest()` (the 4673% / 8776% numbers) |
| **Live Calibrated** | Same strategy + realistic execution drag model | `run_backtest(mode="live_calibrated")` (to build) |
| **Live Actual** | Real broker results from the DB | `gd_trades` aggregation |

Investor pitch leads with **Calibrated**, references Theoretical as upper bound, shows Actual as proof once accumulated.

---

## Drag parameters to model

| Parameter | What it models | Initial guess | How to refine |
|---|---|---|---|
| `entry_slippage` | Market-order fills past signal mid-price | $0.05 (Gold), $0.02 (Oil) | Avg of `(live_fill - signal_price)` from `gd_trades` |
| `sl_slippage` | SL fills past stop level (broker doesn't honor exact SL) | $0.15 (Gold), $0.30 (Oil) | Compare DB `exit_price` vs `sl_price` on SL exits |
| `tp_slippage` | Limit-order fills at TP | $0.00 typical | Most TPs fill exactly; verify in live data |
| `partial_close_lag` | DWX response lag on partial close | $0.05 (Gold), $0.10 (Oil) | (broker_partial_price - intended_partial_price) |
| `news_spread_mult` | Extra slippage during NFP/FOMC/CPI minutes | 3-5× | Cross-reference economic calendar with SL fills |
| `service_uptime_pct` | % of valid signals actually captured | 90-95% | (signals fired / signals possible) from logs |
| `weekend_gap_slip` | Monday open can slip past Friday SL | 25% chance, $5 max | Monday-Friday gap analysis |
| `order_rejection_rate` | Broker rejects (margin, min-stop, lot) | 1-3% | Count of `ORDER_FAILED` in journal |

---

## Implementation plan (when triggered)

### Phase 1 — Data collection layer (Week 1 post-trigger)

1. Build `scripts/calibration_extract.py` that reads:
   - `gd_signals` (intended) vs `gd_trades` (actual fill) → entry slippage
   - `gd_trades` exit_price vs sl_price → SL slippage
   - Journal `ORDER_FAILED` count → rejection rate
   - Service log gaps → uptime %
2. Output `docs/CALIBRATION_DATA_v1.json` with empirical params per system.
3. **Validate against the 2 known-clean weeks** (no audit-class bugs).

### Phase 2 — Engine extension (Week 2)

Branch: `feature/live-calibrated-backtest`

1. New file `backend/backtest/calibration.py`:
   ```python
   @dataclass
   class CalibrationParams:
       entry_slippage: float
       sl_slippage: float
       tp_slippage: float
       partial_close_lag: float
       news_spread_mult: float
       service_uptime_pct: float
       order_rejection_rate: float
       seed: int = 42
   ```
2. Extend `run_backtest()` with `mode: str = "theoretical" | "live_calibrated"`.
3. In live_calibrated mode:
   - Drop ~5-10% of signals randomly (uptime model)
   - Drop ~1-3% of accepted signals (rejection model)
   - Adjust entry_price by entry_slippage in adverse direction
   - Adjust exit_price by sl_slippage on SL exits
   - Apply news_spread_mult on bars in known high-vol minutes (need an economic calendar fixture)
   - Recompute P&L
4. Mirror to `backend-oil/`, `backend-micro/`, `backend-oil-micro/`.

### Phase 3 — Dashboard integration (Week 3)

1. `/backtest` page: tabs for Theoretical / Live Calibrated / Live Actual.
2. `/report` (investor page): headline switches to **Live Calibrated** as default; Theoretical relegated to footnote.
3. Add asterisk: "Live Calibrated based on N live trades 2026-06-15 → date. Refits monthly."

### Phase 4 — Auto-refit (Week 4+)

1. Monthly cron: re-extract calibration params from latest live data.
2. Diff vs prior calibration; alert if any param shifts >2× (suggests live conditions changed).
3. Re-run backtest with new params, update dashboard.

---

## What this protects against

| Risk | Without calibration | With calibration |
|---|---|---|
| Investor sees "+4673%" and assumes live similar | Disappointed when live is 1500-2000% | Sees realistic expectation upfront |
| Strategy R&D optimizes for backtest WR/PF | May ship filters that look good on paper but die on slippage | Optimizes the metric that maps to live |
| Filter sweeps overstate edge | A filter that adds +$30k theoretical may add only +$5k live | Filter sweep computes both numbers |
| New regime (e.g., 2025 oil crash) makes existing calibration stale | Live results diverge silently from backtest | Auto-refit catches this in monthly diff |

---

## Recalibration cadence

- **Monthly:** automatic refit from latest live data
- **After major broker change:** manual refit + re-run all backtests
- **After strategy change:** re-validate calibration assumptions still hold

---

## Reopen criteria

When at least one of:
- ✅ ≥30 clean live trades accumulated (no audit-class bugs)
- ✅ At least 1 full Asia → London → NY cycle without service downtime
- ✅ DWX EA dual-instance issue confirmed resolved
- ✅ User signals "ready" after observing 2+ weeks of stable trading

Then start **Phase 1 — Data collection layer**.

---

_Created 2026-06-15 after 2009 + 2022 pessimistic postmortems exposed the theoretical-vs-realistic gap. See:_
- `docs/POSTMORTEM_2009_OIL_MICRO.md`
- `docs/POSTMORTEM_2022_OIL_MICRO.md`
