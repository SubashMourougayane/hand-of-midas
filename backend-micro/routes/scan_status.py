"""Micro Scan Status — shows active rolling consolidation windows."""
import time
import threading
import re
from fastapi import APIRouter
from datetime import datetime, timezone, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution import get_current_price, get_candles
from backend.db import execute
from config import MICRO_ALPHA_SWEEP, DD_PROTECTION, TRADE_REF_PREFIX

router = APIRouter()

_cache = {"price": None, "h1": [], "daily": [], "ts": 0, "fetching": False}
_CACHE_TTL = 10


def _refresh_cache():
    if _cache["fetching"]:
        return
    _cache["fetching"] = True
    try:
        price = get_current_price(instrument="XAU_USD")
        if price:
            _cache["price"] = price
        h1 = get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA")
        if h1:
            _cache["h1"] = h1
        daily = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
        if daily:
            _cache["daily"] = daily
        _cache["ts"] = time.time()
    except:
        pass
    finally:
        _cache["fetching"] = False


def _ensure_fresh():
    if time.time() - _cache["ts"] > _CACHE_TTL:
        threading.Thread(target=_refresh_cache, daemon=True).start()


def _parse_ts(ts_str: str):
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


@router.get("/scan-status")
def get_scan_status():
    _ensure_fresh()

    cfg = MICRO_ALPHA_SWEEP
    now = datetime.now(timezone.utc)
    today = now.date()

    price = _cache["price"]
    if not price:
        return {"error": "Price unavailable (warming up)"}

    current_mid = price["mid"]
    h1 = _cache["h1"] or []

    # Build all windows and their states
    active_windows = []
    for start_hour in range(cfg["scan_start_hour"], cfg["scan_end_hour"] - cfg["consol_hours"] + 1, cfg["scan_gap_hours"]):
        end_hour = start_hour + cfg["consol_hours"]
        scan_end_hour = end_hour + cfg["scan_after_hours"]

        # Compute range for this window
        consol_bars = []
        for c in h1:
            ts = _parse_ts(c["timestamp"])
            if ts.date() == today and start_hour <= ts.hour < end_hour:
                consol_bars.append(c)

        # Cap scan window at configured scan_end_hour (never scan past 20:00 UTC)
        scan_end_hour = min(scan_end_hour, cfg["scan_end_hour"] if "scan_end_hour" in cfg else 20)

        if len(consol_bars) < 2:
            if now.hour < end_hour:
                status = "building"
            else:
                status = "no_data"
            active_windows.append({
                "start": start_hour, "end": end_hour, "scan_until": scan_end_hour,
                "status": status, "range_high": 0, "range_low": 0, "range": 0,
                "sweep_detected": False, "sweep_info": None,
            })
            continue

        range_high = max((c["bid_high"] + c["ask_high"]) / 2 for c in consol_bars)
        range_low = min((c["bid_low"] + c["ask_low"]) / 2 for c in consol_bars)
        consol_range = range_high - range_low

        # Determine window status
        if now.hour < end_hour:
            status = "building"
        elif now.hour >= scan_end_hour:
            status = "expired"
        elif consol_range < cfg["min_range"]:
            status = "range_too_small"
        else:
            status = "scanning"

        # Check for sweeps in this window's scan phase
        sweep_detected = False
        sweep_info = None
        if status == "scanning" or status == "expired":
            bearish_level = range_high + cfg["sweep_threshold"]
            bullish_level = range_low - cfg["sweep_threshold"]
            for c in h1:
                ts = _parse_ts(c["timestamp"])
                if ts.date() == today and end_hour <= ts.hour < scan_end_hour:
                    mh = (c["bid_high"] + c["ask_high"]) / 2
                    ml = (c["bid_low"] + c["ask_low"]) / 2
                    mc = (c["bid_close"] + c["ask_close"]) / 2
                    if mh > bearish_level and mc < range_high:
                        sweep_detected = True
                        sweep_info = {"direction": "bearish", "wick": round(mh, 2), "time": c["timestamp"]}
                    elif ml < bullish_level and mc > range_low:
                        sweep_detected = True
                        sweep_info = {"direction": "bullish", "wick": round(ml, 2), "time": c["timestamp"]}

        active_windows.append({
            "start": start_hour, "end": end_hour, "scan_until": scan_end_hour,
            "status": status,
            "range_high": round(range_high, 2), "range_low": round(range_low, 2),
            "range": round(consol_range, 2),
            "sweep_detected": sweep_detected, "sweep_info": sweep_info,
        })

    # Daily bias
    daily = _cache["daily"] or []
    bias = "neutral"
    if len(daily) >= 2:
        yesterday = daily[-2]
        mc = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mo = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        mh = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
        ml = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
        prev_range = mh - ml
        if prev_range > 0 and abs(mc - mo) / prev_range >= 0.4:
            bias = "bullish" if mc > mo else "bearish"

    # Trades today
    trades_today = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    # Skip reasons
    skip_reasons = []
    scanning_windows = [w for w in active_windows if w["status"] == "scanning" and w["sweep_detected"]]
    if scanning_windows:
        sw = scanning_windows[0]
        if sw["sweep_info"] and sw["sweep_info"]["direction"] != bias and bias != "neutral":
            skip_reasons.append("bias_mismatch")
    if trade_count >= cfg["max_trades_per_day"]:
        skip_reasons.append("max_trades")

    return {
        "active_windows": active_windows,
        "price": round(current_mid, 2),
        "spread": round(price["spread"], 2),
        "tradeable": price.get("tradeable", False),
        "daily_bias": bias,
        "trades_today": trade_count,
        "max_trades_per_day": cfg["max_trades_per_day"],
        "utc_time": now.strftime("%H:%M:%S"),
        "skip_reasons": skip_reasons,
    }
