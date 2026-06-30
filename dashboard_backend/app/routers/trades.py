"""GET /api/trades/{id}, /journal, /bar-walk."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bt_engine.db.models import BtBarWalk, BtJournalEvent, BtTrade

from ..deps import get_session
from .runs import _trade_to_dict

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/{trade_id}")
def trade_detail(trade_id: UUID, s: Session = Depends(get_session)) -> dict:
    t = s.get(BtTrade, trade_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trade not found")
    return _trade_to_dict(t)


@router.get("/{trade_id}/journal")
def trade_journal(trade_id: UUID, s: Session = Depends(get_session)) -> list[dict]:
    q = (
        select(BtJournalEvent)
        .where(BtJournalEvent.trade_id == trade_id)
        .order_by(BtJournalEvent.ts.asc(), BtJournalEvent.event_id.asc())
    )
    rows = s.execute(q).scalars().all()
    return [
        {
            "event_id": e.event_id,
            "ts": e.ts.isoformat(),
            "event_type": e.event_type,
            "detail": e.detail,
        }
        for e in rows
    ]


@router.get("/{trade_id}/bar-walk")
def trade_bar_walk(trade_id: UUID, s: Session = Depends(get_session)) -> list[dict]:
    q = (
        select(BtBarWalk)
        .where(BtBarWalk.trade_id == trade_id)
        .order_by(BtBarWalk.bar_ts.asc())
    )
    rows = s.execute(q).scalars().all()
    return [
        {
            "bar_ts": r.bar_ts.isoformat(),
            "phase": r.phase,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "mfe_r": float(r.mfe_r) if r.mfe_r is not None else None,
            "mae_r": float(r.mae_r) if r.mae_r is not None else None,
            "unrealised_r": float(r.unrealised_r) if r.unrealised_r is not None else None,
            "distance_to_entry_r": float(r.distance_to_entry_r) if r.distance_to_entry_r is not None else None,
            "distance_to_stop_r": float(r.distance_to_stop_r) if r.distance_to_stop_r is not None else None,
            "distance_to_tp_r": float(r.distance_to_tp_r) if r.distance_to_tp_r is not None else None,
        }
        for r in rows
    ]
