"""Unit tests for DWXBrokerAdapter — fakes the bridge."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pytest

from bt_engine.core.order import Order
from bt_engine.execution.dwx_broker import DWXBrokerAdapter


@dataclass
class _FakeBridge:
    response: dict
    sent_commands: list[str] = field(default_factory=list)

    def send_command(self, command, *, wait_response=True, timeout_s=5.0):
        self.sent_commands.append(command)
        return self.response

    def open_orders(self):
        return {
            "1": {"symbol": "XAUUSD.ecn", "type": "BUY", "volume": 0.01,
                  "open_price": 2000.0, "sl": 1990.0, "tp": 2020.0,
                  "profit": 0.0, "swap": 0.0, "magic": 200000,
                  "open_time": "2026.06.29 12:00:00", "comment": "tag"},
        }


def _order(side: int = 1) -> Order:
    return Order(
        symbol="XAUUSD.ecn", side=side, qty=0.01,
        intended_entry_bar=pd.Timestamp("2026-06-29T12:00:00Z"),
        stop_price=1990.0, take_profit=2020.0, risk_units=10.0,
        tag="zone_42", bracket_kind="1R",
    )


def test_submit_order_buy_writes_command() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12345, "price": 2000.0, "volume": 0.01, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    ticket = b.submit_order(_order(side=1))
    assert ticket == "12345"
    assert len(bridge.sent_commands) == 1
    cmd = bridge.sent_commands[0]
    assert cmd.startswith("OPEN|XAUUSD.ecn|BUY|0.01|0.0|1990.0|2020.0|zone_42")


def test_submit_order_sell() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12346, "price": 2000.0, "volume": 0.01, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    b.submit_order(_order(side=-1))
    assert bridge.sent_commands[0].startswith("OPEN|XAUUSD.ecn|SELL|")


def test_submit_order_failure_raises() -> None:
    bridge = _FakeBridge(response={"success": False, "retcode": 10004, "comment": "rejected"})
    b = DWXBrokerAdapter(bridge)
    with pytest.raises(RuntimeError, match="failed"):
        b.submit_order(_order())


def test_cancel_writes_close_command() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12345, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    b.cancel("12345")
    assert bridge.sent_commands[0] == "CLOSE|12345"


def test_modify_writes_command() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12345, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    b.modify("12345", sl=1995.0, tp=2025.0)
    assert bridge.sent_commands[0] == "MODIFY|12345|1995.0|2025.0"


def test_close_all_writes_command() -> None:
    bridge = _FakeBridge(response={"success": True})
    b = DWXBrokerAdapter(bridge)
    b.close_all()
    assert bridge.sent_commands[0] == "CLOSE_ALL|"


def test_close_partial_writes_command() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12345, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    b.close_partial("12345", 0.18)
    assert bridge.sent_commands[0] == "CLOSE_PARTIAL|12345|0.18"


def test_close_partial_failure_raises() -> None:
    bridge = _FakeBridge(response={"success": False, "error": "no volume"})
    b = DWXBrokerAdapter(bridge)
    with pytest.raises(RuntimeError, match="close_partial failed"):
        b.close_partial("12345", 0.05)


def test_positions_returns_open_orders() -> None:
    bridge = _FakeBridge(response={"success": True})
    b = DWXBrokerAdapter(bridge)
    pos = b.positions()
    assert len(pos) == 1
    assert pos[0]["symbol"] == "XAUUSD.ecn"


def test_fills_yields_synthetic_from_last_response() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12345, "price": 2000.5, "volume": 0.01, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    b.submit_order(_order())
    fills = list(b.fills())
    assert len(fills) == 1
    assert fills[0].symbol == "XAUUSD.ecn"
    assert fills[0].side == 1
    assert fills[0].price == 2000.5
    assert fills[0].qty == 0.01


def test_fills_missing_price_yields_no_malformed_fill() -> None:
    bridge = _FakeBridge(response={"success": True, "ticket": 12345, "volume": 0.01, "retcode": 10009})
    b = DWXBrokerAdapter(bridge)
    b.submit_order(_order())
    assert list(b.fills()) == []


@dataclass
class _RaiseOnSecondBridge:
    """First send_command succeeds; the next one raises (slow-ack timeout)."""
    response: dict
    calls: int = 0

    def send_command(self, command, *, wait_response=True, timeout_s=5.0):
        self.calls += 1
        if self.calls >= 2:
            raise TimeoutError("No response within 5.0s")
        return self.response

    def open_orders(self):
        return {}


def test_raising_submit_clears_stale_response() -> None:
    """Orphan cause #2 adapter half (2026-07 ticket 2146419695): a PRIOR order
    left a stale success response; the NEXT OPEN slow-acks (send_command raises).
    _last_response MUST be cleared so fills() yields nothing for this order —
    else it synthesises a bogus fill at the prior order's price."""
    bridge = _RaiseOnSecondBridge(
        response={"success": True, "ticket": 111, "price": 9999.0, "volume": 0.01})
    b = DWXBrokerAdapter(bridge)
    b.submit_order(_order())                      # 1st: succeeds, primes stale state
    assert b.last_response().get("price") == 9999.0
    with pytest.raises(TimeoutError):
        b.submit_order(_order())                  # 2nd: slow-ack raises
    assert b.last_response() is None, "stale response must be cleared on a raising submit"
    assert list(b.fills()) == [], "no fill may be synthesised from a cleared response"
