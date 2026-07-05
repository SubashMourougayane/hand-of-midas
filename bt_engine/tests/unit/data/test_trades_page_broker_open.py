"""Proves the Trades-page broker_open semantics (Option-A on the ledger).

Mirrors dashboard runs._trade_to_dict's broker_open computation against the shared
reader, so the MT5-truth override of stale SUPERSEDED/closed rows is covered by the
bt_engine suite (dashboard has no pytest infra).
"""
from __future__ import annotations

import json

from bt_engine.data.broker_state import parse_open_positions


def _mt5_open_tickets(path):
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text())
    except Exception:
        return None
    return {p.ticket for p in parse_open_positions(raw)}


def _broker_open(mt5_open, broker_ticket):
    """Exact copy of runs._trade_to_dict broker_open logic."""
    if mt5_open is None:
        return None
    tkt = (broker_ticket or "").strip()
    if not tkt:
        return None
    return tkt in mt5_open


def _status_is_open(broker_open, exit_timestamp):
    """Exact copy of TradesPage status: broker_open true → OPEN, false → closed,
    null → trust DB exit_timestamp."""
    return broker_open is True or (broker_open is None and exit_timestamp is None)


def _rec(t):
    return {t: {"ticket": t, "type": "buy", "volume": 0.1, "open_price": 2000.0,
                "sl": 1995.0, "tp": 2015.0}}


def test_superseded_row_still_held_by_broker_shows_open(tmp_path):
    # The screenshot bug: DB row SUPERSEDED (has exit_timestamp) but MT5 STILL holds it.
    f = tmp_path / "open_orders.json"
    f.write_text(json.dumps(_rec("2118599832")))
    mt5 = _mt5_open_tickets(f)
    bo = _broker_open(mt5, "2118599832")
    assert bo is True
    # even though the DB row was closed/superseded, status = OPEN (MT5 truth)
    assert _status_is_open(bo, exit_timestamp="2026-07-03T15:30:00") is True


def test_db_open_but_broker_closed_shows_closed(tmp_path):
    # DB says open (no exit) but broker no longer holds it → NOT open anymore.
    f = tmp_path / "open_orders.json"
    f.write_text(json.dumps(_rec("111")))  # only 111 open
    mt5 = _mt5_open_tickets(f)
    bo = _broker_open(mt5, "999")
    assert bo is False
    assert _status_is_open(bo, exit_timestamp=None) is False


def test_unknown_read_trusts_db(tmp_path):
    mt5 = _mt5_open_tickets(tmp_path / "absent.json")  # None
    assert _broker_open(mt5, "111") is None
    # falls back to DB exit_timestamp
    assert _status_is_open(None, exit_timestamp=None) is True       # DB open
    assert _status_is_open(None, exit_timestamp="2026-01-01") is False  # DB closed


def test_no_ticket_trusts_db(tmp_path):
    f = tmp_path / "open_orders.json"
    f.write_text(json.dumps(_rec("111")))
    mt5 = _mt5_open_tickets(f)
    assert _broker_open(mt5, "") is None
    assert _broker_open(mt5, None) is None


def test_corrupt_file_trusts_db(tmp_path):
    f = tmp_path / "open_orders.json"
    f.write_text("{ bad json")
    assert _mt5_open_tickets(f) is None  # fail-safe: never 'all closed'
