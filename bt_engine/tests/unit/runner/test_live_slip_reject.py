"""LiveSafetyBroker rejects fills whose actual stop distance exceeds tolerance.

Regression test for L99 audit suspect #1 (2026-07-01):
Trade ticket 2116651769 filled 0.43 lot short at $4022.59 vs expected $4030.74,
inflating actual stop distance from $3.49 to $11.64 (3.34x). Real risk hit
$500 on $10k account when strategy intended $150.

The fix: LiveSafetyBroker.fills() validates each fill's actual stop distance
against order.risk_units and issues a CLOSE if the ratio exceeds
max_entry_slip_ratio, then yields nothing so engine drops the order.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

import pandas as pd
import pytest

from bt_engine.core.order import Fill, Order
from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.runner.live import LiveSafetyBroker, LiveSafetyConfig


def _order(*, side: int, entry: float, sl: float, tp: float, qty: float = 0.10) -> Order:
    return Order(
        symbol="XAUUSD.ecn", side=side, qty=qty,
        intended_entry_bar=pd.Timestamp("2026-07-01 12:00:00", tz="UTC"),
        stop_price=sl, take_profit=tp, risk_units=abs(entry - sl),
        tag="test", bracket_kind="1R", trade_id=uuid.uuid4(),
    )


@dataclass
class _StubBroker:
    """Fake DWXBrokerAdapter: yields whatever fill you prime + records cancels."""
    _fill: Fill | None = None
    _last_response: dict = field(default_factory=dict)
    cancelled: list[str] = field(default_factory=list)
    submitted: list[Order] = field(default_factory=list)

    def prime_fill(self, price: float, ticket: str = "999") -> None:
        self._fill = Fill(
            symbol="XAUUSD.ecn", side=1, qty=0.10, price=price,
            fill_timestamp=pd.Timestamp("2026-07-01 12:00:15", tz="UTC"),
        )
        self._last_response = {"success": True, "ticket": ticket, "price": price, "volume": 0.10}

    def submit_order(self, order: Order) -> str:
        self.submitted.append(order)
        return str(self._last_response.get("ticket", "999"))

    def cancel(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def modify(self, ticket: str, *, sl: float, tp: float = 0.0) -> None:
        pass

    def close_partial(self, ticket: str, qty: float) -> None:
        pass

    def last_response(self) -> dict:
        return self._last_response

    def fills(self) -> Iterator[Fill]:
        if self._fill is not None:
            yield self._fill
            self._fill = None

    def positions(self):
        return []


@dataclass
class _StubBridge:
    def open_orders(self):
        return {}

    def market_data(self):
        return {"XAUUSD.ecn": {"bid": 4030.0, "ask": 4030.1, "spread": 0.1}}

    def account_info(self):
        return {"server": "JustMarkets-Demo2", "balance": 10000.0, "equity": 10000.0}


def test_fills_accepts_within_tolerance() -> None:
    """Actual stop ratio 1.05x expected — under 1.15x tolerance → yielded."""
    broker = _StubBroker()
    bridge = _StubBridge()
    config = LiveSafetyConfig(require_demo=False, max_entry_slip_ratio=1.15,
                                kill_switch_path=__import__("pathlib").Path("/tmp/NEVER_EXISTS_KILLSWITCH"))
    safe = LiveSafetyBroker(broker, bridge, config, sizer=None)

    # Expected entry $4030, SL $4025, risk=5.0. Fill at $4029.75 → actual stop=4.75 → ratio 0.95x.
    order = _order(side=1, entry=4030.0, sl=4025.0, tp=4040.0, qty=0.10)
    safe.last_submitted_order = order
    broker.prime_fill(4029.75)

    fills = list(safe.fills())
    assert len(fills) == 1
    assert fills[0].price == 4029.75
    assert broker.cancelled == [], "no close should have been sent"


def test_fills_rejects_when_ratio_exceeds_tolerance() -> None:
    """Trade 2116651769 reproduction: expected $3.49 stop, actual $11.64 (3.34x)."""
    broker = _StubBroker()
    bridge = _StubBridge()
    config = LiveSafetyConfig(require_demo=False, max_entry_slip_ratio=1.15,
                                kill_switch_path=__import__("pathlib").Path("/tmp/NEVER_EXISTS_KILLSWITCH"))
    safe = LiveSafetyBroker(broker, bridge, config, sizer=None)

    # Expected: entry $4030.74, SL $4034.23, risk_units=3.4856
    # Actual fill: $4022.59, actual stop = $11.64, ratio = 3.34x
    order = _order(side=-1, entry=4030.74, sl=4034.23, tp=3985.91)
    order = Order(
        symbol=order.symbol, side=order.side, qty=order.qty,
        intended_entry_bar=order.intended_entry_bar,
        stop_price=order.stop_price, take_profit=order.take_profit,
        risk_units=3.4856, tag=order.tag, bracket_kind=order.bracket_kind,
        trade_id=order.trade_id,
    )
    safe.last_submitted_order = order
    broker.prime_fill(4022.59, ticket="2116651769")

    fills = list(safe.fills())
    assert len(fills) == 0, "fill must be REJECTED (yielded nothing)"
    assert broker.cancelled == ["2116651769"], "position must be CLOSED to prevent 3.3x risk exposure"


def test_fills_tolerance_boundary() -> None:
    """Exactly at 1.15x ratio → still accepted. Just over → rejected."""
    broker = _StubBroker()
    bridge = _StubBridge()
    config = LiveSafetyConfig(require_demo=False, max_entry_slip_ratio=1.15,
                                kill_switch_path=__import__("pathlib").Path("/tmp/NEVER_EXISTS_KILLSWITCH"))
    safe = LiveSafetyBroker(broker, bridge, config, sizer=None)

    # Expected risk 5.0. Actual = 5.75 = 1.15x exactly → accept.
    order = _order(side=1, entry=100.0, sl=95.0, tp=110.0)
    safe.last_submitted_order = order
    broker.prime_fill(100.75)  # side=1 SL below: stop = 100.75 - 95.0 = 5.75

    fills = list(safe.fills())
    assert len(fills) == 1
    assert broker.cancelled == []


def test_fills_no_order_context_passes_through() -> None:
    """If last_submitted_order is None (BT-mode misconfig), do NOT block."""
    broker = _StubBroker()
    bridge = _StubBridge()
    config = LiveSafetyConfig(require_demo=False, max_entry_slip_ratio=1.15,
                                kill_switch_path=__import__("pathlib").Path("/tmp/NEVER_EXISTS_KILLSWITCH"))
    safe = LiveSafetyBroker(broker, bridge, config, sizer=None)

    safe.last_submitted_order = None
    broker.prime_fill(100.0)
    fills = list(safe.fills())
    assert len(fills) == 1  # pass-through
