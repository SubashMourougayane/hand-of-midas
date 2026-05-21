"""Backtest API route — POST /api/gold/backtest."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
import time

from backend.backtest.engine import run_backtest

router = APIRouter()


class BacktestRequest(BaseModel):
    strategies: list[str] = Field(default=["alpha_sweep", "mean_rev", "cross_market"])
    start_date: str = Field(default="2006-01-01")
    end_date: str = Field(default="2026-12-31")
    capital: float = Field(default=5000.0)
    risk_pct: float = Field(default=3.0)


class TradeResponse(BaseModel):
    date: str
    year: int
    month: int
    strategy: str
    direction: str
    entry: float
    sl: float
    tp: float
    exit_price: float
    pnl_unit: float
    pnl_sized: float
    units: float
    status: str
    bars_held: int
    hold_human: str
    risk: float
    r_mult: float
    equity_after: float


class StatsResponse(BaseModel):
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    max_drawdown_pct: float
    avg_win: float
    avg_loss: float
    risk_reward: float
    trades_per_year: float
    months: float
    strategies: dict


class BacktestResponse(BaseModel):
    stats: StatsResponse
    trades: list[TradeResponse]
    equity_curve: list[dict]
    monthly_pnl: list[dict]
    yearly_pnl: list[dict]
    duration_ms: int


@router.post("/backtest")
def api_backtest(req: BacktestRequest) -> BacktestResponse:
    """Run portfolio backtest and return full results."""
    t0 = time.time()

    result = run_backtest(
        strategies=req.strategies,
        start_date=req.start_date,
        end_date=req.end_date,
        capital=req.capital,
        risk_pct=req.risk_pct,
    )

    # Compute detailed stats
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
            "avg_hold": st[0].hold_human if len(st) == 1 else None,
        }

    stats = StatsResponse(
        total_trades=result.total_trades,
        wins=result.wins,
        losses=result.losses,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        total_pnl=round(result.total_pnl, 2),
        max_drawdown_pct=round(result.max_drawdown_pct, 1),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        risk_reward=round(rr, 2),
        trades_per_year=round(result.total_trades / years_span, 1),
        months=months_span,
        strategies=strat_stats,
    )

    # Equity curve (cumulative P&L per trade)
    cumulative = 0
    equity_curve = []
    for t in trades:
        cumulative += t.pnl_sized
        equity_curve.append({"date": t.date, "pnl": round(cumulative, 2), "equity": t.equity_after})

    # Monthly P&L aggregation
    monthly_map: dict[str, float] = {}
    for t in trades:
        key = f"{t.year}-{t.month:02d}"
        monthly_map[key] = monthly_map.get(key, 0) + t.pnl_sized
    monthly_pnl = [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly_map.items())]

    # Yearly P&L
    yearly_map: dict[int, dict] = {}
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
        d["return_pct"] = round(d["pnl"] / req.capital * 100, 1)
        yearly_pnl.append(d)

    # Trade list
    trade_responses = [TradeResponse(**t.__dict__) for t in trades]

    duration_ms = int((time.time() - t0) * 1000)

    return BacktestResponse(
        stats=stats,
        trades=trade_responses,
        equity_curve=equity_curve,
        monthly_pnl=monthly_pnl,
        yearly_pnl=yearly_pnl,
        duration_ms=duration_ms,
    )
