"""Micro Trades API."""
from fastapi import APIRouter, Query
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute
from config import TRADE_REF_PREFIX

router = APIRouter()

MICRO_STRATEGIES_FILTER = ["micro_alpha_sweep"]


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


@router.get("/trades/backtest")
def get_backtest_trades(limit: int = Query(default=2000)):
    """Load backtest trades from latest Micro run."""
    try:
        runs = execute(
            "SELECT id FROM gd_backtest_runs WHERE is_latest = TRUE AND strategies @> %s ORDER BY created_at DESC LIMIT 1",
            (MICRO_STRATEGIES_FILTER,), fetch=True
        )
        if not runs:
            return {"trades": [], "message": "No backtest results in DB. Run a backtest first from the Backtest page."}
        run_id = runs[0]["id"]
        trades = execute(
            "SELECT * FROM gd_backtest_trades WHERE run_id = %s ORDER BY trade_index LIMIT %s",
            (run_id, limit), fetch=True
        )
        return {"trades": [dict(t) for t in trades]}
    except Exception:
        return {"trades": [], "message": "No backtest results in DB. Run a backtest first from the Backtest page."}
