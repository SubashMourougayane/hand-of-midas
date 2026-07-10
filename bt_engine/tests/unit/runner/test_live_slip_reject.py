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


def _order(*, side: int, entry: float, sl: float, tp: float, qty: float = 0.10,
           tag: str = "test") -> Order:
    return Order(
        symbol="XAUUSD.ecn", side=side, qty=qty,
        intended_entry_bar=pd.Timestamp("2026-07-01 12:00:00", tz="UTC"),
        stop_price=sl, take_profit=tp, risk_units=abs(entry - sl),
        tag=tag, bracket_kind="1R", trade_id=uuid.uuid4(),
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


@dataclass
class _SlowAckBroker:
    """OPEN raises (ack timeout) but the position IS live at the broker."""
    submitted: list = field(default_factory=list)
    def set_current_bar(self, bar): pass
    def submit_order(self, order):
        self.submitted.append(order)
        raise RuntimeError("No response within 5.0s")
    def cancel(self, oid): pass
    def modify(self, t, *, sl, tp=0.0): pass
    def close_partial(self, t, q): pass
    def last_response(self): return {}
    def fills(self): return iter(())  # nothing — command errored
    def positions(self): return []


@dataclass
class _SlowAckBridge:
    """open_orders shows the recovered position (matched by tag→comment)."""
    def open_orders(self):
        return {"2126588609": {"symbol": "XAUUSD.ecn", "type": "BUY", "volume": 0.03,
                                "open_price": 4166.18, "sl": 4119.77, "tp": 4389.6,
                                "comment": "intraday_a_long_2026-07-03T02:1"}}
    def market_data(self):
        return {"XAUUSD.ecn": {"bid": 4166.0, "ask": 4166.2, "spread": 0.2}}
    def account_info(self):
        return {"server": "JustMarkets-Demo2", "balance": 10000.0, "equity": 10000.0}


def test_open_slow_ack_recovers_ticket_and_fill() -> None:
    """OPEN slow-ack: submit raises, but broker holds the position. The recovery
    must (a) return the recovered ticket, (b) expose it via last_response, and
    (c) yield a synthesised fill so on_open persists the trade. Regression for
    2026-07-03 ticket 2126588609 (opened at broker, no DB row, orphaned)."""
    broker = _SlowAckBroker()
    bridge = _SlowAckBridge()
    config = LiveSafetyConfig(require_demo=False, max_entry_slip_ratio=1.15,
                                kill_switch_path=__import__("pathlib").Path("/tmp/NEVER_EXISTS_KILLSWITCH"))
    safe = LiveSafetyBroker(broker, bridge, config, sizer=None)
    order = _order(side=1, entry=4166.18, sl=4119.77, tp=4389.6, qty=0.03,
                   tag="intraday_a_long_2026-07-03T02:15:00+00:00")  # matches comment prefix

    tk = safe.submit_order(order)
    assert tk == "2126588609"                       # (a) recovered ticket returned
    assert safe.last_response().get("ticket") == "2126588609"  # (b) exposed
    fills = list(safe.fills())
    assert len(fills) == 1                           # (c) synthesised fill yielded
    assert fills[0].price == 4166.18
    assert fills[0].qty == 0.03


@dataclass
class _StaleAckBroker:
    """Real-adapter fault reproduction: a PREVIOUS order left a stale success
    response (price/ticket), and THIS OPEN slow-acks. fills() serves the stale
    fill and last_response() returns the stale success — exactly what the real
    DWXBrokerAdapter did before it cleared _last_response on a raising submit.
    """
    submitted: list = field(default_factory=list)
    cancelled: list = field(default_factory=list)
    # primed with a PRIOR order's response (different price + ticket)
    _last_response: dict = field(default_factory=lambda: {
        "success": True, "ticket": "111_PRIOR", "price": 9999.0, "volume": 0.10})
    _stale_fill: Fill | None = field(default_factory=lambda: Fill(
        symbol="XAUUSD.ecn", side=1, qty=0.10, price=9999.0,
        fill_timestamp=pd.Timestamp("2026-07-01 11:00:00", tz="UTC")))

    def set_current_bar(self, bar): pass
    def submit_order(self, order):
        self.submitted.append(order)
        raise RuntimeError("No response within 5.0s")  # slow-ack: does NOT clear stale state
    def cancel(self, oid): self.cancelled.append(oid)
    def modify(self, t, *, sl, tp=0.0): pass
    def close_partial(self, t, q): pass
    def last_response(self): return self._last_response
    def fills(self):
        if self._stale_fill is not None:
            yield self._stale_fill
            self._stale_fill = None
    def positions(self): return []


def test_slow_ack_with_stale_prior_response_does_not_orphan() -> None:
    """Orphan cause #2 (2026-07 ticket 2146419695): a prior order left a stale
    success/price/ticket AND this OPEN slow-acks. The recovered fill must win —
    NOT the stale fill — and no bogus cancel of the prior ticket may fire.

    The real fix has two halves; this test drives the WRAPPER half (recovered
    fill authoritative). The adapter half (clearing _last_response so fills()
    is empty on a raising submit) is covered in test_dwx_broker."""
    broker = _StaleAckBroker()
    bridge = _SlowAckBridge()  # open_orders → recovered ticket 2126588609
    config = LiveSafetyConfig(require_demo=False, max_entry_slip_ratio=1.15,
                                kill_switch_path=__import__("pathlib").Path("/tmp/NEVER_EXISTS_KILLSWITCH"))
    safe = LiveSafetyBroker(broker, bridge, config, sizer=None)
    order = _order(side=1, entry=4166.18, sl=4119.77, tp=4389.6, qty=0.03,
                   tag="intraday_a_long_2026-07-03T02:15:00+00:00")

    tk = safe.submit_order(order)
    assert tk == "2126588609"                       # recovered the REAL ticket

    fills = list(safe.fills())
    assert len(fills) == 1, "recovered fill must be yielded (position exists)"
    assert fills[0].price == 4166.18, "must be the RECOVERED price, not stale 9999"
    assert fills[0].qty == 0.03
    assert broker.cancelled == [], "must NOT slip-reject / cancel the prior ticket"
