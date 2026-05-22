"""Oil Journal API — GET /api/oil/journal/events."""
from fastapi import APIRouter, Query
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute

router = APIRouter()


@router.get("/journal/events")
def get_events(
    strategy: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """Get oil journal events."""
    sql = "SELECT * FROM gd_journal WHERE 1=1 AND (trade_ref LIKE 'OIL-%' OR strategy = 'alpha_sweep_oil')"
    params = []

    if strategy:
        sql += " AND strategy = %s"
        params.append(strategy)
    if event_type:
        sql += " AND event_type = %s"
        params.append(event_type)

    sql += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)

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
