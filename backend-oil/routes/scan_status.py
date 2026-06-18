"""Oil Scan Status API — real-time sweep proximity for dashboard gauge."""
import time
import threading
from fastapi import APIRouter
from backend.execution import get_current_price, get_candles
from backend.db import execute
from config import ALPHA_SWEEP
from datetime import datetime, timezone, timedelta
import re

router = APIRouter()

_scan_cache = {"price": None, "h1": [], "daily": [], "ts": 0, "fetching": False}
_SCAN_TTL = 10


def _refresh_scan_cache():
    """Fetch Oil scan data in background — keeps last good data on failure."""
    if _scan_cache["fetching"]:
        return
    _scan_cache["fetching"] = True
    try:
        price = get_current_price(instrument="BCO_USD")
        if price:
            _scan_cache["price"] = price
        h1 = get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA")
        if h1:
            _scan_cache["h1"] = h1
        daily = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
        if daily:
            _scan_cache["daily"] = daily
        _scan_cache["ts"] = time.time()
    except:
        pass
    finally:
        _scan_cache["fetching"] = False


def _ensure_scan_fresh():
    if time.time() - _scan_cache["ts"] > _SCAN_TTL:
        threading.Thread(target=_refresh_scan_cache, daemon=True).start()


def _parse_ts(ts_str: str):
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


@router.get("/scan-status")
def get_scan_status():
    _ensure_scan_fresh()

    cfg = ALPHA_SWEEP
    now = datetime.now(timezone.utc)
    today = now.date()
    utc_hour = now.hour + now.minute / 60.0

    scan_active = cfg["scan_start"] <= utc_hour <= cfg["scan_end"]

    price = _scan_cache["price"]
    if not price:
        return {"error": "Price unavailable (warming up)", "scan_active": scan_active}

    current_mid = price["mid"]
    tradeable = price.get("tradeable", False)

    h1 = _scan_cache["h1"] or []
    asia_high, asia_low = 0, 999999
    for c in h1:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and 0 <= ts.hour < 8:
            asia_high = max(asia_high, (c["bid_high"] + c["ask_high"]) / 2)
            asia_low = min(asia_low, (c["bid_low"] + c["ask_low"]) / 2)

    if asia_high == 0 or asia_low == 999999:
        return {"error": "Asia range not available", "scan_active": scan_active, "price": current_mid}

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
    for c in h1:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and ts.hour >= cfg["scan_start"]:
            mid_high = (c["bid_high"] + c["ask_high"]) / 2
            mid_low = (c["bid_low"] + c["ask_low"]) / 2
            mid_close = (c["bid_close"] + c["ask_close"]) / 2
            if mid_high > bearish_sweep_level and mid_close < asia_high:
                sweep_detected = True
                sweep_info = {"direction": "bearish", "wick": mid_high, "time": c["timestamp"]}
            elif mid_low < bullish_sweep_level and mid_close > asia_low:
                sweep_detected = True
                sweep_info = {"direction": "bullish", "wick": mid_low, "time": c["timestamp"]}

    # Day 1 override fix: LIMIT_TTL_EXPIRED entries don't count toward cap.
    trades_today = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades "
        "WHERE strategy='alpha_sweep_oil' AND entry_time::date = %s "
        "AND (exit_reason IS NULL OR exit_reason NOT IN ('LIMIT_TTL_EXPIRED', 'LIMIT_TTL_EXPIRED_GRACE'))",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    # Determine sweep status
    sweep_status = "WAITING"
    if sweep_detected and sweep_info:
        sweep_time = _parse_ts(sweep_info["time"])
        window_end = sweep_time + timedelta(hours=cfg.get("engulfing_window_hours", 2))
        if trade_count > 0:
            sweep_status = "TRADED"
        elif now > window_end:
            sweep_status = "EXPIRED"
        else:
            sweep_status = "ACTIVE"

    daily = _scan_cache["daily"] or []
    bias = "neutral"
    if len(daily) >= 2:
        yesterday = daily[-2]
        mc = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mo = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        bias = "bullish" if mc > mo else "bearish"

    # F28-M6: when BIAS_MODE=neutral, strategy ignores V1+V2; display effective.
    try:
        from config import BIAS_MODE as _bias_mode_cfg
        if _bias_mode_cfg == "neutral":
            bias = "neutral"
    except Exception:
        pass

    # Compute skip reasons
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
