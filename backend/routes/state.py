"""State API — GET /api/gold/state for live dashboard."""
import time
from fastapi import APIRouter
from backend.execution.oanda_executor import get_current_price, get_account_summary, get_open_trades
from backend.db import execute

router = APIRouter()

_state_cache = {"data": None, "ts": 0}
_CACHE_TTL = 15  # seconds


@router.get("/state")
def get_state():
    """Current live state — price, account, positions, DD state, recent signals.
    Cached for 15s to prevent OANDA 522 retries from blocking the dashboard."""
    now = time.time()
    if _state_cache["data"] and (now - _state_cache["ts"]) < _CACHE_TTL:
        return _state_cache["data"]

    price = get_current_price()
    account = get_account_summary()
    positions = get_open_trades(instrument="XAU_USD")

    # DD state
    dd_rows = execute("SELECT * FROM gd_dd_state WHERE id = 1", fetch=True)
    dd_state = dict(dd_rows[0]) if dd_rows else {}
    dd_state = {k: float(v) if hasattr(v, '__float__') and k != 'id' else v for k, v in dd_state.items()}

    # Recent signals (last 10)
    signals = execute(
        "SELECT * FROM gd_signals ORDER BY timestamp DESC LIMIT 10",
        fetch=True
    )
    signals_list = []
    for s in (signals or []):
        signals_list.append({
            "timestamp": s["timestamp"].isoformat() if s["timestamp"] else None,
            "strategy": s["strategy"],
            "direction": s["direction"],
            "entry_price": float(s["entry_price"]) if s["entry_price"] else None,
            "taken": s["taken"],
            "skip_reason": s["skip_reason"],
        })

    # Open trades from DB
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL ORDER BY entry_time DESC",
        fetch=True
    )
    db_positions = []
    for t in (open_trades or []):
        db_positions.append({
            "trade_ref": t["trade_ref"],
            "strategy": t["strategy"],
            "side": t["side"],
            "entry_price": float(t["entry_price"]),
            "sl": float(t["sl_price"]) if t["sl_price"] else None,
            "tp": float(t["tp_price"]) if t["tp_price"] else None,
            "units": t["units"],
            "entry_time": t["entry_time"].isoformat() if t["entry_time"] else None,
        })

    # Recent closed trades (last 5)
    recent_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NOT NULL ORDER BY exit_time DESC LIMIT 5",
        fetch=True
    )
    recent = []
    for t in (recent_trades or []):
        recent.append({
            "trade_ref": t["trade_ref"],
            "strategy": t["strategy"],
            "side": t["side"],
            "pnl_gbp": float(t["pnl_gbp"]) if t["pnl_gbp"] else 0,
            "pnl_usd": float(t["pnl_usd"]) if t["pnl_usd"] else 0,
            "exit_reason": t["exit_reason"],
            "exit_time": t["exit_time"].isoformat() if t["exit_time"] else None,
        })

    result = {
        "price": price,
        "account": account,
        "oanda_positions": positions,
        "db_positions": db_positions,
        "dd_state": dd_state,
        "recent_signals": signals_list,
        "recent_trades": recent,
        "scheduler_active": True,
    }

    _state_cache["data"] = result
    _state_cache["ts"] = now
    return result
