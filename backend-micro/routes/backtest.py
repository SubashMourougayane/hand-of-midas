"""Micro Backtest API — POST /api/micro/backtest, GET /api/micro/backtest/latest."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.engine import run_backtest
from backend.db import execute

router = APIRouter()


class BacktestRequest(BaseModel):
    strategies: list[str] = Field(default=["micro_alpha_sweep", "mean_rev", "cross_market"])
    start_date: str = Field(default="2006-01-01")
    end_date: str = Field(default="2026-12-31")
    capital: float = Field(default=5000.0)
    risk_pct: float = Field(default=3.0)


@router.post("/backtest")
def api_backtest(req: BacktestRequest):
    """Run Micro portfolio backtest."""
    t0 = time.time()

    result = run_backtest(
        strategies=req.strategies,
        start_date=req.start_date,
        end_date=req.end_date,
        capital=req.capital,
        risk_pct=req.risk_pct,
    )

    trades = result.trades
    wins = [t for t in trades if t.pnl_sized > 0]
    losses = [t for t in trades if t.pnl_sized <= 0]
    avg_win = sum(t.pnl_sized for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t.pnl_sized for t in losses) / len(losses)) if losses else 0
    rr = avg_win / avg_loss if avg_loss > 0 else 0

    years_span = len(set(t.year for t in trades)) if trades else 1
    months_span = years_span * 12

    # Per-strategy breakdown
    strat_stats = {}
    for strat in set(t.strategy for t in trades):
        st = [t for t in trades if t.strategy == strat]
        sw = [t for t in st if t.pnl_sized > 0]
        sl = [t for t in st if t.pnl_sized <= 0]
        gw = sum(t.pnl_sized for t in sw)
        gl = abs(sum(t.pnl_sized for t in sl))
        strat_stats[strat] = {
            "trades": len(st),
            "wins": len(sw),
            "wr": len(sw) / len(st) if st else 0,
            "pf": gw / gl if gl > 0 else 0,
            "pnl": round(sum(t.pnl_sized for t in st), 2),
        }

    stats = {
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "total_pnl": round(result.total_pnl, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "risk_reward": round(rr, 2),
        "trades_per_year": round(result.total_trades / years_span, 1),
        "months": months_span,
        "strategies": strat_stats,
    }

    # Equity curve
    cumulative = 0
    equity_curve = []
    for t in trades:
        cumulative += t.pnl_sized
        equity_curve.append({"date": t.date, "pnl": round(cumulative, 2), "equity": t.equity_after})

    # Monthly P&L
    monthly_map = {}
    for t in trades:
        key = f"{t.year}-{t.month:02d}"
        monthly_map[key] = monthly_map.get(key, 0) + t.pnl_sized
    monthly_pnl = [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly_map.items())]

    # Yearly P&L
    yearly_map = {}
    for t in trades:
        if t.year not in yearly_map:
            yearly_map[t.year] = {"year": t.year, "trades": 0, "wins": 0, "pnl": 0.0}
        yearly_map[t.year]["trades"] += 1
        yearly_map[t.year]["pnl"] += t.pnl_sized
        if t.pnl_sized > 0:
            yearly_map[t.year]["wins"] += 1

    yearly_pnl = []
    for y in sorted(yearly_map.keys()):
        d = yearly_map[y]
        d["pnl"] = round(d["pnl"], 2)
        d["wr"] = round(d["wins"] / d["trades"], 3) if d["trades"] > 0 else 0
        year_trades_list = [t for t in trades if t.year == y]
        if year_trades_list:
            start_fund = round(year_trades_list[0].equity_after - year_trades_list[0].pnl_sized, 2)
            end_fund = round(year_trades_list[-1].equity_after, 2)
        else:
            start_fund = req.capital
            end_fund = req.capital
        d["start_fund"] = start_fund
        d["end_fund"] = end_fund
        d["return_pct"] = round((end_fund - start_fund) / max(start_fund, 1) * 100, 1)
        yearly_pnl.append(d)

    trade_responses = [t.__dict__ for t in trades]
    duration_ms = int((time.time() - t0) * 1000)

    return {
        "stats": stats,
        "trades": trade_responses,
        "equity_curve": equity_curve,
        "monthly_pnl": monthly_pnl,
        "yearly_pnl": yearly_pnl,
        "duration_ms": duration_ms,
    }


@router.get("/backtest/latest")
def get_latest():
    """Return last saved Micro backtest from DB (or null if never run)."""
    try:
        rows = execute(
            "SELECT * FROM gd_backtest_results WHERE instrument='micro' ORDER BY created_at DESC LIMIT 1",
            fetch=True
        )
        if not rows:
            return {"result": None}
        import json
        row = rows[0]
        return {
            "stats": json.loads(row["stats_json"]) if row.get("stats_json") else None,
            "trades": json.loads(row["trades_json"]) if row.get("trades_json") else [],
            "equity_curve": json.loads(row["equity_json"]) if row.get("equity_json") else [],
            "monthly_pnl": json.loads(row["monthly_json"]) if row.get("monthly_json") else [],
            "yearly_pnl": json.loads(row["yearly_json"]) if row.get("yearly_json") else [],
            "duration_ms": row.get("duration_ms", 0),
            "config": json.loads(row["config_json"]) if row.get("config_json") else None,
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "result": True,
        }
    except Exception:
        return {"result": None}
