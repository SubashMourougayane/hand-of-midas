"""Unit tests for the shared MT5-truth broker-state reader.

Covers the PURE parser branch-by-branch + the fail-safe I/O contract (a bad read
must NEVER look like 'all positions closed').
"""
from __future__ import annotations

from bt_engine.data.broker_state import (
    Position, parse_open_positions, open_tickets,
    read_open_positions_from_file, open_tickets_from_bridge,
)


def _rec(**kw):
    base = {"symbol": "XAUUSD.ecn", "type": "BUY", "volume": 0.1,
            "open_price": 2000.0, "sl": 1995.0, "tp": 2015.0,
            "open_time": "2026.07.05 12:00:00", "profit": 3.2, "comment": "intraday_a_long_x"}
    base.update(kw)
    return base


def test_basic_long_position():
    raw = {"111": _rec()}
    pos = parse_open_positions(raw)
    assert len(pos) == 1
    p = pos[0]
    assert p.ticket == "111" and p.side == 1 and p.volume == 0.1
    assert p.entry_price == 2000.0 and p.sl == 1995.0 and p.tp == 2015.0
    assert p.profit == 3.2 and p.symbol == "XAUUSD.ecn"


def test_short_side_mapping():
    for t in ("SELL", "1", "POSITION_TYPE_SELL", "sell"):
        p = parse_open_positions({"9": _rec(type=t)})[0]
        assert p.side == -1, t
    for t in ("BUY", "0", "buy"):
        p = parse_open_positions({"9": _rec(type=t)})[0]
        assert p.side == 1, t


def test_orders_wrapper():
    raw = {"orders": {"111": _rec()}}
    assert open_tickets(raw) == {"111"}


def test_sl_tp_zero_becomes_none():
    p = parse_open_positions({"1": _rec(sl=0, tp=0)})[0]
    assert p.sl is None and p.tp is None


def test_price_open_fallback():
    r = _rec()
    del r["open_price"]
    r["price_open"] = 1999.0
    p = parse_open_positions({"1": r})[0]
    assert p.entry_price == 1999.0


def test_skips_zero_volume_and_zero_entry():
    assert parse_open_positions({"1": _rec(volume=0)}) == []
    assert parse_open_positions({"1": _rec(open_price=0)}) == []
    # missing both entry sources (no open_price, no price_open)
    r = _rec(); r.pop("open_price", None)
    assert parse_open_positions({"1": r}) == []


def test_symbol_filter():
    raw = {"1": _rec(symbol="XAUUSD.ecn"), "2": _rec(symbol="EURUSD")}
    got = parse_open_positions(raw, symbol="XAUUSD.ecn")
    assert {p.ticket for p in got} == {"1"}


def test_junk_inputs_return_empty():
    assert parse_open_positions(None) == []
    assert parse_open_positions([]) == []
    assert parse_open_positions("garbage") == []
    assert parse_open_positions({"1": "not-a-dict"}) == []


def test_ticket_from_key_authoritative():
    # record has a different 'ticket' field; the MAP KEY wins
    p = parse_open_positions({"KEYWIN": _rec(ticket="999")})[0]
    assert p.ticket == "KEYWIN"


def test_open_tickets_set():
    raw = {"1": _rec(), "2": _rec(symbol="EURUSD"), "3": _rec(volume=0)}
    # ticket 3 skipped (zero vol); 1 and 2 kept
    assert open_tickets(raw) == {"1", "2"}


def test_read_from_file_missing_returns_empty(tmp_path):
    assert read_open_positions_from_file(tmp_path / "nope.json") == []


def test_read_from_file_ok(tmp_path):
    import json
    f = tmp_path / "open_orders.json"
    f.write_text(json.dumps({"111": _rec()}))
    got = read_open_positions_from_file(f)
    assert len(got) == 1 and got[0].ticket == "111"


def test_read_from_file_corrupt_returns_empty(tmp_path):
    f = tmp_path / "open_orders.json"
    f.write_text("{ not valid json")
    assert read_open_positions_from_file(f) == []


class _GoodBridge:
    def open_orders(self):
        return {"111": _rec()}


class _FailBridge:
    def open_orders(self):
        raise RuntimeError("bridge down")


class _EmptyBridge:
    def open_orders(self):
        return {}


def test_open_tickets_from_bridge_distinguishes_fail_vs_empty():
    # FAIL -> None (unknown; H1 must NOT treat as all-closed)
    assert open_tickets_from_bridge(_FailBridge()) is None
    # EMPTY -> set() (read ok, genuinely no positions)
    assert open_tickets_from_bridge(_EmptyBridge()) == set()
    # GOOD -> the tickets
    assert open_tickets_from_bridge(_GoodBridge()) == {"111"}
