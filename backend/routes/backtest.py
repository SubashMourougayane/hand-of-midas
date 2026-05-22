"""Backtest API route — POST /api/gold/backtest, GET /api/gold/backtest/latest."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
import time
import json

from backend.backtest.engine import run_backtest
from backend.db import execute, insert_returning, get_conn

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

    response = BacktestResponse(
        stats=stats,
        trades=trade_responses,
        equity_curve=equity_curve,
        monthly_pnl=monthly_pnl,
        yearly_pnl=yearly_pnl,
        duration_ms=duration_ms,
    )

    # Persist to DB
    try:
        _save_backtest_to_db(req, stats, trade_responses, equity_curve, duration_ms)
    except Exception as e:
        print(f"Warning: failed to persist backtest to DB: {e}")

    return response


def _save_backtest_to_db(req, stats, trades, equity_curve, duration_ms):
    """Save backtest run + trades to database."""
    # Mark previous runs as not latest
    execute("UPDATE gd_backtest_runs SET is_latest = FALSE WHERE is_latest = TRUE")

    # Insert run
    run_id = insert_returning(
        """INSERT INTO gd_backtest_runs
           (strategies, start_date, end_date, capital, risk_pct,
            total_trades, wins, losses, win_rate, profit_factor,
            total_pnl, max_drawdown_pct, avg_win, avg_loss, risk_reward, duration_ms)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (req.strategies, req.start_date, req.end_date, req.capital, req.risk_pct,
         stats.total_trades, stats.wins, stats.losses, stats.win_rate, stats.profit_factor,
         stats.total_pnl, stats.max_drawdown_pct, stats.avg_win, stats.avg_loss, stats.risk_reward, duration_ms)
    )

    if not run_id:
        return

    # Batch insert trades
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for i, t in enumerate(trades):
                cur.execute(
                    """INSERT INTO gd_backtest_trades
                       (run_id, trade_index, date, year, month, strategy, direction,
                        entry, sl, tp, exit_price, pnl_unit, pnl_sized, units,
                        status, bars_held, hold_human, risk, r_mult, equity_after)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, i, t.date, t.year, t.month, t.strategy, t.direction,
                     t.entry, t.sl, t.tp, t.exit_price, t.pnl_unit, t.pnl_sized, t.units,
                     t.status, t.bars_held, t.hold_human, t.risk, t.r_mult, t.equity_after)
                )
            # Insert equity curve
            for pt in equity_curve:
                cur.execute(
                    "INSERT INTO gd_backtest_equity (run_id, date, cumulative_pnl, equity) VALUES (%s,%s,%s,%s)",
                    (run_id, pt["date"], pt["pnl"], pt["equity"])
                )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.get("/backtest/latest")
def get_latest_backtest():
    """Load the most recent backtest run from DB."""
    runs = execute(
        "SELECT * FROM gd_backtest_runs WHERE is_latest = TRUE ORDER BY created_at DESC LIMIT 1",
        fetch=True
    )
    if not runs:
        return {"result": None}

    run = runs[0]
    run_id = run["id"]

    # Load trades
    trades = execute(
        "SELECT * FROM gd_backtest_trades WHERE run_id = %s ORDER BY trade_index",
        (run_id,), fetch=True
    )

    # Load equity curve
    equity = execute(
        "SELECT date, cumulative_pnl as pnl, equity FROM gd_backtest_equity WHERE run_id = %s ORDER BY date",
        (run_id,), fetch=True
    )

    # Build strategy breakdown from trades
    strat_stats = {}
    for t in trades:
        s = t["strategy"]
        if s not in strat_stats:
            strat_stats[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
        strat_stats[s]["trades"] += 1
        strat_stats[s]["pnl"] += float(t["pnl_sized"])
        if float(t["pnl_sized"]) > 0:
            strat_stats[s]["wins"] += 1
    for s in strat_stats:
        st = strat_stats[s]
        st["wr"] = st["wins"] / st["trades"] if st["trades"] > 0 else 0
        gross_w = sum(float(t["pnl_sized"]) for t in trades if t["strategy"] == s and float(t["pnl_sized"]) > 0)
        gross_l = abs(sum(float(t["pnl_sized"]) for t in trades if t["strategy"] == s and float(t["pnl_sized"]) <= 0))
        st["pf"] = gross_w / gross_l if gross_l > 0 else 0
        st["pnl"] = round(st["pnl"], 2)

    # Monthly P&L
    monthly_map = {}
    for t in trades:
        key = f"{t['year']}-{t['month']:02d}"
        monthly_map[key] = monthly_map.get(key, 0) + float(t["pnl_sized"])
    monthly_pnl = [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly_map.items())]

    # Yearly P&L
    yearly_map = {}
    for t in trades:
        y = t["year"]
        if y not in yearly_map:
            yearly_map[y] = {"year": y, "trades": 0, "wins": 0, "pnl": 0.0}
        yearly_map[y]["trades"] += 1
        yearly_map[y]["pnl"] += float(t["pnl_sized"])
        if float(t["pnl_sized"]) > 0:
            yearly_map[y]["wins"] += 1
    yearly_pnl = []
    for y in sorted(yearly_map.keys()):
        d = yearly_map[y]
        d["pnl"] = round(d["pnl"], 2)
        d["wr"] = round(d["wins"] / d["trades"], 3) if d["trades"] > 0 else 0
        d["return_pct"] = round(d["pnl"] / float(run["capital"]) * 100, 1)
        yearly_pnl.append(d)

    # Convert trades to response format
    trade_list = [{
        "date": str(t["date"]),
        "year": t["year"],
        "month": t["month"],
        "strategy": t["strategy"],
        "direction": t["direction"],
        "entry": float(t["entry"]),
        "sl": float(t["sl"]),
        "tp": float(t["tp"]),
        "exit_price": float(t["exit_price"]),
        "pnl_unit": float(t["pnl_unit"]),
        "pnl_sized": float(t["pnl_sized"]),
        "units": float(t["units"]),
        "status": t["status"],
        "bars_held": t["bars_held"],
        "hold_human": t["hold_human"],
        "risk": float(t["risk"]),
        "r_mult": float(t["r_mult"]),
        "equity_after": float(t["equity_after"]),
    } for t in trades]

    equity_curve = [{"date": str(e["date"]), "pnl": float(e["pnl"]), "equity": float(e["equity"])} for e in equity]

    return {
        "stats": {
            "total_trades": run["total_trades"],
            "wins": run["wins"],
            "losses": run["losses"],
            "win_rate": float(run["win_rate"]),
            "profit_factor": float(run["profit_factor"]),
            "total_pnl": float(run["total_pnl"]),
            "max_drawdown_pct": float(run["max_drawdown_pct"]),
            "avg_win": float(run["avg_win"]),
            "avg_loss": float(run["avg_loss"]),
            "risk_reward": float(run["risk_reward"]),
            "trades_per_year": round(run["total_trades"] / max(len(set(t["year"] for t in trades)), 1), 1),
            "months": len(set(t["year"] for t in trades)) * 12,
            "strategies": strat_stats,
        },
        "trades": trade_list,
        "equity_curve": equity_curve,
        "monthly_pnl": monthly_pnl,
        "yearly_pnl": yearly_pnl,
        "duration_ms": run["duration_ms"],
        "config": {
            "strategies": run["strategies"],
            "start_date": str(run["start_date"]),
            "end_date": str(run["end_date"]),
            "capital": float(run["capital"]),
            "risk_pct": float(run["risk_pct"]),
        },
        "created_at": run["created_at"].isoformat(),
    }
