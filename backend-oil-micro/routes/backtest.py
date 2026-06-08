"""Oil Micro Backtest API — SSE streaming backtest + GET /api/oil-micro/backtest/latest."""
import asyncio
import json
import time
import threading
import uuid
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backtest.engine import run_backtest
from backend.db import execute, insert_returning, get_conn

router = APIRouter()

MICRO_STRATEGIES_FILTER = ["micro_alpha_sweep_oil"]

_runs = {}


class BacktestRequest(BaseModel):
    strategies: list[str] = Field(default=["micro_alpha_sweep_oil"])
    start_date: str = Field(default="2020-01-01")
    end_date: str = Field(default="2026-12-31")
    capital: float = Field(default=5000.0)
    risk_pct: float = Field(default=4.0)


def _run_backtest_thread(run_id: str, req: BacktestRequest):
    t0 = time.time()
    _runs[run_id]["progress"].append("Loading Oil data (H1 + M3 + Daily)...")

    try:
        result = run_backtest(
            start_date=req.start_date,
            end_date=req.end_date,
            capital=req.capital,
            risk_pct=req.risk_pct,
        )

        _runs[run_id]["progress"].append(f"Complete: {len(result.trades)} trades found")

        trades = result.trades
        wins = [t for t in trades if t.pnl_sized > 0]
        losses = [t for t in trades if t.pnl_sized <= 0]
        avg_win = sum(t.pnl_sized for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t.pnl_sized for t in losses) / len(losses)) if losses else 0
        rr = avg_win / avg_loss if avg_loss > 0 else 0

        years_span = len(set(t.year for t in trades)) if trades else 1
        months_span = years_span * 12

        strat_stats = {}
        for strat in set(t.strategy for t in trades):
            st = [t for t in trades if t.strategy == strat]
            sw = [t for t in st if t.pnl_sized > 0]
            gw = sum(t.pnl_sized for t in sw)
            gl = abs(sum(t.pnl_sized for t in st if t.pnl_sized <= 0))
            strat_stats[strat] = {
                "trades": len(st), "wins": len(sw),
                "wr": len(sw) / len(st) if st else 0,
                "pf": gw / gl if gl > 0 else 0,
                "pnl": round(sum(t.pnl_sized for t in st), 2),
            }

        def _get_session(date_str):
            import re as _re
            match = _re.search(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}):', str(date_str))
            if not match:
                return "unknown"
            h = int(match.group(2))
            if h >= 22 or h < 8:
                return "asian"
            elif 8 <= h < 13:
                return "london"
            elif 13 <= h < 17:
                return "overlap"
            else:
                return "newyork"

        session_data = {"asian": [], "london": [], "overlap": [], "newyork": []}
        for t in trades:
            sess = _get_session(t.date)
            if sess in session_data:
                session_data[sess].append(t.pnl_sized)

        sessions = {}
        for sess, pnls in session_data.items():
            if not pnls:
                sessions[sess] = {"trades": 0, "wins": 0, "win_rate": 0, "pnl": 0, "pf": 0, "monthly": 0}
                continue
            sw = sum(1 for p in pnls if p > 0)
            gw = sum(p for p in pnls if p > 0)
            gl = abs(sum(p for p in pnls if p <= 0))
            sessions[sess] = {
                "trades": len(pnls), "wins": sw,
                "win_rate": round(sw / len(pnls) * 100, 1),
                "pnl": round(sum(pnls), 0),
                "pf": round(gw / gl, 2) if gl > 0 else 0,
                "monthly": round(sum(pnls) / max(months_span, 1), 0),
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
            "sessions": sessions,
            "strategies": strat_stats,
        }

        cumulative = 0
        equity_curve = []
        for t in trades:
            cumulative += t.pnl_sized
            equity_curve.append({"date": t.date, "pnl": round(cumulative, 2), "equity": t.equity_after})

        monthly_map = {}
        for t in trades:
            key = f"{t.year}-{t.month:02d}"
            monthly_map[key] = monthly_map.get(key, 0) + t.pnl_sized
        monthly_pnl = [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly_map.items())]

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

        response_data = {
            "stats": stats,
            "trades": trade_responses,
            "equity_curve": equity_curve,
            "monthly_pnl": monthly_pnl,
            "yearly_pnl": yearly_pnl,
            "duration_ms": duration_ms,
        }

        _runs[run_id]["result"] = response_data
        _runs[run_id]["status"] = "done"
        _runs[run_id]["progress"].append(f"Complete! {result.total_trades} trades, PF {result.profit_factor:.2f}, P&L ${result.total_pnl:,.0f} ({duration_ms/1000:.1f}s)")

        try:
            _save_backtest_to_db(req, stats, trade_responses, equity_curve, duration_ms)
        except Exception as e:
            print(f"Oil Micro DB save warning: {e}")

    except Exception as e:
        _runs[run_id]["status"] = "error"
        _runs[run_id]["progress"].append(f"ERROR: {str(e)}")


@router.post("/backtest")
async def api_backtest(req: BacktestRequest):
    run_id = str(uuid.uuid4())[:8]
    _runs[run_id] = {"status": "running", "progress": [], "result": None}

    t = threading.Thread(target=_run_backtest_thread, args=(run_id, req), daemon=True)
    t.start()

    async def event_generator():
        last_idx = 0
        while True:
            run = _runs.get(run_id)
            if not run:
                break

            while last_idx < len(run["progress"]):
                msg = run["progress"][last_idx]
                yield f"data: {json.dumps({'type': 'progress', 'message': msg})}\n\n"
                last_idx += 1

            if run["status"] == "done":
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            elif run["status"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': run['progress'][-1] if run['progress'] else 'Unknown error'})}\n\n"
                break

            await asyncio.sleep(0.5)

        if run_id in _runs:
            del _runs[run_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _save_backtest_to_db(req, stats, trades, equity_curve, duration_ms):
    execute("UPDATE gd_backtest_runs SET is_latest = FALSE WHERE is_latest = TRUE AND strategies @> %s", (MICRO_STRATEGIES_FILTER,))

    run_id = insert_returning(
        """INSERT INTO gd_backtest_runs
           (strategies, start_date, end_date, capital, risk_pct,
            total_trades, wins, losses, win_rate, profit_factor,
            total_pnl, max_drawdown_pct, avg_win, avg_loss, risk_reward, duration_ms)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (MICRO_STRATEGIES_FILTER, req.start_date, req.end_date, float(req.capital), float(req.risk_pct),
         int(stats["total_trades"]), int(stats["wins"]), int(stats["losses"]),
         float(stats["win_rate"]), float(stats["profit_factor"]),
         float(stats["total_pnl"]), float(stats["max_drawdown_pct"]),
         float(stats["avg_win"]), float(stats["avg_loss"]), float(stats["risk_reward"]), int(duration_ms))
    )

    if not run_id:
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            trade_rows = [
                (run_id, i, str(t["date"]), int(t["year"]), int(t["month"]), t["strategy"], t["direction"],
                 float(t["entry"]), float(t["sl"]), float(t["tp"]), float(t["exit_price"]),
                 float(t["pnl_unit"]), float(t["pnl_sized"]), float(t["units"]),
                 t["status"], int(t["bars_held"]), t["hold_human"], float(t["risk"]), float(t["r_mult"]), float(t["equity_after"]))
                for i, t in enumerate(trades)
            ]
            execute_values(
                cur,
                """INSERT INTO gd_backtest_trades
                   (run_id, trade_index, date, year, month, strategy, direction,
                    entry, sl, tp, exit_price, pnl_unit, pnl_sized, units,
                    status, bars_held, hold_human, risk, r_mult, equity_after)
                   VALUES %s""",
                trade_rows,
                page_size=500,
            )
            equity_rows = [
                (run_id, str(pt["date"]), float(pt["pnl"]), float(pt["equity"]))
                for pt in equity_curve
            ]
            execute_values(
                cur,
                "INSERT INTO gd_backtest_equity (run_id, date, cumulative_pnl, equity) VALUES %s",
                equity_rows,
                page_size=500,
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.get("/backtest/latest")
def get_latest_backtest():
    try:
        runs = execute(
            "SELECT * FROM gd_backtest_runs WHERE is_latest = TRUE AND strategies @> %s ORDER BY created_at DESC LIMIT 1",
            (MICRO_STRATEGIES_FILTER,),
            fetch=True
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
            gw = sum(float(t["pnl_sized"]) for t in trades if t["strategy"] == s and float(t["pnl_sized"]) > 0)
            gl = abs(sum(float(t["pnl_sized"]) for t in trades if t["strategy"] == s and float(t["pnl_sized"]) <= 0))
            st["pf"] = gw / gl if gl > 0 else 0
            st["pnl"] = round(st["pnl"], 2)

        monthly_map = {}
        for t in trades:
            key = f"{t['year']}-{t['month']:02d}"
            monthly_map[key] = monthly_map.get(key, 0) + float(t["pnl_sized"])
        monthly_pnl = [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly_map.items())]

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
            d["wr"] = round(d["wins"] / d["trades"], 3) if d["trades"] > 0 else 0
            d["pnl"] = round(d["pnl"], 2)
            d["start_fund"] = float(run["capital"])
            d["end_fund"] = round(float(run["capital"]) + d["pnl"], 2)
            d["return_pct"] = round(d["pnl"] / max(float(run["capital"]), 1) * 100, 1)
            yearly_pnl.append(d)

        return {
            "stats": {
                "total_trades": run["total_trades"],
                "wins": run["wins"],
                "losses": run["losses"],
                "win_rate": float(run["win_rate"]),
                "profit_factor": float(run["profit_factor"]),
                "total_pnl": float(run["total_pnl"]),
                "max_drawdown_pct": float(run["max_drawdown_pct"]),
                "avg_win": float(run["avg_win"]) if run.get("avg_win") else 0,
                "avg_loss": float(run["avg_loss"]) if run.get("avg_loss") else 0,
                "risk_reward": float(run["risk_reward"]) if run.get("risk_reward") else 0,
                "trades_per_year": round(run["total_trades"] / max(len(yearly_map), 1), 1),
                "months": len(yearly_map) * 12,
                "strategies": strat_stats,
            },
            "trades": [dict(t) for t in trades],
            "equity_curve": [dict(e) for e in equity],
            "monthly_pnl": monthly_pnl,
            "yearly_pnl": yearly_pnl,
            "duration_ms": run.get("duration_ms", 0),
            "config": {
                "strategies": run["strategies"],
                "start_date": run["start_date"],
                "end_date": run["end_date"],
                "capital": float(run["capital"]),
                "risk_pct": float(run["risk_pct"]),
            },
            "created_at": run["created_at"].isoformat() if run.get("created_at") else None,
        }
    except Exception as e:
        print(f"Oil Micro backtest/latest error: {e}")
        return {"result": None}
