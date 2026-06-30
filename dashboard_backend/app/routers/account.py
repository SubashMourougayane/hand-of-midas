"""GET /api/account/latest + /api/scan-status."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session

from bt_engine.db.models import BtAccountSnapshot, BtRun, BtSignal

from ..deps import get_session

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/account/latest")
def latest_account(
    run_id: UUID,
    limit: int = 1,
    s: Session = Depends(get_session),
) -> dict:
    q = (
        select(BtAccountSnapshot)
        .where(BtAccountSnapshot.run_id == run_id)
        .order_by(desc(BtAccountSnapshot.ts))
        .limit(limit)
    )
    rows = s.execute(q).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="no account snapshot for run")
    return {
        "items": [
            {
                "snap_id": r.snap_id,
                "ts": r.ts.isoformat(),
                "balance": float(r.balance) if r.balance is not None else None,
                "equity": float(r.equity) if r.equity is not None else None,
                "open_pnl": float(r.open_pnl) if r.open_pnl is not None else None,
                "open_position": int(r.open_position) if r.open_position is not None else None,
            }
            for r in rows
        ]
    }


@router.get("/account/series")
def account_series(
    run_id: UUID,
    since: datetime | None = None,
    limit: int = 500,
    s: Session = Depends(get_session),
) -> list[dict]:
    q = (
        select(BtAccountSnapshot)
        .where(BtAccountSnapshot.run_id == run_id)
        .order_by(BtAccountSnapshot.ts.asc())
    )
    if since is not None:
        q = q.where(BtAccountSnapshot.ts >= since)
    q = q.limit(limit)
    rows = s.execute(q).scalars().all()
    return [
        {
            "ts": r.ts.isoformat(),
            "balance": float(r.balance) if r.balance is not None else None,
            "equity": float(r.equity) if r.equity is not None else None,
        }
        for r in rows
    ]


@router.get("/scan-status")
def scan_status(s: Session = Depends(get_session)) -> dict:
    """Active runs + last bar processed per run (live mode only)."""
    live_q = (
        select(BtRun)
        .where(BtRun.mode == "live")
        .where(BtRun.end_ts.is_(None))
        .order_by(desc(BtRun.start_ts))
    )
    live_runs = s.execute(live_q).scalars().all()
    runs_info = []
    for r in live_runs:
        last = s.execute(
            select(func.max(BtAccountSnapshot.ts)).where(BtAccountSnapshot.run_id == r.run_id)
        ).scalar_one()
        last_sig = s.execute(
            select(func.max(BtSignal.ts)).where(
                BtSignal.run_id == r.run_id,
                BtSignal.status == "GATE_SIGNAL_PASSED",
            )
        ).scalar_one()
        runs_info.append({
            "run_id": str(r.run_id),
            "run_ref": r.ref,
            "strategy_id": r.strategy_id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "start_ts": r.start_ts.isoformat(),
            "last_bar_ts": last.isoformat() if last is not None else None,
            "last_signal_pass_ts": last_sig.isoformat() if last_sig is not None else None,
        })
    return {"runs": runs_info}
