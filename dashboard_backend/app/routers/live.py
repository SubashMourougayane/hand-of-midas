"""GET /api/live/summary — ONE call powering the whole Live cockpit.

Replaces the frontend's N+1 fan-out (it looped over EVERY historical run of each
active strategy — dozens after restart churn — firing open + closed(5000-row)
queries at each, most dead runs returning []). That saturated the DB pool and
piled up hundreds of pending requests.

This endpoint does it all in a handful of set-based queries:
  - active live strategies (runs with end_ts IS NULL)
  - open trades across ALL runs of those strategies, deduped by broker_ticket
  - realized-today = Σ broker_net_usd of trades closed since 00:00 UTC, deduped
  - freshest account snapshot across those runs
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from bt_engine.db.models import BtRun, BtTrade, BtAccountSnapshot

from bt_engine.data.broker_state import (
    read_open_positions_from_file, parse_open_positions,
)

from ..deps import get_session
from ..ws.price_stream import ACCOUNT_FILE, OPEN_ORDERS_FILE
from .runs import _trade_to_dict, _run_to_summary


def _mt5_open_tickets() -> set[str] | None:
    """MT5 = source of truth for OPEN positions. Returns the set of open tickets,
    or None if the file can't be read OR is corrupt/unparseable (unknown → callers
    must NOT treat as 'all closed'; fall back to the DB view). Only a file that is
    present AND valid JSON yields a set (possibly empty = genuinely no positions)."""
    try:
        if not OPEN_ORDERS_FILE.is_file():
            return None
        raw = json.loads(OPEN_ORDERS_FILE.read_text())
    except Exception:
        return None  # missing / unreadable / corrupt → unknown, keep DB view
    return {p.ticket for p in parse_open_positions(raw)}

router = APIRouter(prefix="/api/live", tags=["live"])


def _mt5_account_info() -> dict:
    """MT5 account_info.json — source of truth for margin/leverage/equity. Read
    directly (not via WS) so the Live cockpit's Capital Deployed + per-trade
    margin populate even on a CLOSED market (WS account_live is tick-driven and
    silent on weekends/holidays; the file still holds the last-known values)."""
    try:
        if ACCOUNT_FILE.is_file():
            a = json.loads(ACCOUNT_FILE.read_text())
            if isinstance(a, dict):
                return a
    except Exception:
        pass
    return {}


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@router.get("/summary")
def live_summary(s: Session = Depends(get_session)) -> dict:
    # 1) Active live strategies + their run_ids.
    active_runs = s.execute(
        select(BtRun).where(BtRun.mode == "live").where(BtRun.end_ts.is_(None))
    ).scalars().all()
    active_strats = {r.strategy_id for r in active_runs}
    if not active_strats:
        return {"legs": [], "realized_today_usd": 0.0, "account": None, "server_ts": _now_iso()}

    # All runs (any state) belonging to those active strategies — one query.
    all_runs = s.execute(
        select(BtRun).where(BtRun.mode == "live").where(BtRun.strategy_id.in_(active_strats))
    ).scalars().all()
    run_ids = [r.run_id for r in all_runs]
    run_by_id = {r.run_id: r for r in all_runs}
    # The run we present per strategy = the currently-active one.
    active_by_strat = {r.strategy_id: r for r in active_runs}

    # 2) OPEN trades across all those runs, in ONE query. Dedup by broker_ticket
    #    (a re-adopt writes a 2nd row for the same ticket), keeping the row on the
    #    active run when there's a collision.
    open_rows = s.execute(
        select(BtTrade)
        .where(BtTrade.run_id.in_(run_ids))
        .where(BtTrade.exit_timestamp.is_(None))
        .order_by(BtTrade.entry_timestamp.desc())
    ).scalars().all()

    active_run_ids = {r.run_id for r in active_runs}
    best_by_key: dict[str, BtTrade] = {}
    for t in open_rows:
        key = (t.broker_ticket or "").strip() or str(t.trade_id)
        prev = best_by_key.get(key)
        if prev is None:
            best_by_key[key] = t
        else:
            # Prefer the row sitting on an active run.
            if t.run_id in active_run_ids and prev.run_id not in active_run_ids:
                best_by_key[key] = t

    # OPTION A — MT5 is the source of truth for OPEN positions. Filter the DB's
    # open rows to only those the broker STILL holds, so a mid-bar broker close
    # (SL/TP wick) vanishes from the cockpit INSTANTLY — no waiting for the engine's
    # per-bar H1 sweep to book it. If MT5 can't be read (None), keep the DB view
    # (never blank the board on a bad read). A DB-open row with NO broker_ticket
    # (never adopted) is kept — MT5 has nothing to check it against.
    mt5_open = _mt5_open_tickets()

    def _broker_still_holds(t: BtTrade) -> bool:
        if mt5_open is None:
            return True  # unknown → trust DB
        tkt = (t.broker_ticket or "").strip()
        if not tkt:
            return True  # no ticket to verify against MT5
        return tkt in mt5_open

    # Group deduped open trades by their strategy (via run).
    open_by_strat: dict[str, list[BtTrade]] = {}
    for t in best_by_key.values():
        if not _broker_still_holds(t):
            continue  # broker already closed it — MT5 truth wins
        run = run_by_id.get(t.run_id)
        if run is None:
            continue
        open_by_strat.setdefault(run.strategy_id, []).append(t)

    legs = []
    for strat, run in active_by_strat.items():
        trades = open_by_strat.get(strat, [])
        trades.sort(key=lambda t: (t.entry_timestamp or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        legs.append({
            "run": _run_to_summary(run).model_dump(mode="json"),
            "open_trades": [_trade_to_dict(t) for t in trades],
        })

    # 3) Realized-today = Σ broker_net_usd of trades CLOSED since 00:00 UTC, across
    #    those runs, deduped by broker_ticket. ONE query, date-filtered (not 5000 rows).
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    closed_today = s.execute(
        select(BtTrade)
        .where(BtTrade.run_id.in_(run_ids))
        .where(BtTrade.exit_timestamp.is_not(None))
        .where(BtTrade.exit_timestamp >= start_of_day)
    ).scalars().all()
    seen: set[str] = set()
    realized = 0.0
    for t in closed_today:
        key = (t.broker_ticket or "").strip() or str(t.trade_id)
        if key in seen:
            continue
        seen.add(key)
        realized += float(t.broker_net_usd or 0.0)

    # 4) Freshest account snapshot across those runs (A+D share one account).
    snap = s.execute(
        select(BtAccountSnapshot)
        .where(BtAccountSnapshot.run_id.in_(run_ids))
        .order_by(desc(BtAccountSnapshot.ts))
        .limit(1)
    ).scalars().first()
    # MT5 account_info.json = source of truth for margin/leverage/equity. Read it
    # directly so Capital Deployed + per-trade margin populate even on a closed
    # market. Prefer its live equity/balance over the (possibly stale) DB snapshot.
    mt5 = _mt5_account_info()
    account = None
    if snap is not None or mt5:
        account = {
            "ts": snap.ts.isoformat() if snap is not None else _now_iso(),
            "balance": _f(mt5.get("balance")) if mt5.get("balance") is not None
                       else (float(snap.balance) if snap is not None and snap.balance is not None else None),
            "equity": _f(mt5.get("equity")) if mt5.get("equity") is not None
                      else (float(snap.equity) if snap is not None and snap.equity is not None else None),
            "open_pnl": _f(mt5.get("profit")) if mt5.get("profit") is not None
                        else (float(snap.open_pnl) if snap is not None and snap.open_pnl is not None else None),
            "open_position": int(snap.open_position) if snap is not None and snap.open_position is not None else None,
            # MT5 truth — margin (capital deployed) + level + leverage.
            "margin": _f(mt5.get("margin")),
            "free_margin": _f(mt5.get("free_margin")),
            "margin_level": _f(mt5.get("margin_level")),
            "leverage": _f(mt5.get("leverage")),
        }

    return {
        "legs": legs,
        "realized_today_usd": round(realized, 2),
        "account": account,
        "server_ts": _now_iso(),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
