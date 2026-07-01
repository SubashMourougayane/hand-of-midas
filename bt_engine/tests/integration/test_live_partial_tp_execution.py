"""End-to-end: partial-TP walker fire → broker receives CLOSE_PARTIAL + MODIFY.

Regression test for the 2026-07-01 execution-parity bug where walker mutated
in-memory OpenTrade state (partial_taken, stop_price → BE) but never told the
broker. Broker held the original SL, price whipped up, real SL hit, and net
$ P&L diverged sharply from walker's reported +0.5R gross.
"""
from __future__ import annotations

import uuid
from typing import Iterator

import pandas as pd

from bt_engine.core.bar import Bar
from bt_engine.core.clock_bt import BacktestClock
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.order import Fill, OpenTrade, Order
from bt_engine.core.signal import StepResult
from bt_engine.core.state import StrategyState
from dataclasses import dataclass, field


def _bars(low_trough_idx: int, n: int = 6) -> list[Bar]:
    """Short setup: entry 100, sl 101. Bar `low_trough_idx` low touches 99 (+1R MFE).
    Later bar closes back up to entry → SL_BE hit (or does with real broker: SL still at 101).
    """
    base = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
    out = []
    for i in range(n):
        ts = base + pd.Timedelta(minutes=15 * i)
        if i == low_trough_idx:
            out.append(Bar("X", "M15", ts, open=100.0, high=100.2, low=99.0, close=99.5, volume=1.0))
        else:
            out.append(Bar("X", "M15", ts, open=100.0, high=100.2, low=99.7, close=100.0, volume=1.0))
    return out


@dataclass
class OneShotShortState(StrategyState):
    fired: bool = False


class OneShotShort:
    """Strategy that submits ONE short order at bar 0, then does nothing."""

    strategy_id = "one_short"
    config = {}

    def initial_state(self) -> OneShotShortState:
        return OneShotShortState()

    def on_bar(self, state, bar, history):
        if state.fired:
            return StepResult(state=state)
        state.fired = True
        order = Order(
            symbol="X", side=-1, qty=0.10,
            intended_entry_bar=bar.timestamp + pd.Timedelta(minutes=15),
            stop_price=101.0, take_profit=90.0, risk_units=1.0,
            tag="ptp", bracket_kind="1R", trade_id=uuid.uuid4(),
            extra={"partial_tp_at_r": 1.0, "partial_tp_pct": 0.5},
        )
        return StepResult(state=state, new_orders=(order,))


class RecordingBroker:
    """Fake broker that records every command and returns success."""

    def __init__(self) -> None:
        self.submitted: list[Order] = []
        self.calls: list[dict] = []  # every method call ordered
        self._last_resp: dict = {}
        self.last_submitted_order: Order | None = None

    def submit_order(self, order: Order) -> str:
        self.submitted.append(order)
        self.last_submitted_order = order
        self._last_resp = {"success": True, "ticket": 999, "price": float(order.stop_price - 1),
                           "volume": order.qty}
        self.calls.append({"op": "submit", "qty": order.qty, "sl": order.stop_price,
                            "tp": order.take_profit})
        return "999"

    def cancel(self, order_id: str) -> None:
        self.calls.append({"op": "cancel", "id": order_id})

    def modify(self, ticket: str, *, sl: float, tp: float = 0.0) -> None:
        self.calls.append({"op": "modify", "ticket": ticket, "sl": sl, "tp": tp})

    def close_partial(self, ticket: str, qty: float) -> None:
        self.calls.append({"op": "close_partial", "ticket": ticket, "qty": qty})

    def close_all(self) -> None:
        self.calls.append({"op": "close_all"})

    def last_response(self) -> dict:
        return self._last_resp

    def fills(self) -> Iterator[Fill]:
        o = self.last_submitted_order
        if o is None:
            return
        # Fill at bar 1 open (100). Short entry 100, SL 101, TP 90.
        yield Fill(o.symbol, o.side, o.qty, 100.0,
                    pd.Timestamp("2026-01-01 00:15:00", tz="UTC"))

    def positions(self):
        return []


class ArrayProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.symbol = "X"
        self.timeframe = "M15"
        self._frame = pd.DataFrame(
            [{"timestamp": b.timestamp, "open": b.open, "high": b.high,
              "low": b.low, "close": b.close, "volume": b.volume} for b in bars]
        )

    def history_up_to(self, t):
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)


def test_partial_tp_sends_close_partial_and_modify_to_broker() -> None:
    bars = _bars(low_trough_idx=2)  # bar 2 crosses +1R
    provider = ArrayProvider(bars)
    broker = RecordingBroker()

    partial_events = []

    def _capture_partial(tr, bar):
        partial_events.append((tr.trade_id, tr.broker_ticket, tr.stop_price, bar.timestamp))
        # Wire the runner's real logic inline: broker.close_partial + broker.modify.
        pct = float((tr.order.extra or {}).get("partial_tp_pct", 0.5))
        broker.close_partial(tr.broker_ticket, float(tr.fill.qty) * pct)
        broker.modify(tr.broker_ticket, sl=float(tr.entry_price),
                      tp=float(tr.take_profit) if tr.take_profit else 0.0)

    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=OneShotShort(),
        broker=broker,
        on_partial_tp=_capture_partial,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="live")

    # Assertions:
    # 1) Order submitted with broker_ticket propagated to OpenTrade.
    assert len(broker.submitted) == 1
    assert len(partial_events) == 1, "partial callback must fire exactly once"
    trade_id, ticket, sl_after, bar_ts = partial_events[0]
    assert ticket == "999", "broker_ticket must flow from response into OpenTrade"
    assert sl_after == 100.0, "walker moved SL to entry (BE) before callback"
    # 2) Broker got the 2 commands in order.
    ops = [c["op"] for c in broker.calls]
    assert ops == ["submit", "close_partial", "modify"], (
        f"expected submit → close_partial → modify, got {ops}"
    )
    # 3) close_partial qty = 0.10 × 0.5 = 0.05.
    close_cmd = next(c for c in broker.calls if c["op"] == "close_partial")
    assert close_cmd["qty"] == 0.05
    assert close_cmd["ticket"] == "999"
    # 4) modify sends SL=entry_price (100).
    modify_cmd = next(c for c in broker.calls if c["op"] == "modify")
    assert modify_cmd["sl"] == 100.0
    assert modify_cmd["tp"] == 90.0
    assert modify_cmd["ticket"] == "999"


def test_partial_tp_does_not_fire_when_mfe_never_hits_trigger() -> None:
    """MFE stays below +1R → callback never fires → no broker modify commands."""
    # bars where price wobbles but never reaches +1R (low >= 99.5)
    base = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
    bars = [
        Bar("X", "M15", base + pd.Timedelta(minutes=15 * i),
             open=100.0, high=100.2, low=99.6, close=99.9, volume=1.0)
        for i in range(5)
    ]
    provider = ArrayProvider(bars)
    broker = RecordingBroker()
    calls: list = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=OneShotShort(),
        broker=broker,
        on_partial_tp=lambda t, b: calls.append(t),
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="live")
    assert len(calls) == 0
    ops = [c["op"] for c in broker.calls]
    assert "close_partial" not in ops
    assert "modify" not in ops
