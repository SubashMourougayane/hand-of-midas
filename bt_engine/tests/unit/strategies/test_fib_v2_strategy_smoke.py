"""Smoke test for FibV2EnsembleStrategy: factory works, registry round-trip,
initial_state is valid, on_bar runs without errors on a synthetic frame.

This is NOT a parity test — parity lives in Phase 5. Smoke verifies wiring.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from bt_engine.core.bar import Bar
from bt_engine.strategies.fib_v2 import (
    FibV2Config,
    FibV2EnsembleStrategy,
    FibV2LongStrategy,
    FibV2ShortStrategy,
    LONG_BULL_STRONG,
    SHORT_BEAR_STRONG,
)
from bt_engine.strategies import registry


def _make_m5_frame(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    base = 4000.0 + np.cumsum(rng.normal(0, 2, n))
    high = base + np.abs(rng.normal(1, 0.5, n))
    low = base - np.abs(rng.normal(1, 0.5, n))
    open_ = base + rng.normal(0, 0.3, n)
    open_ = np.clip(open_, low, high)
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high,
        "low": low, "close": base, "volume": rng.integers(1, 100, n),
    })


def test_registry_factory_returns_strategy():
    s = registry.get("fib_v2_xau_ensemble", symbol="XAUUSD.ecn")
    assert s.strategy_id == "fib_v2_xau_ensemble"
    assert len(s.legs) == 2
    assert s.legs[0].leg_name == "long_bull_strong"
    assert s.legs[1].leg_name == "short_bear_strong"


def test_long_only_strategy_has_one_leg():
    s = FibV2LongStrategy(symbol="XAUUSD.ecn")
    assert len(s.legs) == 1
    assert s.legs[0] == LONG_BULL_STRONG


def test_short_only_strategy_has_one_leg():
    s = FibV2ShortStrategy(symbol="XAUUSD.ecn")
    assert len(s.legs) == 1
    assert s.legs[0] == SHORT_BEAR_STRONG


def test_cost_override_by_symbol():
    s_xau = FibV2EnsembleStrategy(symbol="XAUUSD.ecn")
    s_eur = FibV2EnsembleStrategy(symbol="EURUSD.ecn")
    s_brent = FibV2EnsembleStrategy(symbol="BCO_USD")
    assert s_xau._cost_usd == 0.30
    assert s_eur._cost_usd == 0.00003
    assert s_brent._cost_usd == 0.05


def test_initial_state_is_clean():
    s = FibV2EnsembleStrategy(symbol="XAUUSD.ecn")
    state = s.initial_state()
    assert state.bars_seen == 0
    assert state.last_L is None
    assert state.last_H is None
    assert len(state.pending_setups) == 0
    assert len(state.consumed_setup_keys) == 0


def test_on_bar_no_errors_short_run():
    """Run 200 bars; assert state advances and no exceptions."""
    s = FibV2EnsembleStrategy(symbol="XAUUSD.ecn")
    state = s.initial_state()
    frame = _make_m5_frame(n=200)
    for i in range(len(frame)):
        history = frame.iloc[: i + 1].reset_index(drop=True)
        bar = Bar.from_row(symbol="XAUUSD.ecn", timeframe="M5", row=frame.iloc[i])
        step = s.on_bar(state, bar, history)
        state = step.state
    assert state.bars_seen == 200


def test_validate_for_live_requires_m5():
    s = FibV2EnsembleStrategy(symbol="XAUUSD.ecn")
    s.validate_for_live(timeframe="M5")  # ok
    with pytest.raises(ValueError, match="M5"):
        s.validate_for_live(timeframe="M1")
    with pytest.raises(ValueError, match="M5"):
        s.validate_for_live(timeframe="H1")


def test_config_qty_override():
    s = FibV2EnsembleStrategy(symbol="XAUUSD.ecn", qty=0.05)
    assert s.config.qty == 0.05


def test_state_clone_returns_self_for_perf():
    """FibV2State.clone() returns self by design (perf — see state.py docstring).

    The strategy mutates state in-place and returns it via StepResult. Engine
    treats the returned object as the new state. No deep copy needed since
    state is single-threaded and never inspected between bars.
    """
    s = FibV2EnsembleStrategy(symbol="XAUUSD.ecn")
    state = s.initial_state()
    state.last_L = 4000.0
    clone = state.clone()
    assert clone is state, "FibV2State.clone() must return self (perf override)"
