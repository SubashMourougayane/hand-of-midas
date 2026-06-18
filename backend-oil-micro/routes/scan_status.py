"""Oil Micro Scan Status — shows active rolling consolidation windows."""
import time
import threading
import re
from fastapi import APIRouter
from datetime import datetime, timezone
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
        price = get_current_price(instrument="BCO_USD")
        if price:
            _cache["price"] = price
        h1 = get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA")
        if h1:
            _cache["h1"] = h1
        daily = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
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


def _hours_in_range(start: int, end: int) -> set:
    if start < end:
        return set(range(start, end))
    return set(range(start, 24)) | set(range(0, end))


def _hour_past(current: int, target: int) -> bool:
    diff = (current - target) % 24
    return 0 < diff <= 12


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

    close_start = cfg.get("market_close_start", 21)
    close_end = cfg.get("market_close_end", 22)

    active_windows = []
    for start_hour in range(0, 24, cfg["scan_gap_hours"]):
        end_hour = (start_hour + cfg["consol_hours"]) % 24
        scan_end_hour = (start_hour + cfg["consol_hours"] + cfg["scan_after_hours"]) % 24

        consol_hours = _hours_in_range(start_hour, end_hour)
        if close_start in consol_hours:
            continue

        consol_bars = []
        for c in h1:
            ts = _parse_ts(c["timestamp"])
            if ts.hour in consol_hours:
                consol_bars.append(c)

        if not _hour_past(now.hour, end_hour):
            status = "building"
        elif _hour_past(now.hour, scan_end_hour):
            status = "expired"
        elif len(consol_bars) < 2:
            status = "no_data"
        else:
            range_high = max((c["bid_high"] + c["ask_high"]) / 2 for c in consol_bars)
            range_low = min((c["bid_low"] + c["ask_low"]) / 2 for c in consol_bars)
            consol_range = range_high - range_low
            if consol_range < cfg["min_range"]:
                status = "range_too_small"
            else:
                status = "scanning"

        if len(consol_bars) < 2 or status in ("building", "no_data"):
            active_windows.append({
                "start": start_hour, "end": end_hour, "scan_until": scan_end_hour,
                "status": status, "range_high": 0, "range_low": 0, "range": 0,
                "sweep_detected": False, "sweep_info": None,
            })
            continue

        range_high = max((c["bid_high"] + c["ask_high"]) / 2 for c in consol_bars)
        range_low = min((c["bid_low"] + c["ask_low"]) / 2 for c in consol_bars)
        consol_range = range_high - range_low

        sweep_detected = False
        sweep_info = None
        if status == "scanning":
            bearish_level = range_high + cfg["sweep_threshold"]
            bullish_level = range_low - cfg["sweep_threshold"]
            scan_hours = _hours_in_range(end_hour, scan_end_hour)
            for c in h1:
                ts = _parse_ts(c["timestamp"])
                if ts.hour in scan_hours:
                    mh = (c["bid_high"] + c["ask_high"]) / 2
                    ml = (c["bid_low"] + c["ask_low"]) / 2
                    mc = (c["bid_close"] + c["ask_close"]) / 2
                    if mh > bearish_level and mc < range_high:
                        sweep_detected = True
                        sweep_info = {"direction": "bearish", "wick": round(mh, 4), "time": c["timestamp"]}
                    elif ml < bullish_level and mc > range_low:
                        sweep_detected = True
                        sweep_info = {"direction": "bullish", "wick": round(ml, 4), "time": c["timestamp"]}

        active_windows.append({
            "start": start_hour, "end": end_hour, "scan_until": scan_end_hour,
            "status": status,
            "range_high": round(range_high, 4), "range_low": round(range_low, 4),
            "range": round(consol_range, 4),
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
        if prev_range > 0:
            body_pct = abs(mc - mo) / prev_range
            v1_bias = "neutral"
            if body_pct >= 0.4:
                v1_bias = "bullish" if mc > mo else "bearish"
            close_pos = (mc - ml) / prev_range
            v2_bias = "neutral"
            if close_pos >= 0.8:
                v2_bias = "bullish"
            elif close_pos <= 0.2:
                v2_bias = "bearish"
            if v1_bias == "bearish" or v2_bias == "bearish":
                bias = "bearish"
            elif v1_bias == "bullish" or v2_bias == "bullish":
                bias = "bullish"

    # F28-M6: when BIAS_MODE=neutral, strategy ignores V1+V2; display effective.
    try:
        from config import BIAS_MODE as _bias_mode_cfg
        if _bias_mode_cfg == "neutral":
            bias = "neutral"
    except Exception:
        pass

    # Day 1 override fix: LIMIT_TTL_EXPIRED entries don't count toward cap.
    trades_today = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades "
        f"WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND entry_time::date = %s "
        f"AND (exit_reason IS NULL OR exit_reason NOT IN ('LIMIT_TTL_EXPIRED', 'LIMIT_TTL_EXPIRED_GRACE'))",
        (today,), fetch=True
    )
    trade_count = trades_today[0]["cnt"] if trades_today else 0

    return {
        "active_windows": active_windows,
        "price": round(current_mid, 4),
        "spread": round(price["spread"], 4) if price.get("spread") else 0,
        "tradeable": price.get("tradeable", False),
        "daily_bias": bias,
        "trades_today": trade_count,
        "max_trades_per_day": cfg["max_trades_per_day"],
        "utc_time": now.strftime("%H:%M:%S"),
    }
