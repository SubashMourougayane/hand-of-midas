"""SSE Stream — pushes live state + scan-status to frontend every 5s."""
import asyncio
import json
import time
import threading
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from backend.execution import get_current_price, get_candles, get_account_summary, get_open_trades
from backend.config import ALPHA_SWEEP
from backend.db import execute
from datetime import datetime, timezone, timedelta
import re

router = APIRouter()

# Shared state — updated by background thread, read by SSE generators
_live_data = {"state": None, "scan": None, "ts": 0}
_UPDATE_INTERVAL = 5  # seconds between refreshes
_thread_started = False


def _parse_ts(ts_str: str):
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


def _build_scan_status():
    """Build scan-status data (same logic as scan_status.py route)."""
    cfg = ALPHA_SWEEP
    now = datetime.now(timezone.utc)
    today = now.date()
    utc_hour = now.hour + now.minute / 60.0
    scan_active = cfg["scan_start"] <= utc_hour <= cfg["scan_end"]

    price = get_current_price(instrument="XAU_USD")
    if not price:
        return None

    current_mid = price["mid"]
    tradeable = price.get("tradeable", False)

    h1 = get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA") or []
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
                sweep_info = {"direction": "bearish", "wick": round(mid_high, 2), "time": c["timestamp"]}
            elif mid_low < bullish_sweep_level and mid_close > asia_low:
                sweep_detected = True
                sweep_info = {"direction": "bullish", "wick": round(mid_low, 2), "time": c["timestamp"]}

    trades_today = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    if sweep_detected and sweep_info:
        sweep_time = _parse_ts(sweep_info["time"])
        window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])
        if trade_count > 0:
            sweep_status = "TRADED"
        elif now > window_end:
            sweep_status = "EXPIRED"
        else:
            sweep_status = "ACTIVE"

    # Daily bias
    daily = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA") or []
    bias = "neutral"
    if len(daily) >= 2:
        yesterday = daily[-2]
        mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        mid_high_d = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
        mid_low_d = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
        prev_range = mid_high_d - mid_low_d
        if prev_range > 0 and abs(mid_close - mid_open) / prev_range >= 0.4:
            bias = "bullish" if mid_close > mid_open else "bearish"

    # Skip reasons
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
        "price": round(current_mid, 2),
        "spread": round(price["spread"], 2),
        "asia_high": round(asia_high, 2),
        "asia_low": round(asia_low, 2),
        "asia_range": round(asia_range, 2),
        "bearish_sweep_level": round(bearish_sweep_level, 2),
        "bullish_sweep_level": round(bullish_sweep_level, 2),
        "dist_to_bearish": round(dist_to_bearish, 2),
        "dist_to_bullish": round(dist_to_bullish, 2),
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
    """Build state data (same logic as state.py route)."""
    price = get_current_price()
    account = get_account_summary()
    positions = get_open_trades(instrument="XAU_USD")

    dd_rows = execute("SELECT * FROM gd_dd_state WHERE id = 1", fetch=True)
    dd_state = {}
    if dd_rows:
        dd_state = {k: float(v) if hasattr(v, '__float__') and k != 'id' else v for k, v in dict(dd_rows[0]).items()}

    signals = execute("SELECT * FROM gd_signals WHERE strategy NOT IN ('micro_alpha_sweep', 'alpha_sweep_oil') ORDER BY timestamp DESC LIMIT 10", fetch=True)
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

    open_trades = execute("SELECT * FROM gd_trades WHERE exit_time IS NULL ORDER BY entry_time DESC", fetch=True)
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

    recent_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NOT NULL ORDER BY exit_time DESC LIMIT 5", fetch=True
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


def _refresh_loop():
    """Background thread: refreshes combined data every 5 seconds."""
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
                payload = {
                    "state": _live_data["state"],
                    "scan": _live_data["scan"],
                }
                yield f"data: {json.dumps(payload, default=str)}\n\n"
                last_ts = _live_data["ts"]
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
