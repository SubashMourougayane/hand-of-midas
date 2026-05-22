"""Oil Backtest API — POST /api/oil/backtest + GET /api/oil/backtest/latest."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.engine import run_backtest
from backend.db import execute, insert_returning, get_conn

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
        "trades_per_year": round(result.total_trades / max(len(yearly_map), 1), 1),
        "months": len(yearly_map) * 12,
        "strategies": {"alpha_sweep": {"trades": result.total_trades, "wins": result.wins, "wr": result.win_rate, "pf": result.profit_factor, "pnl": round(result.total_pnl, 2)}},
    }

    trade_dicts = [t.__dict__ for t in trades]

    # Save to DB
    try:
        _save_to_db(req, stats, trade_dicts, equity_curve, duration_ms)
    except Exception as e:
        print(f"Warning: failed to persist oil backtest to DB: {e}")

    return {
        "stats": stats,
        "trades": trade_dicts,
        "equity_curve": equity_curve,
        "yearly_pnl": yearly_pnl,
        "monthly_pnl": [],
        "duration_ms": duration_ms,
    }


def _save_to_db(req, stats, trades, equity_curve, duration_ms):
    """Save oil backtest run to DB (uses oil_ prefix tables or shared with instrument tag)."""
    # Use shared gd_backtest_runs but mark as oil
    execute("UPDATE gd_backtest_runs SET is_latest = FALSE WHERE is_latest = TRUE AND strategies = %s", (["alpha_sweep_oil"],))

    run_id = insert_returning(
        """INSERT INTO gd_backtest_runs
           (strategies, start_date, end_date, capital, risk_pct,
            total_trades, wins, losses, win_rate, profit_factor,
            total_pnl, max_drawdown_pct, avg_win, avg_loss, risk_reward, duration_ms, is_latest)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
           RETURNING id""",
        (["alpha_sweep_oil"], req.start_date, req.end_date, req.capital, req.risk_pct,
         stats["total_trades"], stats["wins"], stats["losses"], stats["win_rate"], stats["profit_factor"],
         stats["total_pnl"], stats["max_drawdown_pct"], stats["avg_win"], stats["avg_loss"], stats["risk_reward"], duration_ms)
    )

    if not run_id:
        return

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
                    (run_id, i, t["date"], t["year"], t["month"], "alpha_sweep_oil", t["direction"],
                     t["entry"], t["sl"], t["tp"], t["exit_price"], t["pnl_unit"], t["pnl_sized"], t["units"],
                     t["status"], t["bars_held"], t["hold_human"], t["risk"], t["r_mult"], t["equity_after"])
                )
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
    """Load most recent oil backtest from DB."""
    runs = execute(
        "SELECT * FROM gd_backtest_runs WHERE is_latest = TRUE AND strategies = %s ORDER BY created_at DESC LIMIT 1",
        (["alpha_sweep_oil"],), fetch=True
    )
    if not runs:
        return {"result": None}

    run = runs[0]
    run_id = run["id"]

    trades = execute(
        "SELECT * FROM gd_backtest_trades WHERE run_id = %s ORDER BY trade_index",
        (run_id,), fetch=True
    )
    equity = execute(
        "SELECT date, cumulative_pnl as pnl, equity FROM gd_backtest_equity WHERE run_id = %s ORDER BY date",
        (run_id,), fetch=True
    )

    if not trades:
        return {"result": None}

    # Build yearly
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
        year_trades_sorted = sorted([t for t in trades if t["year"] == y], key=lambda x: x["trade_index"])
        if year_trades_sorted:
            start_fund = round(float(year_trades_sorted[0]["equity_after"]) - float(year_trades_sorted[0]["pnl_sized"]), 2)
            end_fund = round(float(year_trades_sorted[-1]["equity_after"]), 2)
        else:
            start_fund = float(run["capital"])
            end_fund = float(run["capital"])
        d["start_fund"] = start_fund
        d["end_fund"] = end_fund
        d["return_pct"] = round((end_fund - start_fund) / max(start_fund, 1) * 100, 1)
        yearly_pnl.append(d)

    trade_list = [{
        "date": str(t["date"]), "year": t["year"], "month": t["month"],
        "strategy": t["strategy"], "direction": t["direction"],
        "entry": float(t["entry"]), "sl": float(t["sl"]), "tp": float(t["tp"]),
        "exit_price": float(t["exit_price"]), "pnl_unit": float(t["pnl_unit"]),
        "pnl_sized": float(t["pnl_sized"]), "units": float(t["units"]),
        "status": t["status"], "bars_held": t["bars_held"],
        "hold_human": t["hold_human"], "risk": float(t["risk"]),
        "r_mult": float(t["r_mult"]), "equity_after": float(t["equity_after"]),
    } for t in trades]

    equity_curve = [{"date": str(e["date"]), "pnl": float(e["pnl"]), "equity": float(e["equity"])} for e in (equity or [])]

    strat_stats = {"alpha_sweep": {
        "trades": len(trades),
        "wins": sum(1 for t in trades if float(t["pnl_sized"]) > 0),
        "wr": sum(1 for t in trades if float(t["pnl_sized"]) > 0) / len(trades) if trades else 0,
        "pf": float(run["profit_factor"]),
        "pnl": float(run["total_pnl"]),
    }}

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
            "trades_per_year": round(run["total_trades"] / max(len(yearly_map), 1), 1),
            "months": len(yearly_map) * 12,
            "strategies": strat_stats,
        },
        "trades": trade_list,
        "equity_curve": equity_curve,
        "yearly_pnl": yearly_pnl,
        "monthly_pnl": [],
        "duration_ms": run["duration_ms"],
        "config": {
            "strategies": ["alpha_sweep"],
            "start_date": str(run["start_date"]),
            "end_date": str(run["end_date"]),
            "capital": float(run["capital"]),
            "risk_pct": float(run["risk_pct"]),
        },
        "created_at": run["created_at"].isoformat(),
    }
