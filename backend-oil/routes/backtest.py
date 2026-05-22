"""Oil Backtest API — POST /api/oil/backtest."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import run_backtest

router = APIRouter()


class BacktestRequest(BaseModel):
    start_date: str = Field(default="2006-01-01")
    end_date: str = Field(default="2026-12-31")
    capital: float = Field(default=5000.0)
    risk_pct: float = Field(default=4.0)


@router.post("/backtest")
def api_backtest(req: BacktestRequest):
    t0 = time.time()
    result = run_backtest(
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

    # Yearly breakdown
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
        year_trades = [t for t in trades if t.year == y]
        start_fund = round(year_trades[0].equity_after - year_trades[0].pnl_sized, 2) if year_trades else req.capital
        end_fund = round(year_trades[-1].equity_after, 2) if year_trades else req.capital
        d["start_fund"] = start_fund
        d["end_fund"] = end_fund
        d["return_pct"] = round((end_fund - start_fund) / max(start_fund, 1) * 100, 1)
        yearly_pnl.append(d)

    # Equity curve
    cumulative = 0
    equity_curve = []
    for t in trades:
        cumulative += t.pnl_sized
        equity_curve.append({"date": t.date, "pnl": round(cumulative, 2), "equity": t.equity_after})

    duration_ms = int((time.time() - t0) * 1000)

    return {
        "stats": {
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
            "trades_per_year": round(result.total_trades / max(len(yearly_map), 1), 1),
            "strategies": {"alpha_sweep": {"trades": result.total_trades, "wins": result.wins, "wr": result.win_rate, "pf": result.profit_factor, "pnl": round(result.total_pnl, 2)}},
        },
        "trades": [t.__dict__ for t in trades],
        "equity_curve": equity_curve,
        "yearly_pnl": yearly_pnl,
        "monthly_pnl": [],
        "duration_ms": duration_ms,
    }
