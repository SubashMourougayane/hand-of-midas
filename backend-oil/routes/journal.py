"""Oil Journal API — GET /api/oil/journal/events + /journal/trades."""
from fastapi import APIRouter, Query
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute

router = APIRouter()


@router.get("/journal/events")
def get_events(
    trade_ref: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """Get oil journal events."""
    sql = "SELECT * FROM gd_journal WHERE (trade_ref LIKE 'OIL-%%' OR trade_ref = 'SYSTEM') AND strategy = 'alpha_sweep_oil'"
    params: list = []

    if trade_ref:
        sql += " AND trade_ref = %s"
        params.append(trade_ref)
    if event_type:
        sql += " AND event_type = %s"
        params.append(event_type)

    sql += " ORDER BY timestamp DESC LIMIT %s"
    params.append(int(limit))

    rows = execute(sql, params, fetch=True)
    events = []
    for r in (rows or []):
        events.append({
            "id": r["id"],
            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            "trade_ref": r["trade_ref"],
            "strategy": r["strategy"],
            "event_type": r["event_type"],
            "price": float(r["price"]) if r["price"] else None,
            "context": r["context"],
        })
    return {"events": events}


@router.get("/journal/trades")
def get_journal_trades(limit: int = Query(20, le=100)):
    """Get journal events grouped by trade_ref for Oil."""
    trade_refs = execute(
        "SELECT DISTINCT trade_ref FROM gd_journal WHERE trade_ref LIKE 'OIL-%%' AND trade_ref != 'SYSTEM' ORDER BY trade_ref DESC LIMIT %s",
        (int(limit),), fetch=True
    )
    if not trade_refs:
        return {"trades": []}

    trades = []
    for row in trade_refs:
        ref = row["trade_ref"]
        events = execute(
            "SELECT * FROM gd_journal WHERE trade_ref = %s ORDER BY timestamp ASC",
            (ref,), fetch=True
        )
        trades.append({
            "trade_ref": ref,
            "events": [
                {
                    "timestamp": e["timestamp"].isoformat() if e["timestamp"] else None,
                    "event_type": e["event_type"],
                    "price": float(e["price"]) if e["price"] else None,
                    "context": e["context"],
                }
                for e in (events or [])
            ],
        })
    return {"trades": trades}
