"""Trade-list parity harness — Gold Micro.

Phase 6 F6: same as Oil Micro trade parity but for backend-micro.
See test_oil_micro_trade_parity.py for full docstring.
"""
from __future__ import annotations

import os
import sys
import importlib

import pandas as pd
import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PKG_GOLD_MICRO = os.path.join(ROOT, "backend-micro")


@pytest.fixture
def gold_micro_modules():
    """Set up sys.path for backend-micro. Mirror Phase 4 fixture."""
    prev_path = list(sys.path)
    prev_modules = set(sys.modules.keys())
    prev_env = {k: os.environ.get(k) for k in ("GOLD_MICRO_BIAS_MODE",)}

    os.environ["GOLD_MICRO_BIAS_MODE"] = "neutral"

    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies",
                         "backend.backtest", "backend.data")):
            del sys.modules[k]

    if PKG_GOLD_MICRO in sys.path:
        sys.path.remove(PKG_GOLD_MICRO)
    sys.path.insert(0, PKG_GOLD_MICRO)
    importlib.invalidate_caches()

    engine = importlib.import_module("backtest.engine")
    strategy = importlib.import_module("backend.strategies.micro_alpha_sweep")

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


def test_gold_micro_trade_outcome_parity_jun11_18(gold_micro_modules):
    """Each BT trade for Jun 11-18 has populated deterministic fields."""
    engine, strategy, cfg_mod = gold_micro_modules

    result = engine.run_backtest(strategies=["micro_alpha_sweep"], bias_mode="neutral")

    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    window_trades = [
        t for t in result.trades
        if start <= pd.Timestamp(t.date) <= end
    ]

    assert len(window_trades) > 0, "BT produced 0 trades for Jun 11-18 window"

    for t in window_trades:
        assert t.entry > 0, f"trade {t.date}: entry={t.entry}"
        assert t.sl != t.entry, f"trade {t.date}: SL == entry?"
        assert t.tp != t.entry, f"trade {t.date}: TP == entry?"
        assert t.exit_price > 0, f"trade {t.date}: exit_price={t.exit_price}"
        assert t.bars_held >= 0, f"trade {t.date}: bars_held={t.bars_held}"
        assert t.status, f"trade {t.date}: empty status"

    print(f"\nGold Micro trade-list parity (Jun 11-18):")
    print(f"  trades: {len(window_trades)}")
    for t in window_trades:
        print(f"  {t.date} {t.direction} {t.status} pnl={t.pnl_unit:.4f}")


def test_gold_micro_trade_outcome_deterministic(gold_micro_modules):
    """Running BT TWICE with same seed produces IDENTICAL trade list."""
    engine, strategy, cfg_mod = gold_micro_modules

    result1 = engine.run_backtest(
        strategies=["micro_alpha_sweep"], bias_mode="neutral", seed=42)
    result2 = engine.run_backtest(
        strategies=["micro_alpha_sweep"], bias_mode="neutral", seed=42)

    assert result1.total_trades == result2.total_trades
    assert result1.total_pnl == pytest.approx(result2.total_pnl, abs=0.01)

    for t1, t2 in zip(result1.trades, result2.trades):
        assert t1.date == t2.date
        assert t1.direction == t2.direction
        assert t1.entry == pytest.approx(t2.entry, abs=1e-6)
        assert t1.sl == pytest.approx(t2.sl, abs=1e-6)
        assert t1.tp == pytest.approx(t2.tp, abs=1e-6)
        assert t1.exit_price == pytest.approx(t2.exit_price, abs=1e-6)
        assert t1.bars_held == t2.bars_held
        assert t1.status == t2.status


def test_gold_micro_no_phantom_trades(gold_micro_modules):
    """Spot-check 3 trades — exit price must exist in real M3 OHLC.

    Burn-rule guard: BT exit price has to be a price that actually
    occurred during the trade. No phantom fills.

    Phase 6 F6 fix (2026-06-19): filter was `status == "SL"` only and
    skipped when none. Gold Micro Jun 11-18 has no pure-SL exits
    (Filter #7 partial + Filter #5 BE dominate). Broadened to check
    ANY trade in window — same OHLC reachability guarantee for every
    exit reason.

    Skip-conditions per exit reason:
      - SL / BE_SL / PARTIAL+SL / PARTIAL+BE_SL: exit hit by ask_high
        (SHORT) or bid_low (LONG) within trade window — same physical
        check.
      - TP / PARTIAL+TP: exit hit by bid_high (LONG) or ask_low (SHORT).
      - MAX_HOLD / PARTIAL+MAX_HOLD / DATA_END: exit at last-bar close,
        which is always in OHLC by construction. Skip OHLC bounds.
    """
    engine, strategy, cfg_mod = gold_micro_modules
    result = engine.run_backtest(strategies=["micro_alpha_sweep"], bias_mode="neutral")

    data = engine._get_cached_data()
    gold_m3 = data["gold_m3"]

    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    window_trades = [
        t for t in result.trades
        if start <= pd.Timestamp(t.date) <= end
    ]

    # Tolerance for slippage — Gold has $4000+ price so 5.0 ≈ 0.12%
    SLIPPAGE_TOLERANCE = 5.0

    checked = 0
    for t in window_trades[:3]:
        entry_ts = pd.Timestamp(t.date)
        assert entry_ts in gold_m3.index, f"trade {t.date}: entry bar not in M3"

        bar_idx = gold_m3.index.get_loc(entry_ts)
        end_idx = min(bar_idx + t.bars_held + 1, len(gold_m3) - 1)
        bars = gold_m3.iloc[bar_idx:end_idx + 1]

        # Skip OHLC reachability check for time-based exits (always valid by construction)
        if any(reason in t.status for reason in ("MAX_HOLD", "DATA_END", "expired")):
            checked += 1
            continue

        # SL-side exits: LONG exits at bid_low extreme; SHORT at ask_high extreme
        # TP-side exits: LONG exits at bid_high; SHORT at ask_low
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
                f"max bid_high={max_high} (TP-side check)"
            )
        elif t.direction == "SHORT" and is_tp_side:
            min_low = bars["ask_low"].min()
            assert t.exit_price >= min_low - SLIPPAGE_TOLERANCE, (
                f"trade {t.date} SHORT {t.status} exit={t.exit_price} below "
                f"min ask_low={min_low} (TP-side check)"
            )
        checked += 1

    assert checked >= 3, f"only checked {checked}/3 trades — window too small?"
