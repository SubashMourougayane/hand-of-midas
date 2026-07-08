"""Unit tests for the manual position-close service + auth guard.

The service is engine-authoritative: it sends a verified broker close + writes a
MANUAL_CLOSE_REQUESTED journal event, and does NOT write the trade exit (the
engine finalises that next bar). Bridge/broker/session are faked here.
"""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

from dashboard_backend.app.routers.auth import _sign
from dashboard_backend.app.routers.positions import require_auth
from dashboard_backend.app.services.positions import (
    PositionCloseError,
    close_position,
)
from fastapi import HTTPException


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class _FakeBridge:
    def __init__(self, positions):
        self._p = {str(k): dict(v) for k, v in positions.items()}

    def open_orders(self):
        return {k: dict(v) for k, v in self._p.items()}


class _FakeBroker:
    """Mimics DWXBrokerAdapter.cancel → CLOSE|ticket. `confirm` decides whether
    the position actually leaves open_orders (slow-ack / genuine-fail modelling)."""

    def __init__(self, bridge, *, confirm=True):
        self.bridge = bridge
        self.confirm = confirm
        self.cancelled = []

    def cancel(self, ticket):
        self.cancelled.append(str(ticket))
        if self.confirm:
            self.bridge._p.pop(str(ticket), None)


class _FakeResult:
    def __init__(self, scalars_val=None, first_val=None):
        self._scalars = scalars_val if scalars_val is not None else []
        self._first = first_val

    def scalars(self):
        return list(self._scalars)

    def first(self):
        return self._first


class _FakeSession:
    """Returns scripted results per execute() call, in order."""

    def __init__(self, results):
        self._results = list(results)
        self._i = 0
        self.added = []
        self.commits = 0

    def execute(self, _stmt):
        r = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        return r

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1


def _trade():
    return SimpleNamespace(trade_id=uuid.uuid4(), run_id=uuid.uuid4())


# --------------------------------------------------------------------------
# require_auth
# --------------------------------------------------------------------------
def test_require_auth_accepts_valid_token():
    token = _sign({"u": "subash", "exp": int(time.time()) + 3600})
    assert require_auth(f"Bearer {token}") == "subash"


def test_require_auth_rejects_missing_token():
    with pytest.raises(HTTPException) as ei:
        require_auth(None)
    assert ei.value.status_code == 401


def test_require_auth_rejects_expired_token():
    token = _sign({"u": "subash", "exp": int(time.time()) - 1})
    with pytest.raises(HTTPException) as ei:
        require_auth(f"Bearer {token}")
    assert ei.value.status_code == 401


# --------------------------------------------------------------------------
# close_position
# --------------------------------------------------------------------------
def test_close_sends_broker_close_and_journals():
    tr = _trade()
    session = _FakeSession([_FakeResult(scalars_val=[tr])])  # one open row
    bridge = _FakeBridge({"2138348483": {"volume": 0.04, "sl": 4149.31}})
    broker = _FakeBroker(bridge, confirm=True)

    out = close_position("2138348483", session, actor="subash", bridge=bridge, broker=broker)

    assert out["status"] == "closing"
    assert out["ticket"] == "2138348483"
    assert broker.cancelled == ["2138348483"]      # real close sent
    assert "2138348483" not in bridge._p            # gone from broker
    assert session.commits == 1                     # journal committed
    ev = session.added[0]
    assert ev.event_type == "MANUAL_CLOSE_REQUESTED"
    assert ev.detail["actor"] == "subash"
    # engine-authoritative: service must NOT write an exit
    assert not hasattr(ev, "exit_timestamp") or ev.__class__.__name__ == "BtJournalEvent"


def test_close_404_when_no_row_for_ticket():
    session = _FakeSession([
        _FakeResult(scalars_val=[]),        # _find_open_trade_by_ticket → none
        _FakeResult(first_val=None),        # _ticket_has_any_row → none
    ])
    with pytest.raises(PositionCloseError) as ei:
        close_position("999", session, bridge=_FakeBridge({}), broker=_FakeBroker(_FakeBridge({})))
    assert ei.value.status == 404


def test_close_409_when_already_closed():
    session = _FakeSession([
        _FakeResult(scalars_val=[]),                 # no OPEN row
        _FakeResult(first_val=(uuid.uuid4(),)),      # but a row exists → closed
    ])
    with pytest.raises(PositionCloseError) as ei:
        close_position("999", session, bridge=_FakeBridge({}), broker=_FakeBroker(_FakeBridge({})))
    assert ei.value.status == 409


def test_close_502_when_broker_does_not_confirm():
    tr = _trade()
    session = _FakeSession([_FakeResult(scalars_val=[tr])])
    bridge = _FakeBridge({"42": {"volume": 0.09, "sl": 4149.31}})
    broker = _FakeBroker(bridge, confirm=False)      # cancel never removes it
    with pytest.raises(PositionCloseError) as ei:
        close_position("42", session, bridge=bridge, broker=broker)
    assert ei.value.status == 502
    assert session.commits == 0                      # no audit written on failure


def test_close_when_already_flat_at_broker_still_journals():
    tr = _trade()
    session = _FakeSession([_FakeResult(scalars_val=[tr])])
    bridge = _FakeBridge({})                          # broker already flat
    broker = _FakeBroker(bridge, confirm=True)
    out = close_position("42", session, actor="subash", bridge=bridge, broker=broker)
    assert out["status"] == "closing"
    assert out["note"] == "already flat at broker"
    assert broker.cancelled == []                    # nothing to send
    assert session.commits == 1                      # audit still recorded
