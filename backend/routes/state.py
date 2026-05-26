"""State API — GET /api/gold/state for live dashboard."""
import time
import threading
from fastapi import APIRouter
from backend.execution import get_current_price, get_account_summary, get_open_trades
from backend.db import execute

router = APIRouter()

_oanda_cache = {"price": None, "account": None, "positions": [], "ts": 0, "fetching": False}
_OANDA_TTL = 10  # refresh OANDA data every 10s in background


def _refresh_oanda():
    """Fetch OANDA data in background thread — never blocks API."""
    if _oanda_cache["fetching"]:
        return
    _oanda_cache["fetching"] = True
    try:
        _oanda_cache["price"] = get_current_price()
        _oanda_cache["account"] = get_account_summary()
        _oanda_cache["positions"] = get_open_trades(instrument="XAU_USD")
        _oanda_cache["ts"] = time.time()
    except:
        pass
    finally:
        _oanda_cache["fetching"] = False


def _ensure_oanda_fresh():
    """Kick off background refresh if stale. Never blocks."""
    if time.time() - _oanda_cache["ts"] > _OANDA_TTL:
        threading.Thread(target=_refresh_oanda, daemon=True).start()


@router.get("/state")
def get_state():
    """Current live state — NEVER blocks on OANDA. Returns last known data immediately."""
    _ensure_oanda_fresh()

    price = _oanda_cache["price"]
    account = _oanda_cache["account"]
    positions = _oanda_cache["positions"]

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

    return {
        "price": price,
        "account": account,
        "oanda_positions": positions,
        "db_positions": db_positions,
        "dd_state": dd_state,
        "recent_signals": signals_list,
        "recent_trades": recent,
        "scheduler_active": True,
    }
