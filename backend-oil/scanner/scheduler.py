"""Oil trading scheduler — Alpha-Sweep during London 08:00-10:30 UTC + position monitor."""
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution.oanda_executor import get_candles, get_current_price, get_account_summary
from backend.db import execute
from config import ALPHA_SWEEP, STRATEGY_RISK, MAX_UNITS, slippage
from scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, _log_journal

scheduler = BackgroundScheduler(timezone="UTC")


def london_session_job():
    """Every 3 min during 08:00-10:30 UTC — Oil Alpha-Sweep."""
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    if hour < 8.0 or hour > 10.5:
        return

    print(f"  [OIL {now.strftime('%H:%M:%S')} UTC] Alpha-Sweep polling...")
    try:
        _run_alpha_sweep()
    except Exception as e:
        print(f"  [OIL] Alpha-Sweep error: {e}")
        _log_journal("SYSTEM", "alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "london_session"})


def position_monitor_job():
    """Every 1 min — check Oil positions for SL/TP closures + max hold + break-even."""
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
    except Exception as e:
        print(f"  [OIL] Position monitor error: {e}")
        _log_journal("SYSTEM", "alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "position_monitor"})


def _run_alpha_sweep():
    """Check for Oil Asia sweep + M3 engulfing."""
    cfg = ALPHA_SWEEP
    today = datetime.now(timezone.utc).date()

    # Already traded today?
    existing = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep_oil' AND entry_time::date = %s",
        (today,), fetch=True
    )
    if existing and existing[0]["cnt"] > 0:
        return

    # Get H1 bars for Asia session
    h1_candles = get_candles(instrument="BCO_USD", granularity="H1", count=12, price="BA")
    if len(h1_candles) < 8:
        return

    # Asia bars (00:00-08:00 UTC) with mid prices
    asia_bars = []
    for c in h1_candles:
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if ts.date() == today and 0 <= ts.hour < 8:
            c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
            c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
            c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
            asia_bars.append(c)

    if len(asia_bars) < 3:
        return

    asia_high = max(c["mid_high"] for c in asia_bars)
    asia_low = min(c["mid_low"] for c in asia_bars)
    asia_range = asia_high - asia_low

    if asia_range < cfg["asia_min_range"]:
        _log_journal("SYSTEM", "alpha_sweep_oil", "NO_SIGNAL", None, {
            "reason": "asia_range_too_small", "asia_range": round(asia_range, 4),
            "min_required": cfg["asia_min_range"],
        })
        return

    # London bars with mid prices
    london_bars = []
    for c in h1_candles:
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if ts.date() == today and ts.hour >= 8:
            c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
            c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
            c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
            london_bars.append(c)

    if not london_bars:
        return

    # Detect sweep
    sweep_dir = None
    sweep_wick = 0.0
    for bar in london_bars:
        if bar["mid_high"] > asia_high + cfg["sweep_threshold"] and bar["mid_close"] < asia_high:
            sweep_dir = "bearish"
            sweep_wick = bar["mid_high"]
            break
        elif bar["mid_low"] < asia_low - cfg["sweep_threshold"] and bar["mid_close"] > asia_low:
            sweep_dir = "bullish"
            sweep_wick = bar["mid_low"]
            break

    if sweep_dir is None:
        return

    # Daily bias
    daily_candles = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
    if len(daily_candles) < 2:
        return
    yesterday = daily_candles[-2]
    mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
    mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
    bias = "bullish" if mid_close > mid_open else "bearish"

    if sweep_dir == "bullish" and bias != "bullish":
        _log_journal("SYSTEM", "alpha_sweep_oil", "NO_SIGNAL", None, {
            "reason": "bias_mismatch", "sweep_dir": sweep_dir, "daily_bias": bias,
        })
        return
    if sweep_dir == "bearish" and bias != "bearish":
        _log_journal("SYSTEM", "alpha_sweep_oil", "NO_SIGNAL", None, {
            "reason": "bias_mismatch", "sweep_dir": sweep_dir, "daily_bias": bias,
        })
        return

    # Check M3 for engulfing
    m3_candles = get_candles(instrument="BCO_USD", granularity="M3", count=50, price="BA")
    sweep_time = datetime.fromisoformat(london_bars[0]["timestamp"].replace("Z", "+00:00"))
    window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])

    relevant_m3 = []
    for c in m3_candles:
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if sweep_time < ts <= window_end:
            relevant_m3.append(c)

    if len(relevant_m3) < 3:
        return

    for j in range(2, len(relevant_m3)):
        c = relevant_m3[j]
        prev = relevant_m3[j - 1]

        co = (c["bid_open"] + c["ask_open"]) / 2
        cc = (c["bid_close"] + c["ask_close"]) / 2
        po = (prev["bid_open"] + prev["ask_open"]) / 2
        pc = (prev["bid_close"] + prev["ask_close"]) / 2

        ct, cb = max(co, cc), min(co, cc)
        pt, pb = max(po, pc), min(po, pc)

        if sweep_dir == "bullish" and not (cc > co and cb <= pb and ct >= pt):
            continue
        if sweep_dir == "bearish" and not (cc < co and cb <= pb and ct >= pt):
            continue

        # Engulfing confirmed — compute entry/SL/TP
        br = (c["ask_high"] + c["bid_high"]) / 2 - (c["ask_low"] + c["bid_low"]) / 2

        if sweep_dir == "bullish":
            entry = (c["ask_close"] + c["bid_close"]) / 2 + slippage(br)
            sl = sweep_wick - cfg["sl_buffer"]
            risk = entry - sl
            if risk < cfg["min_sl"]:
                sl = entry - cfg["min_sl"]
                risk = cfg["min_sl"]
            if risk < 0.01 or risk > asia_range * 0.8:
                continue
            tp = entry + asia_range * cfg["tp_multiplier"]
            if tp - entry < risk * 0.8:
                continue
            direction = "long"
        else:
            entry = (c["bid_close"] + c["ask_close"]) / 2 - slippage(br)
            sl = sweep_wick + cfg["sl_buffer"]
            risk = sl - entry
            if risk < cfg["min_sl"]:
                sl = entry + cfg["min_sl"]
                risk = cfg["min_sl"]
            if risk < 0.01 or risk > asia_range * 0.8:
                continue
            tp = entry - asia_range * cfg["tp_multiplier"]
            if entry - tp < risk * 0.8:
                continue
            direction = "short"

        # Execute via live_engine (handles DD, sizing, logging, persistence)
        execute_signal(
            direction=direction,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            context={
                "asia_high": asia_high, "asia_low": asia_low, "asia_range": asia_range,
                "sweep_dir": sweep_dir, "sweep_wick": sweep_wick, "bias": bias,
            },
        )
        return  # One trade per day


def start_scheduler():
    scheduler.add_job(london_session_job, "cron", minute="*/3", hour="8-10", id="oil_alpha_sweep_poll")
    scheduler.add_job(position_monitor_job, "cron", minute="*", id="oil_position_monitor")
    scheduler.start()
    print("Oil scheduler started: Alpha-Sweep London poll (08:00-10:30) + Position monitor (every 1 min)")


def stop_scheduler():
    scheduler.shutdown(wait=False)
