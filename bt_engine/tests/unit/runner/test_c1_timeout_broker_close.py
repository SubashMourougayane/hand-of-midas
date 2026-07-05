"""C1 FIX regression: walker TIMEOUT exit must close the real broker position.

Before the fix, on_close booked a TIMEOUT trade in the DB but never sent a broker
CLOSE — SL/TP are server-side (self-close) but TIMEOUT has no broker equivalent, so
the real MT5 position kept running unmanaged (orphan + phantom P&L).

These tests target the helper `_close_live_position_verified` in isolation:
  1. Position open -> sends cancel(ticket) -> confirmed gone -> True.
  2. Position already gone (SL/TP hit intrabar) -> no cancel, returns True.
  3. Slow-ack: cancel "raises" but the position clears on a later re-read -> True.
  4. Cancel truly fails, position stays open -> False (caller logs + journals).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import bt_engine.runner.live as live
from bt_engine.runner.live import _close_live_position_verified


@dataclass
class _Bridge:
    """Fake DwxBridge: open_orders() returns whatever we set. Sequence support so
    a ticket can 'disappear' after N reads (models slow-ack rewrite)."""
    states: list  # list of open_orders dicts, consumed left-to-right; last repeats
    reads: int = 0

    def open_orders(self):
        i = min(self.reads, len(self.states) - 1)
        self.reads += 1
        return self.states[i]


@dataclass
class _Broker:
    fail: bool = False
    cancelled: list = field(default_factory=list)

    def cancel(self, ticket: str) -> None:
        self.cancelled.append(ticket)
        if self.fail:
            raise RuntimeError("broker cancel failed")


def _open(ticket="555"):
    return {ticket: {"ticket": ticket, "volume": 0.1, "type": "buy"}}


def test_timeout_close_open_then_gone(monkeypatch):
    # open on first read, gone after cancel
    bridge = _Bridge(states=[_open(), {}])
    broker = _Broker()
    ok = _close_live_position_verified(broker, bridge, "555", attempts=2, backoff_s=0)
    assert ok is True
    assert broker.cancelled == ["555"]  # cancel WAS sent


def test_timeout_close_already_gone_no_cancel():
    # position already not open (SL/TP hit intrabar) -> no cancel needed
    bridge = _Bridge(states=[{}])
    broker = _Broker()
    ok = _close_live_position_verified(broker, bridge, "555", attempts=2, backoff_s=0)
    assert ok is True
    assert broker.cancelled == []  # never tried to cancel a gone position


def test_timeout_close_slow_ack_recovers():
    # cancel raises, but position clears on the 2nd re-read (slow-ack)
    bridge = _Bridge(states=[_open(), _open(), {}])
    broker = _Broker(fail=True)
    ok = _close_live_position_verified(broker, bridge, "555", attempts=4, backoff_s=0)
    assert ok is True
    assert broker.cancelled == ["555"]


def test_timeout_close_truly_fails():
    # position never leaves -> False (caller must journal TIMEOUT_CLOSE_FAILED)
    bridge = _Bridge(states=[_open()])
    broker = _Broker(fail=True)
    ok = _close_live_position_verified(broker, bridge, "555", attempts=3, backoff_s=0)
    assert ok is False


def test_timeout_close_empty_ticket():
    bridge = _Bridge(states=[_open()])
    broker = _Broker()
    assert _close_live_position_verified(broker, bridge, "", attempts=2, backoff_s=0) is False
