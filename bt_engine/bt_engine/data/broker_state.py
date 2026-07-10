"""Single source of truth for LIVE broker STATE — MT5 open positions.

ONE reader that BOTH the engine (H1 broker-closed detection) and the dashboard
(open-positions list) call, so they can never disagree about "is this open".

Design law (see RCA 2026-07-05):
  - MT5 = truth for STATE (open? entry? sl/tp? volume? P&L?).
  - Strategy = truth for DECISIONS (bar-close only — not here).
  - DB = truth for PROVENANCE/history (why the trade exists — not here).

This module ONLY answers the STATE question. Two layers:
  - `parse_open_positions(raw)`  — PURE function, no I/O. Normalizes the raw
    open_orders.json dict into a list of Position dataclasses. Fully unit-tested.
  - `read_open_positions(...)`   — thin I/O wrapper: read the JSON (via a bridge or
    a file path), then parse. Never raises — returns [] on any read/parse failure
    (conservative: a bad read must NEVER be interpreted as "all positions closed").

The raw open_orders.json shape (MT5/DWX EA), keyed by ticket:
    { "<ticket>": {"symbol","type","volume","open_price"|"price_open",
                   "sl","tp","open_time","profit","comment", ...}, ... }
Some EAs wrap the map under an "orders" key — handled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class Position:
    """Normalized live broker position — MT5 truth."""
    ticket: str
    symbol: str
    side: int              # +1 long, -1 short
    volume: float          # lots
    entry_price: float
    sl: Optional[float]    # None if not set (0/none)
    tp: Optional[float]
    open_time: Optional[str]   # raw broker string (server-local); caller converts
    profit: Optional[float]    # MT5 unrealized $ (may be absent)
    comment: str
    raw: dict              # untouched original record (for callers needing more)


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _side_from_type(t: Any) -> int:
    """MT5 position type → side. BUY/0 = long, SELL/1 = short."""
    s = str(t).strip().upper()
    return 1 if s in {"BUY", "0", "POSITION_TYPE_BUY"} else -1


def _inner_map(raw: Any) -> dict:
    """Extract the ticket→record map, tolerating an 'orders' wrapper."""
    if not isinstance(raw, dict):
        return {}
    if "orders" in raw and isinstance(raw["orders"], dict):
        return raw["orders"]
    return raw


def parse_open_positions(raw: Any, *, symbol: Optional[str] = None) -> list[Position]:
    """PURE: normalize open_orders.json content into Position list.

    - Tolerates the 'orders' wrapper and non-dict junk (returns []).
    - ticket taken from the map KEY (authoritative), falling back to record fields.
    - Filters to `symbol` if given (else returns all).
    - Skips records with no usable volume or entry price (not a real position).
    - sl/tp of 0/none → None.
    """
    inner = _inner_map(raw)
    out: list[Position] = []
    for key, rec in inner.items():
        if not isinstance(rec, dict):
            continue
        ticket = str(key) if key not in (None, "") else str(
            rec.get("ticket") or rec.get("id") or rec.get("position_id") or ""
        )
        if not ticket:
            continue
        # Recover the true unsigned ticket from the EA's signed-int32 wrap so it
        # matches the (normalized) broker_ticket stored in the DB. See dwx_bridge.
        from .dwx_bridge import normalize_ticket
        ticket = str(normalize_ticket(ticket))
        sym = str(rec.get("symbol") or symbol or "")
        if symbol is not None and sym and sym != symbol:
            continue
        vol = _f(rec.get("volume"))
        entry = _f(rec.get("open_price"))
        if entry is None:
            entry = _f(rec.get("price_open"))
        if not vol or vol <= 0 or entry is None or entry <= 0:
            continue  # not a real open position
        sl = _f(rec.get("sl"))
        if sl is not None and sl == 0:
            sl = None
        tp = _f(rec.get("tp"))
        if tp is not None and tp == 0:
            tp = None
        out.append(Position(
            ticket=ticket,
            symbol=sym,
            side=_side_from_type(rec.get("type")),
            volume=float(vol),
            entry_price=float(entry),
            sl=sl,
            tp=tp,
            open_time=(str(rec.get("open_time")) if rec.get("open_time") else None),
            profit=_f(rec.get("profit")),
            comment=str(rec.get("comment") or ""),
            raw=dict(rec),
        ))
    return out


def open_tickets(raw: Any) -> set[str]:
    """PURE: just the set of open ticket ids (fast path for H1 gone-check)."""
    return {p.ticket for p in parse_open_positions(raw)}


# ---------------------------------------------------------------------------
# I/O wrappers — never raise; a failed read returns [] / empty set so a bad read
# is NEVER interpreted as "everything closed".
# ---------------------------------------------------------------------------
def read_open_positions_from_bridge(bridge, *, symbol: Optional[str] = None) -> list[Position]:
    try:
        raw = bridge.open_orders()
    except Exception:
        return []
    return parse_open_positions(raw, symbol=symbol)


def read_open_positions_from_file(path: "str | Path", *, symbol: Optional[str] = None) -> list[Position]:
    try:
        p = Path(path)
        if not p.is_file():
            return []
        raw = json.loads(p.read_text())
    except Exception:
        return []
    return parse_open_positions(raw, symbol=symbol)


def open_tickets_from_bridge(bridge) -> Optional[set[str]]:
    """Return the set of open tickets, or None if the read FAILED (distinct from
    an empty set = 'read ok, genuinely no positions'). H1 must treat None as
    'unknown → do nothing', never as 'all closed'."""
    try:
        raw = bridge.open_orders()
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return open_tickets(raw)
