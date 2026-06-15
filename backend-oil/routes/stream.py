"""Oil SSE Stream — pushes live state + scan-status to frontend every 5s."""
import asyncio
import json
import time
import threading
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from backend.execution import get_current_price, get_candles, get_account_summary, get_open_trades
from backend.db import execute
from config import ALPHA_SWEEP
from datetime import datetime, timezone, timedelta
import re

router = APIRouter()

_live_data = {"state": None, "scan": None, "ts": 0}
_UPDATE_INTERVAL = 5
_thread_started = False


def _parse_ts(ts_str: str):
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


def _build_scan_status():
    cfg = ALPHA_SWEEP
    now = datetime.now(timezone.utc)
    today = now.date()
    utc_hour = now.hour + now.minute / 60.0
    scan_active = cfg["scan_start"] <= utc_hour <= cfg["scan_end"]

    price = get_current_price(instrument="BCO_USD")
    if not price:
        return None

    current_mid = price["mid"]
    tradeable = price.get("tradeable", False)

    h1 = get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA") or []
    asia_high, asia_low = 0, 999999
    for c in h1:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and 0 <= ts.hour < 8:
            asia_high = max(asia_high, (c["bid_high"] + c["ask_high"]) / 2)
            asia_low = min(asia_low, (c["bid_low"] + c["ask_low"]) / 2)

    if asia_high == 0 or asia_low == 999999:
        return None

    asia_range = asia_high - asia_low
    sweep_threshold = cfg["sweep_threshold"]
    bearish_sweep_level = asia_high + sweep_threshold
    bullish_sweep_level = asia_low - sweep_threshold

    dist_to_bearish = bearish_sweep_level - current_mid
    dist_to_bullish = current_mid - bullish_sweep_level

    if current_mid >= bearish_sweep_level:
        sweep_direction = "bearish"
        proximity_pct = 100.0
    elif current_mid <= bullish_sweep_level:
        sweep_direction = "bullish"
        proximity_pct = 100.0
    elif current_mid >= (asia_high + asia_low) / 2:
        sweep_direction = "bearish"
        full_range = bearish_sweep_level - asia_low
        proximity_pct = min(100, max(0, (1 - dist_to_bearish / full_range) * 100)) if full_range > 0 else 0
    else:
        sweep_direction = "bullish"
        full_range = asia_high - bullish_sweep_level
        proximity_pct = min(100, max(0, (1 - dist_to_bullish / full_range) * 100)) if full_range > 0 else 0

    sweep_detected = False
    sweep_info = None
    sweep_status = "WAITING"
    for c in h1:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and ts.hour >= cfg["scan_start"]:
            mid_high = (c["bid_high"] + c["ask_high"]) / 2
            mid_low = (c["bid_low"] + c["ask_low"]) / 2
            mid_close = (c["bid_close"] + c["ask_close"]) / 2
            if mid_high > bearish_sweep_level and mid_close < asia_high:
                sweep_detected = True
                sweep_info = {"direction": "bearish", "wick": round(mid_high, 4), "time": c["timestamp"]}
            elif mid_low < bullish_sweep_level and mid_close > asia_low:
                sweep_detected = True
                sweep_info = {"direction": "bullish", "wick": round(mid_low, 4), "time": c["timestamp"]}

    trades_today = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep_oil' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    if sweep_detected and sweep_info:
        sweep_time = _parse_ts(sweep_info["time"])
        window_end = sweep_time + timedelta(hours=cfg.get("engulfing_window_hours", 2))
        if trade_count > 0:
            sweep_status = "TRADED"
        elif now > window_end:
            sweep_status = "EXPIRED"
        else:
            sweep_status = "ACTIVE"

    daily = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA") or []
    bias = "neutral"
    if len(daily) >= 2:
        yesterday = daily[-2]
        mc = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mo = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        bias = "bullish" if mc > mo else "bearish"

    skip_reasons = []
    if sweep_detected and sweep_info:
        sweep_dir = sweep_info["direction"]
        if sweep_dir != bias and bias != "neutral":
            skip_reasons.append("bias_mismatch")
        if sweep_status == "EXPIRED":
            skip_reasons.append("expired")
        if trade_count >= cfg["max_trades_per_day"]:
            skip_reasons.append("max_trades")
        if not scan_active:
            skip_reasons.append("outside_window")

    return {
        "scan_active": scan_active,
        "tradeable": tradeable,
        "price": round(current_mid, 4),
        "spread": round(price["spread"], 4),
        "asia_high": round(asia_high, 4),
        "asia_low": round(asia_low, 4),
        "asia_range": round(asia_range, 4),
        "bearish_sweep_level": round(bearish_sweep_level, 4),
        "bullish_sweep_level": round(bullish_sweep_level, 4),
        "dist_to_bearish": round(dist_to_bearish, 4),
        "dist_to_bullish": round(dist_to_bullish, 4),
        "proximity_pct": round(proximity_pct, 1),
        "sweep_direction": sweep_direction,
        "sweep_detected": sweep_detected,
        "sweep_status": sweep_status,
        "sweep_info": sweep_info,
        "daily_bias": bias,
        "trades_today": trade_count,
        "max_trades_per_day": cfg["max_trades_per_day"],
        "utc_time": now.strftime("%H:%M:%S"),
        "skip_reasons": skip_reasons,
    }


def _build_state():
    price = get_current_price(instrument="BCO_USD")
    account = get_account_summary()
    positions = get_open_trades(instrument="BCO_USD")

    # Issue #5 fix 2026-06-15: was 'OIL-%%' which matched OIL-MI- (Oil Micro).
    db_positions = execute(
        "SELECT trade_ref, strategy, side, entry_price, sl_price as sl, tp_price as tp, units, entry_time "
        "FROM gd_trades WHERE exit_time IS NULL AND strategy = 'alpha_sweep_oil' ORDER BY entry_time DESC",
        fetch=True
    )
    dd_rows = execute("SELECT * FROM gd_dd_state WHERE id = 2", fetch=True)
    dd_state = None
    if dd_rows:
        dd_state = {
            "consecutive_losses": dd_rows[0]["consecutive_losses"],
            "pause_counter": dd_rows[0]["pause_counter"],
            "equity": float(dd_rows[0]["equity"]),
            "peak_equity": float(dd_rows[0]["peak_equity"]),
        }

    signals = execute(
        "SELECT timestamp, strategy, direction, entry_price, taken, skip_reason "
        "FROM gd_signals WHERE strategy = 'alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 10",
        fetch=True
    )
    recent_trades = execute(
        "SELECT trade_ref, strategy, side, pnl_gbp, pnl_usd, exit_reason, exit_time "
        "FROM gd_trades WHERE exit_time IS NOT NULL AND strategy = 'alpha_sweep_oil' ORDER BY exit_time DESC LIMIT 5",
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


def _refresh_loop():
    while True:
        try:
            scan = _build_scan_status()
            state = _build_state()
            if scan:
                _live_data["scan"] = scan
            if state:
                _live_data["state"] = state
            _live_data["ts"] = time.time()
        except Exception:
            pass
        time.sleep(_UPDATE_INTERVAL)


def _ensure_thread():
    global _thread_started
    if not _thread_started:
        _thread_started = True
        t = threading.Thread(target=_refresh_loop, daemon=True)
        t.start()


@router.get("/stream")
async def stream():
    """SSE endpoint — pushes combined state+scan every 5 seconds."""
    _ensure_thread()

    async def event_generator():
        last_ts = 0
        while True:
            if _live_data["ts"] > last_ts and _live_data["state"] and _live_data["scan"]:
                payload = {"state": _live_data["state"], "scan": _live_data["scan"]}
                yield f"data: {json.dumps(payload, default=str)}\n\n"
                last_ts = _live_data["ts"]
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
