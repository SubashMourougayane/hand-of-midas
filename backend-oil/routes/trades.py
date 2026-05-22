"""Oil Trades API — GET /api/oil/trades + /api/oil/trades/backtest."""
from fastapi import APIRouter, Query
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.db import execute

router = APIRouter()


@router.get("/trades")
def get_trades(limit: int = Query(200, le=500)):
    """Get live oil trades."""
    rows = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NOT NULL AND trade_ref LIKE 'OIL-%' ORDER BY exit_time DESC LIMIT %s",
        (limit,), fetch=True
    )
    if not rows:
        return {"trades": [], "stats": {}}

    trades = [{
        "trade_ref": r["trade_ref"], "strategy": r["strategy"], "side": r["side"],
        "entry_time": r["entry_time"].isoformat() if r["entry_time"] else None,
        "exit_time": r["exit_time"].isoformat() if r["exit_time"] else None,
        "entry_price": float(r["entry_price"]), "exit_price": float(r["exit_price"]) if r["exit_price"] else None,
        "sl": float(r["sl_price"]) if r["sl_price"] else None,
        "tp": float(r["tp_price"]) if r["tp_price"] else None,
        "units": r["units"],
        "pnl_gbp": float(r["pnl_gbp"]) if r["pnl_gbp"] else 0,
        "pnl_usd": float(r["pnl_usd"]) if r["pnl_usd"] else 0,
        "exit_reason": r["exit_reason"], "mode": r["mode"],
    } for r in rows]

    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    stats = {
        "total": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "total_pnl": sum(pnls),
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": abs(sum(losses) / len(losses)) if losses else 0,
    }
    return {"trades": trades, "stats": stats}


@router.get("/trades/backtest")
def get_backtest_trades(
    strategy: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    limit: int = Query(2000, le=5000),
):
    """Get trades from latest oil backtest run."""
    runs = execute(
        "SELECT id FROM gd_backtest_runs WHERE is_latest = TRUE AND strategies = %s LIMIT 1",
        (["alpha_sweep_oil"],), fetch=True
    )
    if not runs:
        return {"trades": [], "stats": {}}

    run_id = runs[0]["id"]
    sql = "SELECT * FROM gd_backtest_trades WHERE run_id = %s"
    params: list = [run_id]

    if strategy:
        sql += " AND strategy = %s"
        params.append(strategy)
    if side:
        sql += " AND direction = %s"
        params.append(side.upper())
    if result == "win":
        sql += " AND pnl_sized > 0"
    elif result == "loss":
        sql += " AND pnl_sized <= 0"
    if year:
        sql += " AND year = %s"
        params.append(year)

    sql += " ORDER BY trade_index LIMIT %s"
    params.append(limit)

    rows = execute(sql, params, fetch=True)
    if not rows:
        return {"trades": [], "stats": {}}

    trades = [{
        "date": str(r["date"]), "year": r["year"], "strategy": r["strategy"],
        "direction": r["direction"], "entry": float(r["entry"]), "sl": float(r["sl"]),
        "tp": float(r["tp"]), "exit_price": float(r["exit_price"]),
        "pnl_sized": float(r["pnl_sized"]), "units": float(r["units"]),
        "status": r["status"], "hold_human": r["hold_human"],
        "risk": float(r["risk"]), "r_mult": float(r["r_mult"]),
        "equity_after": float(r["equity_after"]), "bars_held": r["bars_held"],
    } for r in rows]

    pnls = [t["pnl_sized"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_w = sum(wins) if wins else 0
    gross_l = abs(sum(losses)) if losses else 0.001
    stats = {
        "total": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "total_pnl": sum(pnls), "profit_factor": gross_w / gross_l,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": abs(sum(losses) / len(losses)) if losses else 0,
    }
    return {"trades": trades, "stats": stats}
