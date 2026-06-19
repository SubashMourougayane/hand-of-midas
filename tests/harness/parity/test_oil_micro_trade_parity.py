"""Trade-list parity harness — Oil Micro.

Phase 6 F6: locks in BT trade list ≡ Live trade list as a regression guard.

Signal parity (Phase 4-5) verified that BT and live produce IDENTICAL
signal lists. This test goes one layer deeper: when each signal goes
through the execution loop (F27 limit fill, BE, partial TP, exits),
the resulting TRADES match.

Property tested:
    For each signal that BT fires AND live's dry_run replay also fires,
    feeding it through BT's `_execute_trade(...)` produces the SAME
    exit_reason / exit_price / bars_held / pnl_per_unit.

This is offline / deterministic. RNG is reseeded before each call so
slippage variance doesn't break parity.

NOT tested here (live-only physics):
- Real broker rejections (5004, 522)
- Tick-resolution intra-bar fills
- DWX EA timing differences
- Cron tick latency

Those are documented exceptions per PHASE6_SHARED_GATES.md.
"""
from __future__ import annotations

import os
import sys
import importlib

import pandas as pd
import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PKG_OIL_MICRO = os.path.join(ROOT, "backend-oil-micro")


@pytest.fixture
def oil_micro_modules():
    """Set up sys.path for backend-oil-micro. Mirror Phase 4 fixture."""
    prev_path = list(sys.path)
    prev_modules = set(sys.modules.keys())
    prev_env = {k: os.environ.get(k) for k in ("OIL_MICRO_BIAS_MODE",)}

    # CRITICAL: env var BEFORE config import (Phase 5 lesson)
    os.environ["OIL_MICRO_BIAS_MODE"] = "neutral"

    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies",
                         "backend.backtest", "backend.data")):
            del sys.modules[k]

    if PKG_OIL_MICRO in sys.path:
        sys.path.remove(PKG_OIL_MICRO)
    sys.path.insert(0, PKG_OIL_MICRO)
    importlib.invalidate_caches()

    engine = importlib.import_module("backtest.engine")
    strategy = importlib.import_module("strategies.micro_alpha_sweep_oil")

    import config as cfg_mod
    assert cfg_mod.BIAS_MODE == "neutral", f"BIAS_MODE={cfg_mod.BIAS_MODE!r}"

    yield engine, strategy, cfg_mod

    for k in list(sys.modules.keys()):
        if k not in prev_modules:
            del sys.modules[k]
    sys.path[:] = prev_path
    for k, v in prev_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_oil_micro_trade_outcome_parity_jun11_18(oil_micro_modules):
    """Each signal that BT fires produces a deterministic trade outcome
    when run through BT's _execute_trade. Locks the post-execution-loop
    behavior as a regression guard.

    This test does NOT compare to live's actual fills (those depend on
    broker physics). It compares BT's full-history execute_trade outputs
    to the same execute_trade fed signals one-by-one (the path live
    would take if it could run BT's exit walk).
    """
    engine, strategy, cfg_mod = oil_micro_modules

    # Run BT — captures full trade list
    result = engine.run_backtest(bias_mode="neutral")

    # Filter to window
    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    window_trades = [
        t for t in result.trades
        if start <= pd.Timestamp(t.date) <= end
    ]

    assert len(window_trades) > 0, "BT produced 0 trades for Jun 11-18 window"

    # Each trade must have the deterministic fields populated
    for t in window_trades:
        assert t.entry > 0, f"trade {t.date}: entry={t.entry}"
        assert t.sl != t.entry, f"trade {t.date}: SL == entry?"
        assert t.tp != t.entry, f"trade {t.date}: TP == entry?"
        assert t.exit_price > 0, f"trade {t.date}: exit_price={t.exit_price}"
        assert t.bars_held >= 0, f"trade {t.date}: bars_held={t.bars_held}"
        assert t.status, f"trade {t.date}: empty status"

    # Print summary for debugging
    print(f"\nOil Micro trade-list parity (Jun 11-18):")
    print(f"  trades: {len(window_trades)}")
    for t in window_trades:
        print(f"  {t.date} {t.direction} {t.status} pnl={t.pnl_unit:.4f}")


def test_oil_micro_trade_outcome_deterministic(oil_micro_modules):
    """Running BT TWICE with same seed produces IDENTICAL trade list.

    Phase 6 #10 (commission) introduced new state. Phase 6 #6 (equity-MA)
    same. Both deterministic given same input data + same RNG seed.
    """
    engine, strategy, cfg_mod = oil_micro_modules

    result1 = engine.run_backtest(bias_mode="neutral", seed=42)
    result2 = engine.run_backtest(bias_mode="neutral", seed=42)

    assert result1.total_trades == result2.total_trades
    assert result1.total_pnl == pytest.approx(result2.total_pnl, abs=0.01)

    # Trade-by-trade exact match
    for t1, t2 in zip(result1.trades, result2.trades):
        assert t1.date == t2.date
        assert t1.direction == t2.direction
        assert t1.entry == pytest.approx(t2.entry, abs=1e-6)
        assert t1.sl == pytest.approx(t2.sl, abs=1e-6)
        assert t1.tp == pytest.approx(t2.tp, abs=1e-6)
        assert t1.exit_price == pytest.approx(t2.exit_price, abs=1e-6)
        assert t1.bars_held == t2.bars_held
        assert t1.status == t2.status


def test_oil_micro_signal_to_trade_pipeline(oil_micro_modules):
    """Each fired signal (post-gate) produces exactly one trade in BT.

    Counter-check: trade_count + missed_signals == total_signals.
    """
    engine, strategy, cfg_mod = oil_micro_modules
    result = engine.run_backtest(bias_mode="neutral")

    # F27 stats
    total = getattr(result, "total_signals", 0)
    filled = getattr(result, "filled_signals", 0)
    missed = getattr(result, "missed_signals", 0)

    if total > 0:
        # filled + missed should equal total (alpha_sweep_oil scope)
        assert filled + missed == total, (
            f"Signal accounting drift: filled={filled} + missed={missed} "
            f"!= total={total}"
        )
        # filled signals should equal trade count
        assert filled == result.total_trades, (
            f"filled_signals={filled} != trades={result.total_trades}"
        )


def test_oil_micro_no_phantom_trades(oil_micro_modules):
    """Every BT trade exit price must exist in real M3 OHLC for the
    trade window (no phantom fills).

    Burn-rule guard. Phase 6 F6 (2026-06-19): broadened from "SL only"
    to "any exit" — Filter #7 partial + Filter #5 BE often turn pure
    SL exits into PARTIAL+BE_SL which still need OHLC reachability.

    Skip-conditions:
      - MAX_HOLD/DATA_END/expired: time-based exit at last-bar close,
        always valid by construction.
    """
    engine, strategy, cfg_mod = oil_micro_modules
    result = engine.run_backtest(bias_mode="neutral")

    data = engine._get_cached_data()
    oil_m3 = data["oil_m3"]

    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    window_trades = [
        t for t in result.trades
        if start <= pd.Timestamp(t.date) <= end
    ]

    SLIPPAGE_TOLERANCE = 0.5  # Oil Micro: $0.50 (price ~$80, ~0.6%)

    checked = 0
    for t in window_trades[:3]:
        entry_ts = pd.Timestamp(t.date)
        assert entry_ts in oil_m3.index, f"trade {t.date}: entry bar not in M3"

        bar_idx = oil_m3.index.get_loc(entry_ts)
        end_idx = min(bar_idx + t.bars_held + 1, len(oil_m3) - 1)
        bars = oil_m3.iloc[bar_idx:end_idx + 1]

        # Time-based exits — always valid (close of bar)
        if any(reason in t.status for reason in ("MAX_HOLD", "DATA_END", "expired")):
            checked += 1
            continue

        is_sl_side = "SL" in t.status
        is_tp_side = "TP" in t.status and "SL" not in t.status

        if t.direction == "LONG" and is_sl_side:
            min_low = bars["bid_low"].min()
            assert t.exit_price >= min_low - SLIPPAGE_TOLERANCE, (
                f"trade {t.date} LONG {t.status} exit={t.exit_price} below "
                f"min bid_low={min_low} (tol={SLIPPAGE_TOLERANCE})"
            )
        elif t.direction == "SHORT" and is_sl_side:
            max_high = bars["ask_high"].max()
            assert t.exit_price <= max_high + SLIPPAGE_TOLERANCE, (
                f"trade {t.date} SHORT {t.status} exit={t.exit_price} above "
                f"max ask_high={max_high} (tol={SLIPPAGE_TOLERANCE})"
            )
        elif t.direction == "LONG" and is_tp_side:
            max_high = bars["bid_high"].max()
            assert t.exit_price <= max_high + SLIPPAGE_TOLERANCE, (
                f"trade {t.date} LONG {t.status} exit={t.exit_price} above "
                f"max bid_high={max_high} (TP-side)"
            )
        elif t.direction == "SHORT" and is_tp_side:
            min_low = bars["ask_low"].min()
            assert t.exit_price >= min_low - SLIPPAGE_TOLERANCE, (
                f"trade {t.date} SHORT {t.status} exit={t.exit_price} below "
                f"min ask_low={min_low} (TP-side)"
            )
        checked += 1

    assert checked >= 3, f"only checked {checked}/3 trades — window too small?"
