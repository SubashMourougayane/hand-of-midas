"""Integration test for run_engine — stub strategy + execution model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterator

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.clock_bt import BacktestClock
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.order import Fill, OpenTrade, Order
from bt_engine.core.signal import StepResult, StrategyEvent
from bt_engine.core.state import StrategyState


def _bars(n: int = 10, start: str = "2026-06-29T00:00:00Z") -> list[Bar]:
    base = pd.Timestamp(start)
    out = []
    for i in range(n):
        ts = base + pd.Timedelta(minutes=15 * i)
        # gentle uptrend, range stays mild
        o = 1000.0 + i
        c = o + 0.5
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        out.append(Bar("X", "M15", ts, o, h, l, c, 1.0))
    return out


@dataclass
class StubState(StrategyState):
    seen_timestamps: list[pd.Timestamp] = field(default_factory=list)
    history_last_ts: list[pd.Timestamp] = field(default_factory=list)
    issued_order: bool = False


class StubStrategy:
    strategy_id = "stub"
    config = None

    def initial_state(self) -> StubState:
        return StubState()

    def on_bar(self, state: StubState, bar: Bar, history: pd.DataFrame) -> StepResult:
        state.seen_timestamps.append(bar.timestamp)
        state.history_last_ts.append(history["timestamp"].iloc[-1])
        orders: tuple[Order, ...] = ()
        # issue exactly one long order at the 3rd bar, target the 4th bar's open
        if not state.issued_order and len(state.seen_timestamps) == 3:
            next_bar = bar.timestamp + pd.Timedelta(minutes=15)
            orders = (
                Order(
                    symbol="X", side=1, qty=1.0,
                    intended_entry_bar=next_bar,
                    stop_price=bar.close - 5.0,
                    take_profit=bar.close + 5.0,
                    risk_units=5.0,
                    tag="stub", bracket_kind="1R",
                    trade_id=uuid.uuid4(),
                ),
            )
            state.issued_order = True
        return StepResult(state=state, new_orders=orders)


class StubProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.symbol = "X"
        self.timeframe = "M15"
        self._frame = pd.DataFrame(
            [
                {"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume}
                for b in bars
            ]
        )
        self._bars = bars

    def bars(self) -> Iterator[Bar]:
        return iter(self._bars)

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)


class FillAtOpen:
    def simulate_fill(self, order: Order, next_bar: Bar) -> Fill:
        return Fill(order.symbol, order.side, order.qty, next_bar.open, next_bar.timestamp)

    def slippage_bps(self) -> float:
        return 0.0


def test_engine_processes_all_bars() -> None:
    bars = _bars(10)
    provider = StubProvider(bars)
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=StubStrategy(),
        execution=FillAtOpen(),
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    assert run.bars_processed == 10


def test_engine_history_alignment_assertion_holds() -> None:
    """Strategy.on_bar must see history whose last row matches bar.timestamp."""
    bars = _bars(5)
    provider = StubProvider(bars)
    strat = StubStrategy()
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=strat,
        execution=FillAtOpen(),
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    # we can't read state directly because engine deepcopies; instead drive via callback
    # but for now, just assert no crash means alignment held.


def test_engine_opens_and_closes_trade_via_bracket() -> None:
    bars = _bars(20)
    provider = StubProvider(bars)
    closed = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=StubStrategy(),
        execution=FillAtOpen(),
        on_trade_close=lambda tr, oc: closed.append((tr, oc)),
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    # gentle uptrend with risk_units=5 and TP=close+5 => TP eventually hit
    # 1 trade opened at bar 3 (index 3) targeting bar 4 entry
    # entry_price = bar[4].open = 1004
    # tp = bar[3].close + 5 = 1003.5 + 5 = 1008.5
    # bar 9 has close 1009.5 -> TP hit
    assert len(closed) == 1
    tr, oc = closed[0]
    assert tr.side == 1
    assert oc.reason == "TP"


def test_engine_mode_validation() -> None:
    bars = _bars(2)
    provider = StubProvider(bars)
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=StubStrategy(),
        execution=FillAtOpen(),
    )
    with pytest.raises(ValueError):
        run_engine(run_id=uuid.uuid4(), deps=deps, mode="zzz")


class OneShotLiveStrategy:
    strategy_id = "one_shot"
    config = {}

    def initial_state(self) -> StubState:
        return StubState()

    def on_bar(self, state: StubState, bar: Bar, history: pd.DataFrame) -> StepResult:
        if state.issued_order:
            return StepResult(state=state)
        state.issued_order = True
        order = Order(
            symbol="X", side=1, qty=1.0,
            intended_entry_bar=bar.timestamp + pd.Timedelta(minutes=15),
            stop_price=bar.close - 5.0,
            take_profit=bar.close + 5.0,
            risk_units=5.0,
            tag="live", bracket_kind="1R",
            trade_id=uuid.uuid4(),
        )
        return StepResult(
            state=state,
            new_orders=(order,),
            new_events=(StrategyEvent(str(order.trade_id), "ENTRY_SUBMIT", {"zone_id": 7}),),
        )


class FakeBroker:
    def __init__(self, *, fill_price: float | None = 100.5) -> None:
        self.submitted: list[Order] = []
        self.fill_price = fill_price

    def submit_order(self, order: Order) -> str:
        self.submitted.append(order)
        return "ticket-1"

    def cancel(self, order_id: str) -> None:
        pass

    def fills(self):
        if self.fill_price is None:
            return
        order = self.submitted[-1]
        yield Fill(order.symbol, order.side, order.qty, self.fill_price, pd.Timestamp("2026-06-29T00:00:01Z"))

    def positions(self):
        return []


def test_live_submits_new_order_during_signal_bar_not_target_bar() -> None:
    bars = _bars(2)
    provider = StubProvider(bars)
    broker = FakeBroker()
    opened: list[OpenTrade] = []
    seen_events: list[StrategyEvent] = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=OneShotLiveStrategy(),
        broker=broker,
        on_trade_open=opened.append,
        on_strategy_event=seen_events.append,
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="live", max_bars=1)
    assert run.bars_processed == 1
    assert len(broker.submitted) == 1
    assert len(opened) == 1
    assert broker.submitted[0].intended_entry_bar == bars[0].timestamp + pd.Timedelta(minutes=15)
    assert opened[0].entry_timestamp == pd.Timestamp("2026-06-29T00:00:01Z")
    assert [ev.type for ev in seen_events] == ["ENTRY_SUBMIT"]


def test_live_no_fill_does_not_crash_engine() -> None:
    bars = _bars(1)
    provider = StubProvider(bars)
    events: list[StrategyEvent] = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=OneShotLiveStrategy(),
        broker=FakeBroker(fill_price=None),
        on_strategy_event=events.append,
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="live")
    assert run.bars_processed == 1
    assert any(ev.type == "ORDER_SUBMIT_NO_FILL" for ev in events)


def test_initial_open_trades_are_replayed_to_open_callback() -> None:
    bars = _bars(1)
    provider = StubProvider(bars)
    trade_id = uuid.uuid4()
    order = Order(
        symbol="X", side=1, qty=1.0,
        intended_entry_bar=bars[0].timestamp,
        stop_price=95.0,
        take_profit=105.0,
        risk_units=5.0,
        tag="reconciled",
        bracket_kind="reconciled_live",
        trade_id=trade_id,
    )
    fill = Fill("X", 1, 1.0, 100.0, bars[0].timestamp)
    initial = OpenTrade(
        trade_id=trade_id,
        order=order,
        fill=fill,
        entry_price=100.0,
        entry_timestamp=bars[0].timestamp,
        side=1,
        stop_price=95.0,
        take_profit=105.0,
        risk_units=5.0,
    )
    opened: list[OpenTrade] = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=StubStrategy(),
        broker=FakeBroker(),
        initial_open_trades=(initial,),
        on_trade_open=opened.append,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="live", max_bars=1)
    assert opened == [initial]
