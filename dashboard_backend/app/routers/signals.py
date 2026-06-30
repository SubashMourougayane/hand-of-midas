"""GET /api/signals/recent + /api/signals/funnel."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from bt_engine.db.models import BtSignal

from ..deps import get_session

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _signal_to_dict(s_: BtSignal) -> dict:
    return {
        "signal_id": s_.signal_id,
        "run_id": str(s_.run_id),
        "ts": s_.ts.isoformat(),
        "status": s_.status,
        "reason": s_.reason,
        "zone_id": s_.zone_id,
        "detail": s_.detail,
    }


@router.get("/recent")
def recent_signals(
    run_id: UUID | None = None,
    since: datetime | None = None,
    status_prefix: str | None = None,
    leg: str | None = None,
    limit: int = 200,
    s: Session = Depends(get_session),
) -> list[dict]:
    q = select(BtSignal).order_by(desc(BtSignal.ts), desc(BtSignal.signal_id)).limit(limit)
    if run_id is not None:
        q = q.where(BtSignal.run_id == run_id)
    if since is not None:
        q = q.where(BtSignal.ts >= since)
    if status_prefix is not None:
        q = q.where(BtSignal.status.like(f"{status_prefix}%"))
    rows = s.execute(q).scalars().all()
    filtered = rows
    if leg is not None:
        filtered = [r for r in rows if (r.detail or {}).get("leg") == leg]
    return [_signal_to_dict(r) for r in filtered]


@router.get("/funnel")
def gate_funnel(
    run_id: UUID,
    since: datetime | None = None,
    s: Session = Depends(get_session),
) -> dict:
    """Counts per status — useful to render the gate-rejection funnel pane."""
    q = select(BtSignal.status, func.count(BtSignal.signal_id)).where(BtSignal.run_id == run_id)
    if since is not None:
        q = q.where(BtSignal.ts >= since)
    q = q.group_by(BtSignal.status)
    rows = s.execute(q).all()
    buckets = sorted(
        [{"status": status, "count": int(count)} for status, count in rows],
        key=lambda x: -x["count"],
    )
    return {"run_id": str(run_id), "buckets": buckets}
