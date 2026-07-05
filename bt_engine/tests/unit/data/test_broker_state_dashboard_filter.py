"""Proves the Option-A dashboard filter semantics against the shared reader.

The dashboard keeps a DB-open trade in the live cockpit ONLY if MT5 still holds it
(mt5_open truth). Mirrors dashboard_backend live._broker_still_holds so the rule is
covered by the bt_engine suite (dashboard has no pytest infra).
"""
from __future__ import annotations

import json

from bt_engine.data.broker_state import read_open_positions_from_file


def _mt5_open_tickets(path):
    """Mirror of dashboard live._mt5_open_tickets: None on missing/corrupt file
    (fail-safe → keep DB view), else the set of open tickets."""
    import json as _json
    try:
        if not path.is_file():
            return None
        raw = _json.loads(path.read_text())
    except Exception:
        return None
    from bt_engine.data.broker_state import parse_open_positions
    return {p.ticket for p in parse_open_positions(raw)}


def _still_holds(mt5_open, broker_ticket):
    """Exact copy of the dashboard predicate."""
    if mt5_open is None:
        return True  # unknown → trust DB
    tkt = (broker_ticket or "").strip()
    if not tkt:
        return True  # no ticket to verify
    return tkt in mt5_open


def _rec(t):
    return {t: {"ticket": t, "type": "buy", "volume": 0.1, "open_price": 2000.0,
                "sl": 1995.0, "tp": 2015.0}}


def test_broker_closed_ticket_is_dropped(tmp_path):
    f = tmp_path / "open_orders.json"
    f.write_text(json.dumps(_rec("111")))  # only 111 open
    mt5 = _mt5_open_tickets(f)
    assert _still_holds(mt5, "111") is True    # still open → keep
    assert _still_holds(mt5, "999") is False   # broker closed it → drop instantly


def test_unknown_read_keeps_db_view(tmp_path):
    # file missing → None → keep DB rows (never blank the board)
    mt5 = _mt5_open_tickets(tmp_path / "absent.json")
    assert mt5 is None
    assert _still_holds(mt5, "111") is True
    assert _still_holds(mt5, "999") is True


def test_corrupt_read_keeps_db_view(tmp_path):
    # corrupt-but-present file → None (fail-safe) → keep DB view, do NOT blank board
    f = tmp_path / "open_orders.json"
    f.write_text("{ bad json")
    mt5 = _mt5_open_tickets(f)
    assert mt5 is None
    assert _still_holds(mt5, "111") is True
    assert _still_holds(mt5, "999") is True


def test_no_ticket_kept(tmp_path):
    f = tmp_path / "open_orders.json"
    f.write_text(json.dumps(_rec("111")))
    mt5 = _mt5_open_tickets(f)
    assert _still_holds(mt5, "") is True     # never-adopted trade, no ticket → keep
    assert _still_holds(mt5, None) is True
