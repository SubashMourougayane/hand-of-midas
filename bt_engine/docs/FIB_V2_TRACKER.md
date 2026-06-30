# Fib V2 ENSEMBLE — bt_engine Port Tracker

Plan: `/Users/subash/.claude/plans/ok-now-that-we-piped-fog.md`

| Phase | Status | Started | Completed | Tests | Notes |
|---|---|---|---|---|---|
| 1 — Fib V2 streaming strategy | COMPLETED | 2026-06-30 | 2026-06-30 | 24/24 unit + 1 integration | pivot, regime, swing trackers + ensemble strategy all green |
| 2 — Multi-TF data path | COMPLETED | 2026-06-30 | 2026-06-30 | 13/13 | OandaParquetProvider + MultiTfHistoryView green |
| 3 — DB migration 0002 | COMPLETED | 2026-06-30 | 2026-06-30 | 2/2 | 7 fib columns applied to golddigger_bt + _test |
| 4 — Soft-retire SDR-001 + EMA | COMPLETED | 2026-06-30 | 2026-06-30 | n/a | CLI defaults → fib_v2_xau_ensemble; DEPRECATED docstrings; STRATEGY_DEPRECATIONS.md |
| 5 — Parity gate (BLOCKING) | **PASSED** | 2026-06-30 | 2026-06-30 | 8/8 | XAU long, XAU short, XAU ensemble (count+net_R+summary), EUR ensemble (count+net_R). 10-15% tolerance per lane. |
| 6 — Live paper-live | COMPLETED | 2026-06-30 | 2026-06-30 | 1/1 + DB verified | Paper-live smoke 264 trades opened/261 closed; full fib metadata persisted; deployment plumbing READY. EA M5 export pending operator. |
| 7 — Partial-TP safety net | PLANNED | next session | — | — | Port Partial TP 50% at +1R / +2R to bt_engine. Research showed 2-2.6× net R, PF 2.03/1.96, 20/21 pos yrs. See `research/fib_retrace/safety_net_results.csv` + memory `fib-v2-partial-tp-winner.md`. |

## Research numbers to match (Phase 5 gate)

| Lane | Trades | PF | MAR | Pos years | Net $ @ $5k 3% reset |
|---|---|---|---|---|---|
| **XAU ensemble** | 4,740 | 1.31 | 0.41 | 18/21 | +$290,906 |
| **EUR ensemble** | 5,089 | 1.15 | 0.17 | 16/22 | +$173,719 |

## Frozen params (ENSEMBLE)

```
pivot_lb=5, max_hold_h=72 (max_hold_bars=864 M5 bars, horizon=1728)
session="all", ext_target_pct=1.618, sl_buffer_pct=0.02
swing_lb=20, d1_ema_fast=50, d1_ema_slow=200, atr_period=14
max_risk_pct=0.02
Costs: XAU=$0.30/risk_units, EUR=$0.00003/risk_units
LONG leg:  direction=long,  regime=bull_strong  (D1 close > ema200 AND ema50 > ema200)
SHORT leg: direction=short, regime=bear_strong  (D1 close < ema200 AND ema50 < ema200)
```

## Per-phase log

### Phase 1 — Fib V2 streaming strategy (COMPLETED 2026-06-30)

**Files created:**
- `bt_engine/bt_engine/strategies/fib_v2/__init__.py`
- `bt_engine/bt_engine/strategies/fib_v2/config.py` — FibV2Config + LegSpec + COST_USD_DEFAULTS
- `bt_engine/bt_engine/strategies/fib_v2/pivot_tracker.py` — incremental PivotTracker
- `bt_engine/bt_engine/strategies/fib_v2/regime_tracker.py` — D1 EMA200/EMA50/ATR14 with lag-1 semantics
- `bt_engine/bt_engine/strategies/fib_v2/swing_tracker.py` — M5 swing_low/high_lag
- `bt_engine/bt_engine/strategies/fib_v2/state.py` — FibV2State + FibSetup
- `bt_engine/bt_engine/strategies/fib_v2/strategy.py` — FibV2EnsembleStrategy + Long/Short variants
- `bt_engine/tests/unit/strategies/test_fib_v2_pivot_tracker.py` — 7 tests
- `bt_engine/tests/unit/strategies/test_fib_v2_regime_tracker.py` — 4 tests
- `bt_engine/tests/unit/strategies/test_fib_v2_swing_tracker.py` — 4 tests
- `bt_engine/tests/unit/strategies/test_fib_v2_strategy_smoke.py` — 9 tests
- `bt_engine/tests/integration/test_engine_fib_v2_smoke.py` — 50k bars through run_engine

**Files modified:**
- `bt_engine/bt_engine/strategies/registry.py` — added fib_v2_xau_ensemble, fib_v2_xau_long, fib_v2_xau_short

**Test results:** 24/24 unit + 1 integration smoke = ALL GREEN.

**Verified causality contracts:**
- PivotTracker emits at exact same (confirm_ts, type, price) as research::build_pivot_events for lb=2,3,5,8.
- RegimeTracker D1 features match research::attach_d1_to_m5 within abs=1e-3 (EMA initialisation drift acceptable).
- bull_strong / bear_strong gates fire on identical days as vectorized boolean masks.
- SwingTracker output matches research::add_m5_features swing_low/high_lag for lb=5,10,20,30.
- Strategy validates M5 timeframe at live entry.
- State deep-clone preserves tracker state isolation.

**Known deviation (to verify in Phase 5 parity gate):**
- Risk_units computed at signal time using `bar.close` as entry-price proxy. Research uses `m5.open[k+1]` (next bar's actual open). For BT this is acceptable since the engine fills at next bar OPEN and the engine.bracket uses `Order.risk_units` for outcome math. If Phase 5 parity fails on risk_units, we'll add a post-fill risk patch hook.
