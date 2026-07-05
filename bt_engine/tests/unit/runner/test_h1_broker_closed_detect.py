"""H1 FIX regression: detect positions the BROKER closed intrabar (wick through
server-side SL/TP) that the close-based walker would miss → engine stops managing
a ghost. MT5 open_orders = source of truth for open/closed.

Tests the detector `_broker_closed_outcomes` in isolation:
  1. Ticket gone from open_orders -> emits a BROKER_CLOSED outcome for that trade.
  2. Ticket still present -> no outcome (walker keeps managing).
  3. Trade with no broker_ticket -> skipped (leave to walker; nothing to check).
  4. open_orders read fails -> returns [] (never spurious-close on a bad read).
  5. Mixed: only the gone ticket is booked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from bt_engine.runner.live import _broker_closed_outcomes


@dataclass
class _Trade:
    broker_ticket: str | None
    side: int = 1
    entry_price: float = 2000.0
    risk_units: float = 2.0
    bars_held: int = 5


@dataclass
class _Bar:
    timestamp: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2026-07-05 12:00:00", tz="UTC"))
    close: float = 1998.0


@dataclass
class _Bridge:
    orders: dict
    raise_on_read: bool = False

    def open_orders(self):
        if self.raise_on_read:
            raise RuntimeError("bridge read failed")
        return self.orders


def _open(*tickets):
    return {t: {"ticket": t, "volume": 0.1} for t in tickets}


def test_gone_ticket_emits_broker_closed():
    tr = _Trade(broker_ticket="111")
    bridge = _Bridge(orders=_open("222"))  # 111 is gone
    out = _broker_closed_outcomes([tr], _Bar(), bridge)
    assert len(out) == 1
    t, oc = out[0]
    assert t is tr
    assert oc.reason == "BROKER_CLOSED"
    assert oc.event_type == "EXIT_BROKER_CLOSED"


def test_present_ticket_no_outcome():
    tr = _Trade(broker_ticket="111")
    bridge = _Bridge(orders=_open("111", "222"))
    assert _broker_closed_outcomes([tr], _Bar(), bridge) == []


def test_no_ticket_skipped():
    tr = _Trade(broker_ticket=None)
    bridge = _Bridge(orders=_open("222"))
    assert _broker_closed_outcomes([tr], _Bar(), bridge) == []


def test_bad_read_no_spurious_close():
    tr = _Trade(broker_ticket="111")
    bridge = _Bridge(orders={}, raise_on_read=True)
    assert _broker_closed_outcomes([tr], _Bar(), bridge) == []


def test_mixed_only_gone_booked():
    keep = _Trade(broker_ticket="111")
    gone = _Trade(broker_ticket="999", side=-1)
    bridge = _Bridge(orders=_open("111"))  # 999 gone
    out = _broker_closed_outcomes([keep, gone], _Bar(), bridge)
    assert len(out) == 1
    assert out[0][0] is gone


def test_orders_wrapped_in_orders_key():
    # some bridges wrap positions under an 'orders' key
    tr = _Trade(broker_ticket="111")
    bridge = _Bridge(orders={"orders": _open("222")})
    out = _broker_closed_outcomes([tr], _Bar(), bridge)
    assert len(out) == 1 and out[0][1].reason == "BROKER_CLOSED"
