"""Micro Alpha-Sweep scheduler — rolling 4hr consolidation windows every 2 hours."""
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution import get_candles, get_current_price, get_account_summary
from backend.db import execute
import re

from config import MICRO_ALPHA_SWEEP, STRATEGY_RISK, MAX_UNITS, slippage, ENGULFING_TOLERANCE, DD_PROTECTION, TRADE_REF_PREFIX
from scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, _log_journal

scheduler = BackgroundScheduler(timezone="UTC")

# Daily PnL tracking (resets at midnight UTC)
_daily_state = {"date": None, "pnl": 0.0, "trades": 0}

# Sweep blacklist — persists across scan cycles, resets at midnight.
# Matches backtest behavior: once a sweep is consumed (trade taken, SL hit, or no engulfing found),
# it never fires again that day. Key format: "{bar_timestamp}_{sweep_dir}"
_traded_sweeps = {"date": None, "keys": set()}


def _parse_ts(ts_str: str) -> datetime:
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


def _get_active_windows(now: datetime) -> list:
    """Return all consolidation windows currently in their scan phase.
    Handles midnight wrap: windows can start at 22, 0, 2, ... up to 18.
    Market close: 21:00-22:00 UTC — no scanning during this hour.
    """
    cfg = MICRO_ALPHA_SWEEP
    close_start = cfg["market_close_start"]  # 21
    close_end = cfg["market_close_end"]      # 22
    current_hour = now.hour

    # Skip during market close
    if close_start <= current_hour < close_end:
        return []

    windows = []
    # Generate windows starting every 2 hours across full day (0,2,4,...,22)
    for start_hour in range(0, 24, cfg["scan_gap_hours"]):
        end_hour = (start_hour + cfg["consol_hours"]) % 24
        scan_end_hour = (start_hour + cfg["consol_hours"] + cfg["scan_after_hours"]) % 24

        # Skip windows whose consolidation or scan overlaps market close
        # If consolidation spans 21:00 (e.g. 20-00) or scan would run into 21:00
        consol_hours = _hours_in_range(start_hour, end_hour)
        if close_start in consol_hours:
            continue

        # Check if consolidation is done (current hour is past end_hour)
        if not _hour_past(current_hour, end_hour):
            continue

        # Check if scan window hasn't expired
        if _hour_past(current_hour, scan_end_hour):
            continue

        windows.append({
            "consol_start": start_hour,
            "consol_end": end_hour,
            "scan_until": scan_end_hour,
        })
    return windows


def _hours_in_range(start: int, end: int) -> set:
    """Return set of hours in [start, end) handling midnight wrap."""
    if start < end:
        return set(range(start, end))
    return set(range(start, 24)) | set(range(0, end))


def _hour_past(current: int, target: int) -> bool:
    """Check if current hour is past target, handling midnight wrap.
    'Past' means target occurred recently (within last 12 hours).
    """
    diff = (current - target) % 24
    return 0 < diff <= 12


def micro_sweep_job():
    """Every 3 min — scan all active rolling windows for sweeps + engulfings."""
    now = datetime.now(timezone.utc)
    cfg = MICRO_ALPHA_SWEEP


    # Reset daily state at midnight
    global _daily_state, _traded_sweeps
    today = now.date()
    if _daily_state["date"] != today:
        _daily_state = {"date": today, "pnl": 0.0, "trades": 0}
    if _traded_sweeps["date"] != today:
        _traded_sweeps = {"date": today, "keys": set()}

    # Daily max loss check — query ACTUAL daily P&L from DB (not local variable)
    daily_pnl_rows = execute(
        f"SELECT COALESCE(SUM(pnl_usd), 0) as daily_pnl FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time::date = %s AND pnl_usd IS NOT NULL",
        (today,), fetch=True
    )
    actual_daily_pnl = float(daily_pnl_rows[0]["daily_pnl"]) if daily_pnl_rows else 0
    _daily_state["pnl"] = actual_daily_pnl  # Sync local state with DB reality
    if DD_PROTECTION["daily_max_loss"] and actual_daily_pnl <= -DD_PROTECTION["daily_max_loss"]:
        return

    active_windows = _get_active_windows(now)
    if not active_windows:
        return

    print(f"  [MICRO {now.strftime('%H:%M:%S')} UTC] Scanning {len(active_windows)} active windows...")

    try:
        _run_micro_sweep(now, active_windows)
    except Exception as e:
        print(f"  [MICRO] Error: {e}")
        _log_journal("SYSTEM", "micro_alpha_sweep", "ERROR", None, {"error": str(e), "job": "micro_sweep"})


def position_monitor_job():
    """Every 1 min — check positions for SL/TP closures + max hold + break-even."""
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
    except Exception as e:
        print(f"  [MICRO] Position monitor error: {e}")
        _log_journal("SYSTEM", "micro_alpha_sweep", "ERROR", None, {"error": str(e), "job": "position_monitor"})


def _run_micro_sweep(now: datetime, active_windows: list):
    """Process all active windows for sweep detection."""
    cfg = MICRO_ALPHA_SWEEP
    today = now.date()

    # Check trades today
    existing = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trades_today = existing[0]["cnt"] if existing else 0
    if trades_today >= cfg["max_trades_per_day"]:
        return


    # Get H1 bars (complete only)
    h1_candles = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    if len(h1_candles) < 6:
        return

    # Daily bias (Variant C)
    daily_candles = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
    if len(daily_candles) < 2:
        return
    yesterday = daily_candles[-2]
    mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
    mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
    mid_high = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
    mid_low = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
    prev_range = mid_high - mid_low
    if prev_range <= 0:
        bias = "neutral"
    elif abs(mid_close - mid_open) / prev_range < 0.4:
        bias = "neutral"
    else:
        bias = "bullish" if mid_close > mid_open else "bearish"

    # Get M3 candles for engulfing detection
    m3_candles = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")
    if not m3_candles:
        return

    trade_placed_this_cycle = False

    # 5-min cooldown after last signal attempt (taken OR failed with order/SL error)
    from datetime import timedelta as _td
    recent_signal = execute(
        f"SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='micro_alpha_sweep' ORDER BY timestamp DESC LIMIT 1",
        fetch=True
    )
    if recent_signal and recent_signal[0]["timestamp"]:
        last_signal_time = recent_signal[0]["timestamp"]
        if last_signal_time.tzinfo is None:
            last_signal_time = last_signal_time.replace(tzinfo=timezone.utc)
        skip = recent_signal[0].get("skip_reason", "")
        # Cooldown applies if: signal was taken, OR it failed with execution error (same signal will fail again)
        if recent_signal[0]["taken"] or "order_error" in (skip or "") or "sl_too_close" in (skip or ""):
            if now < last_signal_time + _td(minutes=5):
                return  # Cooldown: same signal can't re-fire within 5 min

    for window in active_windows:
        if trades_today >= cfg["max_trades_per_day"] or trade_placed_this_cycle:
            break

        # Build consolidation range from H1 bars in this window (handles midnight wrap)
        consol_hours = _hours_in_range(window["consol_start"], window["consol_end"])
        consol_bars = []
        for c in h1_candles:
            ts = _parse_ts(c["timestamp"])
            if ts.hour in consol_hours:
                c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
                c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
                c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
                consol_bars.append(c)

        if len(consol_bars) < 2:
            continue

        range_high = max(c["mid_high"] for c in consol_bars)
        range_low = min(c["mid_low"] for c in consol_bars)
        consol_range = range_high - range_low

        if consol_range < cfg["min_range"]:
            continue

        # Scan bars: after consolidation, within scan window
        scan_bars = []
        for c in h1_candles:
            ts = _parse_ts(c["timestamp"])
            scan_hours = _hours_in_range(window["consol_end"], window["scan_until"])
            if ts.hour in scan_hours:
                c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
                c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
                c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
                scan_bars.append(c)

        if not scan_bars:
            continue

        # Detect sweeps
        bearish_level = range_high + cfg["sweep_threshold"]
        bullish_level = range_low - cfg["sweep_threshold"]

        for bar in scan_bars:
            if trades_today >= cfg["max_trades_per_day"]:
                break

            sweep_dir = None
            sweep_wick = None

            if bar["mid_high"] > bearish_level and bar["mid_close"] < range_high:
                sweep_dir = "bearish"
                sweep_wick = bar["mid_high"]
            elif bar["mid_low"] < bullish_level and bar["mid_close"] > range_low:
                sweep_dir = "bullish"
                sweep_wick = bar["mid_low"]

            if not sweep_dir:
                continue

            # Dedup: once a sweep is consumed (traded, SL'd, or no engulfing), never re-fire that day.
            # Matches backtest traded_sweeps behavior. Persists across 3-min scan cycles.
            sweep_key = f"{bar['timestamp']}_{sweep_dir}"
            if sweep_key in _traded_sweeps["keys"]:
                continue

            # One-at-a-time: if there are ANY open positions from Micro, don't enter again
            # until the position is closed (one-at-a-time rule)
            open_micro = execute(
                f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time IS NULL",
                fetch=True
            )
            if open_micro and open_micro[0]["cnt"] > 0:
                continue  # Already have an open Micro position — wait for it to close

            # Bias filter
            if bias != "neutral":
                if sweep_dir == "bullish" and bias != "bullish":
                    continue
                if sweep_dir == "bearish" and bias != "bearish":
                    continue

            # Find engulfing in M3 candles
            sweep_time = _parse_ts(bar["timestamp"])
            window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])

            relevant_m3 = []
            for c in m3_candles:
                ts = _parse_ts(c["timestamp"])
                if sweep_time < ts <= window_end:
                    relevant_m3.append(c)

            if len(relevant_m3) < 3:
                if now >= window_end:
                    _traded_sweeps["keys"].add(sweep_key)
                continue

            for j in range(2, len(relevant_m3)):
                c = relevant_m3[j]
                prev = relevant_m3[j - 1]

                co = (c["bid_open"] + c["ask_open"]) / 2
                cc = (c["bid_close"] + c["ask_close"]) / 2
                po = (prev["bid_open"] + prev["ask_open"]) / 2
                pc = (prev["bid_close"] + prev["ask_close"]) / 2

                ct, cb = max(co, cc), min(co, cc)
                pt, pb = max(po, pc), min(po, pc)

                tol = ENGULFING_TOLERANCE
                if sweep_dir == "bullish" and not (cc > co and cb <= pb + tol and ct >= pt - tol):
                    continue
                if sweep_dir == "bearish" and not (cc < co and cb <= pb + tol and ct >= pt - tol):
                    continue

                # Engulfing confirmed — calculate entry
                br = (c["ask_high"] + c["bid_high"]) / 2 - (c["ask_low"] + c["bid_low"]) / 2

                if sweep_dir == "bullish":
                    entry = c["ask_close"] + slippage(br)
                    sl = sweep_wick - cfg["sl_buffer"]
                    risk = entry - sl
                    if risk < cfg["min_sl"]:
                        sl = entry - cfg["min_sl"]
                        risk = cfg["min_sl"]
                    if risk < 0.3 or risk > consol_range * 0.8:
                        continue
                    tp = entry + consol_range * cfg["tp_multiplier"]
                    if tp - entry < risk * 0.8:
                        continue
                    direction = "long"
                else:
                    entry = c["bid_close"] - slippage(br)
                    sl = sweep_wick + cfg["sl_buffer"]
                    risk = sl - entry
                    if risk < cfg["min_sl"]:
                        sl = entry + cfg["min_sl"]
                        risk = cfg["min_sl"]
                    if risk < 0.3 or risk > consol_range * 0.8:
                        continue
                    tp = entry - consol_range * cfg["tp_multiplier"]
                    if entry - tp < risk * 0.8:
                        continue
                    direction = "short"

                # Execute
                trade_ref = execute_signal(
                    strategy="micro_alpha_sweep",
                    direction=direction,
                    entry_price=entry,
                    sl_price=sl,
                    tp_price=tp,
                    context={
                        "range_high": range_high, "range_low": range_low,
                        "consol_range": consol_range, "consol_window": f"{window['consol_start']}-{window['consol_end']}",
                        "sweep_dir": sweep_dir, "sweep_wick": sweep_wick, "bias": bias,
                    },
                    daily_pnl=_daily_state["pnl"],
                )
                _traded_sweeps["keys"].add(sweep_key)
                if trade_ref:
                    trades_today += 1
                    _daily_state["trades"] += 1
                    trade_placed_this_cycle = True
                break  # One engulfing per sweep

            # No engulfing found — only consume sweep if engulfing window has expired.
            # If window still open, a future M3 bar might form a valid engulfing.
            else:
                if now >= window_end:
                    _traded_sweeps["keys"].add(sweep_key)

            # If trade was placed, exit scan_bars loop
            if trade_placed_this_cycle:
                break
        # trade_placed_this_cycle checked at top of window loop


def start_scheduler():
    scheduler.add_job(micro_sweep_job, "cron", minute="*/3", id="micro_sweep_poll")
    scheduler.add_job(position_monitor_job, "cron", minute="*", id="micro_position_monitor")
    scheduler.start()
    print("Micro scheduler started: Rolling window sweep poll (every 3 min) + Position monitor (every 1 min)")


def stop_scheduler():
    scheduler.shutdown(wait=False)
