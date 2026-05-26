"""Oil Scan Status API — real-time sweep proximity for dashboard gauge."""
from fastapi import APIRouter
from backend.execution import get_current_price, get_candles
from backend.db import execute
from config import ALPHA_SWEEP
from datetime import datetime, timezone
import re

router = APIRouter()


def _parse_ts(ts_str: str):
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


@router.get("/scan-status")
def get_scan_status():
    cfg = ALPHA_SWEEP
    now = datetime.now(timezone.utc)
    today = now.date()
    utc_hour = now.hour + now.minute / 60.0

    scan_active = cfg["scan_start"] <= utc_hour <= cfg["scan_end"]

    price = get_current_price(instrument="BCO_USD")
    if not price:
        return {"error": "Price unavailable", "scan_active": scan_active}

    current_mid = price["mid"]
    tradeable = price.get("tradeable", False)

    h1 = get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA")
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

    trades_today = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep_oil' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    daily = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
    bias = "neutral"
    if len(daily) >= 2:
        yesterday = daily[-2]
        mc = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mo = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        bias = "bullish" if mc > mo else "bearish"

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
        "sweep_info": sweep_info,
        "daily_bias": bias,
        "trades_today": trade_count,
        "max_trades_per_day": cfg["max_trades_per_day"],
        "utc_time": now.strftime("%H:%M:%S"),
    }
