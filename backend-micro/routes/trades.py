"""Micro Trades API."""
from fastapi import APIRouter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute
from config import TRADE_REF_PREFIX

router = APIRouter()


@router.get("/trades")
def get_trades():
    rows = execute(
        f"SELECT * FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' ORDER BY entry_time DESC LIMIT 100",
        fetch=True
    )
    return [
        {
            "trade_ref": t["trade_ref"], "strategy": t["strategy"], "side": t["side"],
            "entry_time": t["entry_time"].isoformat() if t["entry_time"] else None,
            "exit_time": t["exit_time"].isoformat() if t["exit_time"] else None,
            "entry_price": float(t["entry_price"]) if t["entry_price"] else 0,
            "exit_price": float(t["exit_price"]) if t["exit_price"] else 0,
            "sl": float(t["sl_price"]) if t["sl_price"] else 0,
            "tp": float(t["tp_price"]) if t["tp_price"] else 0,
            "units": t["units"],
            "pnl_gbp": float(t["pnl_gbp"]) if t["pnl_gbp"] else 0,
            "pnl_usd": float(t["pnl_usd"]) if t["pnl_usd"] else 0,
            "exit_reason": t["exit_reason"] or "",
        }
        for t in (rows or [])
    ]
