"""Manual position-close service — engine-authoritative design.

The dashboard can request a live position be closed. To avoid a split-brain with
the live engine (which owns the in-memory Model-B equity sizer and is the sole
writer of trade exits), this service does exactly TWO things:

  1. Sends a REAL close to the broker (DWX `CLOSE|<ticket>`) and VERIFIES the
     position left open_orders — reusing the engine's slow-ack-safe helper.
  2. Records a `MANUAL_CLOSE_REQUESTED` journal event (audit trail: who + when).

It deliberately does NOT write the trade's exit row, P&L, or touch the equity
sizer. On the next M15 bar the engine's existing `_broker_closed_outcomes`
detector sees the ticket gone, books the DB exit (real broker $ via reconcile)
AND updates the sizer — the same proven path that books any broker-side close.

Net effect: broker closes instantly; the trade row finalises with broker-exact
P&L within one bar (≤15 min). Single writer, no double-count.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.db.models import BtRun, BtTrade
from bt_engine.db.repo import JournalRepo
from bt_engine.execution.dwx_broker import DWXBrokerAdapter
# Reuse the engine's slow-ack-safe close+verify + live-position reader so the
# dashboard and the engine share ONE close discipline (no divergent logic).
from bt_engine.runner.live import _close_live_position_verified, _live_position

log = logging.getLogger("dashboard.positions")


class PositionCloseError(Exception):
    """Carries an HTTP status + message for the router to surface."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _find_open_trade_by_ticket(session: Session, ticket: str) -> BtTrade | None:
    """The still-open bt_trade row for `ticket`, preferring the one on an ACTIVE
    live run (a re-adopt writes a 2nd open row under a fresh run — the active
    run's row is the one the engine is currently managing)."""
    rows = list(
        session.execute(
            select(BtTrade)
            .where(BtTrade.broker_ticket == str(ticket))
            .where(BtTrade.exit_timestamp.is_(None))
        ).scalars()
    )
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    active_run_ids = {
        r.run_id
        for r in session.execute(
            select(BtRun).where(BtRun.mode == "live").where(BtRun.end_ts.is_(None))
        ).scalars()
    }
    for t in rows:
        if t.run_id in active_run_ids:
            return t
    return rows[0]


def _ticket_has_any_row(session: Session, ticket: str) -> bool:
    return (
        session.execute(
            select(BtTrade.trade_id).where(BtTrade.broker_ticket == str(ticket)).limit(1)
        ).first()
        is not None
    )


def _journal_manual_close(
    session: Session, trade: BtTrade, ticket: str, actor: str, *, note: str | None = None
) -> None:
    detail = {
        "broker_ticket": str(ticket),
        "actor": actor,
        "source": "dashboard_manual_close",
    }
    if note:
        detail["note"] = note
    JournalRepo(session).insert(
        trade_id=trade.trade_id,
        run_id=trade.run_id,
        ts=datetime.now(timezone.utc),
        event_type="MANUAL_CLOSE_REQUESTED",
        detail=detail,
    )
    session.commit()


def close_position(
    ticket: str,
    session: Session,
    *,
    actor: str = "dashboard",
    bridge: DwxBridge | None = None,
    broker: object | None = None,
) -> dict:
    """Request a manual close of the live position `ticket`.

    `bridge` / `broker` are injectable for testing; production uses the real DWX
    bridge (auto-resolves the Common/Files/DWX dir on the VPS).

    Raises PositionCloseError(status, message) on any refusal.
    """
    ticket = str(ticket).strip()
    if not ticket:
        raise PositionCloseError(400, "ticket required")

    trade = _find_open_trade_by_ticket(session, ticket)
    if trade is None:
        if _ticket_has_any_row(session, ticket):
            raise PositionCloseError(409, "position already closed")
        raise PositionCloseError(404, "no open trade for that ticket")

    bridge = bridge or DwxBridge()
    broker = broker or DWXBrokerAdapter(bridge)

    # Already flat at the broker? (SL/TP wick beat us to it.) Nothing to send —
    # the engine's broker-closed detector will book it. Still leave the audit.
    if _live_position(bridge, ticket) is None:
        _journal_manual_close(session, trade, ticket, actor, note="already_flat_at_broker")
        log.info("[MANUAL_CLOSE] ticket=%s already flat at broker; engine will book", ticket)
        return {
            "status": "closing",
            "ticket": ticket,
            "trade_id": str(trade.trade_id),
            "note": "already flat at broker",
        }

    ok = _close_live_position_verified(broker, bridge, ticket)
    if not ok:
        log.error("[MANUAL_CLOSE] ticket=%s broker did not confirm close", ticket)
        raise PositionCloseError(
            502, "broker did not confirm the close — position may still be open, retry"
        )

    _journal_manual_close(session, trade, ticket, actor)
    log.info("[MANUAL_CLOSE] ticket=%s closed at broker by actor=%s; engine will finalise", ticket, actor)
    return {"status": "closing", "ticket": ticket, "trade_id": str(trade.trade_id)}
