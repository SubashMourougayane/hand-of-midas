"""Oil State API — GET /api/oil/state (full state matching Gold)."""
from fastapi import APIRouter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution import get_current_price, get_account_summary, get_open_trades
from backend.db import execute

router = APIRouter()


@router.get("/state")
def get_state():
    price = get_current_price(instrument="BCO_USD")
    account = get_account_summary()
    positions = get_open_trades(instrument="BCO_USD")

    # DB positions (open Oil-Macro trades).
    # Issue #5 fix 2026-06-15: was 'OIL-%%' which matched OIL-MI- (Oil Micro).
    db_positions = execute(
        "SELECT trade_ref, strategy, side, entry_price, sl_price as sl, tp_price as tp, units, entry_time, "
        "COALESCE(mode, 'live') AS mode "
        "FROM gd_trades WHERE exit_time IS NULL AND strategy = 'alpha_sweep_oil' ORDER BY entry_time DESC",
        fetch=True
    )

    # DD state (Oil uses id=2)
    dd_rows = execute("SELECT * FROM gd_dd_state WHERE id = 2", fetch=True)
    dd_state = None
    if dd_rows:
        dd_state = {
            "consecutive_losses": dd_rows[0]["consecutive_losses"],
            "pause_counter": dd_rows[0]["pause_counter"],
            "equity": float(dd_rows[0]["equity"]),
            "peak_equity": float(dd_rows[0]["peak_equity"]),
        }

    # Recent signals
    signals = execute(
        "SELECT timestamp, strategy, direction, entry_price, taken, skip_reason "
        "FROM gd_signals WHERE strategy = 'alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 10",
        fetch=True
    )

    # Recent closed Oil-Macro trades.
    recent_trades = execute(
        "SELECT trade_ref, strategy, side, pnl_gbp, pnl_usd, exit_reason, exit_time "
        "FROM gd_trades WHERE exit_time IS NOT NULL AND strategy = 'alpha_sweep_oil' ORDER BY exit_time DESC LIMIT 10",
        fetch=True
    )

    return {
        "price": price,
        "account": account,
        "oanda_positions": positions,
        "db_positions": [
            {
                "trade_ref": p["trade_ref"],
                "strategy": p["strategy"],
                "side": p["side"],
                "entry_price": float(p["entry_price"]) if p["entry_price"] else 0,
                "sl": float(p["sl"]) if p["sl"] else 0,
                "tp": float(p["tp"]) if p["tp"] else 0,
                "units": p["units"],
                "entry_time": p["entry_time"].isoformat() if p["entry_time"] else None,
                # O1 (Filter #27 audit): surface mode so frontend can distinguish
                # pending limits ('pending') from filled positions ('live').
                "mode": p["mode"],
            }
            for p in (db_positions or [])
        ],
        "dd_state": dd_state,
        "recent_signals": [
            {
                "timestamp": s["timestamp"].isoformat() if s["timestamp"] else None,
                "strategy": s["strategy"],
                "direction": s["direction"],
                "entry_price": float(s["entry_price"]) if s["entry_price"] else None,
                "taken": s["taken"],
                "skip_reason": s["skip_reason"] or "",
            }
            for s in (signals or [])
        ],
        "recent_trades": [
            {
                "trade_ref": t["trade_ref"],
                "strategy": t["strategy"],
                "side": t["side"],
                "pnl_gbp": float(t["pnl_gbp"]) if t["pnl_gbp"] else 0,
                "pnl_usd": float(t["pnl_usd"]) if t["pnl_usd"] else 0,
                "exit_reason": t["exit_reason"] or "",
                "exit_time": t["exit_time"].isoformat() if t["exit_time"] else None,
            }
            for t in (recent_trades or [])
        ],
        "instrument": "BCO_USD",
        "scheduler_active": True,
        # Filter #28: surface live bias mode for dashboard.
        "bias_mode": _get_bias_mode_safe(),
    }


def _get_bias_mode_safe() -> str:
    """Read BIAS_MODE from this service's config. Default 'production' on any
    error so the dashboard never breaks."""
    try:
        from config import BIAS_MODE
        return BIAS_MODE
    except Exception:
        return "production"
