"""Trades API — GET /api/gold/trades for trade history."""
from fastapi import APIRouter, Query
from typing import Optional
from backend.db import execute

router = APIRouter()


@router.get("/trades")
def get_trades(
    strategy: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    result: Optional[str] = Query(None),  # 'win' or 'loss'
    limit: int = Query(100, le=500),
):
    """Get closed trades from DB with optional filters."""
    sql = "SELECT * FROM gd_trades WHERE exit_time IS NOT NULL"
    params = []

    if strategy:
        sql += " AND strategy = %s"
        params.append(strategy)
    if side:
        sql += " AND side = %s"
        params.append(side.upper())
    if result == "win":
        sql += " AND pnl_usd > 0"
    elif result == "loss":
        sql += " AND pnl_usd <= 0"

    sql += " ORDER BY exit_time DESC LIMIT %s"
    params.append(limit)

    rows = execute(sql, params, fetch=True)
    if not rows:
        return {"trades": [], "stats": {}}

    trades = []
    for r in rows:
        trades.append({
            "trade_ref": r["trade_ref"],
            "strategy": r["strategy"],
            "side": r["side"],
            "entry_time": r["entry_time"].isoformat() if r["entry_time"] else None,
            "exit_time": r["exit_time"].isoformat() if r["exit_time"] else None,
            "entry_price": float(r["entry_price"]),
            "exit_price": float(r["exit_price"]) if r["exit_price"] else None,
            "sl": float(r["sl_price"]) if r["sl_price"] else None,
            "tp": float(r["tp_price"]) if r["tp_price"] else None,
            "units": r["units"],
            "pnl_gbp": float(r["pnl_gbp"]) if r["pnl_gbp"] else 0,
            "pnl_usd": float(r["pnl_usd"]) if r["pnl_usd"] else 0,
            "exit_reason": r["exit_reason"],
            "mode": r["mode"],
        })

    # Compute stats (using USD P&L)
    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    stats = {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "total_pnl": sum(pnls),
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": abs(sum(losses) / len(losses)) if losses else 0,
    }

    return {"trades": trades, "stats": stats}
