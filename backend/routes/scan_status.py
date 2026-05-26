"""Scan Status API — real-time sweep proximity for dashboard gauge."""
import time
from fastapi import APIRouter
from backend.execution.oanda_executor import get_current_price, get_candles
from backend.config import ALPHA_SWEEP
from backend.db import execute
from datetime import datetime, timezone
import re

router = APIRouter()

_scan_cache = {"data": None, "ts": 0}
_CACHE_TTL = 15  # seconds


def _parse_ts(ts_str: str):
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


@router.get("/scan-status")
def get_scan_status():
    """Real-time Alpha-Sweep scan state. Cached 15s to avoid OANDA 522 blocking."""
    now_ts = time.time()
    if _scan_cache["data"] and (now_ts - _scan_cache["ts"]) < _CACHE_TTL:
        return _scan_cache["data"]

    cfg = ALPHA_SWEEP
    now = datetime.now(timezone.utc)
    today = now.date()
    utc_hour = now.hour + now.minute / 60.0

    scan_active = cfg["scan_start"] <= utc_hour <= cfg["scan_end"]

    price = get_current_price(instrument="XAU_USD")
    if not price:
        return {"error": "Price unavailable", "scan_active": scan_active}

    current_mid = price["mid"]
    tradeable = price.get("tradeable", False)

    h1 = get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA")
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

    dist_to_bearish = current_mid - asia_high
    dist_to_bullish = asia_low - current_mid

    asia_mid = (asia_high + asia_low) / 2
    half_range = asia_range / 2 + sweep_threshold

    if current_mid >= asia_mid:
        proximity_pct = min(100, max(0, (current_mid - asia_mid) / (half_range) * 100))
        sweep_direction = "bearish"
    else:
        proximity_pct = min(100, max(0, (asia_mid - current_mid) / (half_range) * 100))
        sweep_direction = "bullish"

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

    trades_today = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    # Daily bias — Variant C: strong body = directional, weak body = neutral
    daily = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
    bias = "neutral"
    if len(daily) >= 2:
        yesterday = daily[-2]
        mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        mid_high_d = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
        mid_low_d = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
        prev_range = mid_high_d - mid_low_d
        if prev_range <= 0:
            bias = "neutral"
        elif abs(mid_close - mid_open) / prev_range < 0.4:
            bias = "neutral"
        else:
            bias = "bullish" if mid_close > mid_open else "bearish"

    result = {
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
        "sweep_info": sweep_info,
        "daily_bias": bias,
        "trades_today": trade_count,
        "max_trades_per_day": cfg["max_trades_per_day"],
        "utc_time": now.strftime("%H:%M:%S"),
    }

    _scan_cache["data"] = result
    _scan_cache["ts"] = now_ts
    return result
