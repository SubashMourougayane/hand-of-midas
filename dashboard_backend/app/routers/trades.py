"""GET /api/trades/{id}, /journal, /bar-walk."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import timedelta

from bt_engine.db.models import BtBarWalk, BtJournalEvent, BtSignal, BtTrade

from ..deps import get_session
from .runs import _trade_to_dict

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/{trade_id}")
def trade_detail(trade_id: UUID, s: Session = Depends(get_session)) -> dict:
    t = s.get(BtTrade, trade_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trade not found")
    return _trade_to_dict(t)


def _resolve_trade_id_with_source(s: Session, trade_id: UUID) -> UUID:
    """Combined-replay trades reference their A/D source.
    Prefer raw_features.source_trade_id, fall back to parsing trade_ref
    (legacy combo trades carry source UUID inline: COMBO-FIB-INTRADAY-X-<uuid>)."""
    t = s.get(BtTrade, trade_id)
    if t is None:
        return trade_id
    rf = t.raw_features or {}
    src = rf.get("source_trade_id")
    if src:
        try:
            return UUID(str(src))
        except Exception:
            pass
    # Fallback — parse from trade_ref prefix.
    ref = t.trade_ref or ""
    if ref.startswith("COMBO-FIB-INTRADAY-"):
        # COMBO-FIB-INTRADAY-{A|D}-{uuid}
        parts = ref.split("-", 4)
        if len(parts) >= 5:
            try:
                return UUID(parts[4])
            except Exception:
                pass
    return trade_id


@router.get("/{trade_id}/journal")
def trade_journal(trade_id: UUID, s: Session = Depends(get_session)) -> list[dict]:
    # First check direct events. If empty, follow source_trade_id.
    q = (
        select(BtJournalEvent)
        .where(BtJournalEvent.trade_id == trade_id)
        .order_by(BtJournalEvent.ts.asc(), BtJournalEvent.event_id.asc())
    )
    rows = s.execute(q).scalars().all()
    if not rows:
        src = _resolve_trade_id_with_source(s, trade_id)
        if src != trade_id:
            q2 = (
                select(BtJournalEvent)
                .where(BtJournalEvent.trade_id == src)
                .order_by(BtJournalEvent.ts.asc(), BtJournalEvent.event_id.asc())
            )
            rows = s.execute(q2).scalars().all()
    if rows:
        return [
            {
                "event_id": e.event_id,
                "ts": e.ts.isoformat(),
                "event_type": e.event_type,
                "detail": e.detail,
            }
            for e in rows
        ]

    # FALLBACK: synthesize a journal from bt_signals (gate events) in the
    # source run, filtered to a window around entry_timestamp. Backtests
    # without a wired BarWalkJournal don't write trade-scoped journal events,
    # but bt_signals carries every gate decision for the run.
    t = s.get(BtTrade, trade_id)
    if t is None or t.entry_timestamp is None:
        return []
    source_run_id = (t.raw_features or {}).get("source_run_id") if t.raw_features else None
    if not source_run_id:
        # If we resolved trade_id from trade_ref prefix above, look up that
        # source trade's run_id.
        src_tid = _resolve_trade_id_with_source(s, trade_id)
        if src_tid != trade_id:
            src_trade = s.get(BtTrade, src_tid)
            if src_trade:
                source_run_id = src_trade.run_id
    target_run_id = source_run_id or t.run_id
    leg = t.leg
    # 6h window before entry to capture the pivot → setup → confirm flow
    t0 = t.entry_timestamp - timedelta(hours=6)
    t1 = t.exit_timestamp + timedelta(minutes=5) if t.exit_timestamp else t.entry_timestamp + timedelta(hours=24)
    q3 = (
        select(BtSignal)
        .where(BtSignal.run_id == target_run_id)
        .where(BtSignal.ts >= t0)
        .where(BtSignal.ts <= t1)
        .order_by(BtSignal.ts.asc(), BtSignal.signal_id.asc())
    )
    sigs = s.execute(q3).scalars().all()
    # Filter by leg in detail if possible (gate events have detail.leg).
    out = []
    for sig in sigs:
        det = sig.detail or {}
        if leg and det.get("leg") and det.get("leg") != leg:
            continue
        out.append({
            "event_id": sig.signal_id,
            "ts": sig.ts.isoformat(),
            "event_type": sig.status,
            "detail": det,
        })
    return out


@router.get("/{trade_id}/bar-walk")
def trade_bar_walk(trade_id: UUID, s: Session = Depends(get_session)) -> list[dict]:
    q = (
        select(BtBarWalk)
        .where(BtBarWalk.trade_id == trade_id)
        .order_by(BtBarWalk.bar_ts.asc())
    )
    rows = s.execute(q).scalars().all()
    if not rows:
        src = _resolve_trade_id_with_source(s, trade_id)
        if src != trade_id:
            q2 = (
                select(BtBarWalk)
                .where(BtBarWalk.trade_id == src)
                .order_by(BtBarWalk.bar_ts.asc())
            )
            rows = s.execute(q2).scalars().all()
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
