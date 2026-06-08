"""Oil Micro Journal API."""
from fastapi import APIRouter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute
from config import TRADE_REF_PREFIX

router = APIRouter()


@router.get("/journal")
def get_journal():
    rows = execute(
        f"SELECT * FROM gd_journal WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' OR strategy='micro_alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 200",
        fetch=True
    )
    return [
        {
            "id": j["id"],
            "trade_ref": j["trade_ref"],
            "strategy": j["strategy"],
            "event_type": j["event_type"],
            "price": float(j["price"]) if j["price"] else None,
            "context": j["context"],
            "timestamp": j["timestamp"].isoformat() if j["timestamp"] else None,
        }
        for j in (rows or [])
    ]
