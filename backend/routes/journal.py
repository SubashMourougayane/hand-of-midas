"""Journal API — GET /api/gold/journal for event log."""
from fastapi import APIRouter, Query
from typing import Optional
from backend.db import execute

router = APIRouter()


@router.get("/journal/events")
def get_events(
    trade_ref: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """Get journal events with optional filters."""
    sql = "SELECT * FROM gd_journal WHERE 1=1"
    params = []

    if trade_ref:
        sql += " AND trade_ref = %s"
        params.append(trade_ref)
    if event_type:
        sql += " AND event_type = %s"
        params.append(event_type)
    if strategy:
        sql += " AND strategy = %s"
        params.append(strategy)

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


@router.get("/journal/trades")
def get_trade_events(limit: int = Query(20, le=50)):
    """Get events grouped by trade_ref (last N trades)."""
    # Get unique trade_refs
    refs = execute(
        "SELECT DISTINCT trade_ref FROM gd_journal WHERE trade_ref IS NOT NULL AND trade_ref != 'SYSTEM' ORDER BY MAX(timestamp) DESC LIMIT %s",
        (limit,), fetch=True
    )
    if not refs:
        return {"trade_groups": []}

    groups = []
    for ref_row in refs:
        ref = ref_row["trade_ref"]
        events = execute(
            "SELECT * FROM gd_journal WHERE trade_ref = %s ORDER BY timestamp",
            (ref,), fetch=True
        )
        group_events = [{
            "timestamp": e["timestamp"].isoformat() if e["timestamp"] else None,
            "event_type": e["event_type"],
            "price": float(e["price"]) if e["price"] else None,
            "context": e["context"],
        } for e in (events or [])]
        groups.append({"trade_ref": ref, "events": group_events})

    return {"trade_groups": groups}
