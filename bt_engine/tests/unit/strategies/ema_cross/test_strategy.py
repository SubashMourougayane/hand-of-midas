"""Unit tests for EmaCrossStrategy — incremental signal generation."""
from __future__ import annotations

import uuid

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.clock_bt import BacktestClock
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.ema_cross.strategy import EmaCrossConfig, EmaCrossStrategy


def _bars(prices: list[float], start: str = "2026-06-29T00:00:00Z", tf: str = "M15") -> list[Bar]:
    base = pd.Timestamp(start)
    step = pd.Timedelta(minutes=15)
    out = []
    for i, p in enumerate(prices):
        ts = base + step * i
        out.append(Bar("X", tf, ts, p, p + 0.5, p - 0.5, p, 1.0))
    return out


class _StubProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.symbol = "X"
        self.timeframe = "M15"
        self._frame = pd.DataFrame(
            [{"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low,
              "close": b.close, "volume": b.volume} for b in bars]
        )

    def bars(self):
        return iter(self._frame.itertuples())

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)


def test_strategy_emits_no_orders_during_warmup() -> None:
    s = EmaCrossStrategy(EmaCrossConfig(fast=3, slow=5, atr_period=2))
    state = s.initial_state()
    bars = _bars([100.0, 101.0, 102.0])
    for b in bars:
        history = pd.DataFrame([{"timestamp": x.timestamp, "close": x.close} for x in bars if x.timestamp <= b.timestamp])
        step = s.on_bar(state, b, history)
        state = step.state
        assert step.new_orders == ()


def test_strategy_emits_long_order_on_cross_up() -> None:
    s = EmaCrossStrategy(EmaCrossConfig(fast=3, slow=8, atr_period=3))
    # downtrend then sharp uptrend → fast crosses above slow
    prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 100, 102, 104, 106, 108]
    bars = _bars([float(p) for p in prices])
    state = s.initial_state()
    orders_collected = []
    for b in bars:
        history = pd.DataFrame([{"timestamp": x.timestamp, "close": x.close} for x in bars if x.timestamp <= b.timestamp])
        step = s.on_bar(state, b, history)
        state = step.state
        orders_collected.extend(step.new_orders)
    assert len(orders_collected) >= 1
    assert orders_collected[0].side == 1
    assert orders_collected[0].stop_price < orders_collected[0].take_profit


def test_strategy_emits_short_order_on_cross_down() -> None:
    s = EmaCrossStrategy(EmaCrossConfig(fast=3, slow=8, atr_period=3))
    # uptrend then sharp drop
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 100, 98, 96, 94, 92]
    bars = _bars([float(p) for p in prices])
    state = s.initial_state()
    orders_collected = []
    for b in bars:
        history = pd.DataFrame([{"timestamp": x.timestamp, "close": x.close} for x in bars if x.timestamp <= b.timestamp])
        step = s.on_bar(state, b, history)
        state = step.state
        orders_collected.extend(step.new_orders)
    assert len(orders_collected) >= 1
    assert orders_collected[0].side == -1
    assert orders_collected[0].stop_price > orders_collected[0].take_profit


def test_strategy_does_not_double_signal_same_side() -> None:
    s = EmaCrossStrategy(EmaCrossConfig(fast=3, slow=5, atr_period=2))
    # steady uptrend after warmup — only ONE cross-up
    prices = [100, 99, 98, 97, 96, 97, 98, 99, 100, 101, 102, 103, 104]
    bars = _bars([float(p) for p in prices])
    state = s.initial_state()
    longs = 0
    for b in bars:
        history = pd.DataFrame([{"timestamp": x.timestamp, "close": x.close} for x in bars if x.timestamp <= b.timestamp])
        step = s.on_bar(state, b, history)
        state = step.state
        longs += sum(1 for o in step.new_orders if o.side > 0)
    assert longs <= 1


def test_strategy_through_engine_opens_and_closes_trade() -> None:
    s = EmaCrossStrategy(EmaCrossConfig(fast=3, slow=5, atr_period=3, sl_atr_mult=1.5, tp_atr_mult=3.0))
    prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 100, 110, 115, 118, 121, 125, 130]
    bars = _bars([float(p) for p in prices])
    provider = _StubProvider(bars)
    closed = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=s,
        execution=BTExecutionModel(),
        on_trade_close=lambda tr, oc: closed.append((tr, oc)),
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    assert len(closed) >= 1
    assert closed[0][1].reason in ("TP", "SL")
