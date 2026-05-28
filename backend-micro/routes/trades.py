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
def get_backtest_trades(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=200),
    strategy: str = Query(default=None),
    side: str = Query(default=None),
    result: str = Query(default=None),
    year: int = Query(default=None),
):
    """Load backtest trades with pagination and server-side filtering."""
    try:
        runs = execute(
            "SELECT id FROM gd_backtest_runs WHERE is_latest = TRUE AND strategies @> %s ORDER BY created_at DESC LIMIT 1",
            (MICRO_STRATEGIES_FILTER,), fetch=True
        )
        if not runs:
            return {"trades": [], "total": 0, "page": page, "per_page": per_page, "pages": 0, "message": "No backtest results in DB."}
        run_id = runs[0]["id"]

        # Build WHERE clause with filters
        conditions = ["run_id = %s"]
        params = [run_id]

        if strategy:
            conditions.append("strategy = %s")
            params.append(strategy)
        if side:
            conditions.append("direction = %s")
            params.append(side)
        if result == "WIN":
            conditions.append("pnl_sized > 0")
        elif result == "LOSS":
            conditions.append("pnl_sized <= 0")
        if year:
            conditions.append("year = %s")
            params.append(year)

        where = " AND ".join(conditions)

        # Get total count
        count_row = execute(f"SELECT COUNT(*) as cnt FROM gd_backtest_trades WHERE {where}", params, fetch=True)
        total = count_row[0]["cnt"] if count_row else 0
        pages = (total + per_page - 1) // per_page

        # Get page
        offset = (page - 1) * per_page
        trades = execute(
            f"SELECT * FROM gd_backtest_trades WHERE {where} ORDER BY trade_index LIMIT %s OFFSET %s",
            params + [per_page, offset], fetch=True
        )

        return {
            "trades": [dict(t) for t in trades],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }
    except Exception as e:
        return {"trades": [], "total": 0, "page": 1, "per_page": per_page, "pages": 0, "message": str(e)}
