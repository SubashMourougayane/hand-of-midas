"""Micro State API — GET /api/micro/state."""
from fastapi import APIRouter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution import get_current_price, get_account_summary, get_open_trades
from backend.db import execute
from config import DD_STATE_ID, TRADE_REF_PREFIX

router = APIRouter()


@router.get("/state")
def get_state():
    price = get_current_price(instrument="XAU_USD")
    account = get_account_summary()
    positions = get_open_trades(instrument="XAU_USD")

    db_positions = execute(
        f"SELECT trade_ref, strategy, side, entry_price, sl_price as sl, tp_price as tp, units, entry_time "
        f"FROM gd_trades WHERE exit_time IS NULL AND trade_ref LIKE '{TRADE_REF_PREFIX}%%' ORDER BY entry_time DESC",
        fetch=True
    )

    dd_rows = execute(f"SELECT * FROM gd_dd_state WHERE id = {DD_STATE_ID}", fetch=True)
    dd_state = None
    if dd_rows:
        dd_state = {
            "consecutive_losses": dd_rows[0]["consecutive_losses"],
            "pause_counter": dd_rows[0]["pause_counter"],
            "equity": float(dd_rows[0]["equity"]),
            "peak_equity": float(dd_rows[0]["peak_equity"]),
        }

    signals = execute(
        f"SELECT timestamp, strategy, direction, entry_price, taken, skip_reason "
        f"FROM gd_signals WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' OR strategy='micro_alpha_sweep' ORDER BY timestamp DESC LIMIT 10",
        fetch=True
    )

    recent_trades = execute(
        f"SELECT trade_ref, strategy, side, pnl_gbp, pnl_usd, exit_reason, exit_time "
        f"FROM gd_trades WHERE exit_time IS NOT NULL AND trade_ref LIKE '{TRADE_REF_PREFIX}%%' ORDER BY exit_time DESC LIMIT 10",
        fetch=True
    )

    return {
        "price": price,
        "account": account,
        "oanda_positions": positions,
        "db_positions": [
            {
                "trade_ref": p["trade_ref"], "strategy": p["strategy"], "side": p["side"],
                "entry_price": float(p["entry_price"]) if p["entry_price"] else 0,
                "sl": float(p["sl"]) if p["sl"] else 0,
                "tp": float(p["tp"]) if p["tp"] else 0,
                "units": p["units"],
                "entry_time": p["entry_time"].isoformat() if p["entry_time"] else None,
            }
            for p in (db_positions or [])
        ],
        "dd_state": dd_state,
        "recent_signals": [
            {
                "timestamp": s["timestamp"].isoformat() if s["timestamp"] else None,
                "strategy": s["strategy"], "direction": s["direction"],
                "entry_price": float(s["entry_price"]) if s["entry_price"] else None,
                "taken": s["taken"], "skip_reason": s["skip_reason"] or "",
            }
            for s in (signals or [])
        ],
        "recent_trades": [
            {
                "trade_ref": t["trade_ref"], "strategy": t["strategy"], "side": t["side"],
                "pnl_gbp": float(t["pnl_gbp"]) if t["pnl_gbp"] else 0,
                "pnl_usd": float(t["pnl_usd"]) if t["pnl_usd"] else 0,
                "exit_reason": t["exit_reason"] or "",
                "exit_time": t["exit_time"].isoformat() if t["exit_time"] else None,
            }
            for t in (recent_trades or [])
        ],
        "scheduler_active": True,
    }
