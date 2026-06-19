"""Oil Micro Journal API."""
from fastapi import APIRouter, Query
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute
from config import TRADE_REF_PREFIX

router = APIRouter()


def _row_to_dict(j):
    return {
        "id": j["id"],
        "trade_ref": j["trade_ref"],
        "strategy": j["strategy"],
        "event_type": j["event_type"],
        "price": float(j["price"]) if j["price"] else None,
        "context": j["context"],
        "timestamp": j["timestamp"].isoformat() if j["timestamp"] else None,
    }


@router.get("/journal")
def get_journal():
    rows = execute(
        f"SELECT * FROM gd_journal WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' OR strategy='micro_alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 200",
        fetch=True
    )
    return [_row_to_dict(j) for j in (rows or [])]


@router.get("/journal/events")
def get_journal_events(limit: int = Query(default=100)):
    """Journal events for Oil Micro (live + system events).

    M3 fix (UI mismatch audit 2026-06-19): frontend client.ts hits
    /journal/events; Oil Micro previously only exposed /journal → 404 →
    journal page rendered "No events yet" despite 885 DB rows. Mirror of
    Gold Micro's route.
    """
    rows = execute(
        f"SELECT * FROM gd_journal WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' OR strategy='micro_alpha_sweep_oil' ORDER BY timestamp DESC LIMIT %s",
        (limit,), fetch=True
    )
    return [_row_to_dict(j) for j in (rows or [])]
