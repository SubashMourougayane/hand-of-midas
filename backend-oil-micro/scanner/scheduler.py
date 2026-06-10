"""Oil Micro Alpha-Sweep scheduler — rolling 4hr consolidation windows every 2 hours."""
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution import get_candles, get_current_price, get_account_summary, get_open_trades
from backend.db import execute
import re

from config import MICRO_ALPHA_SWEEP, STRATEGY_RISK, MAX_UNITS, slippage, ENGULFING_TOLERANCE, DD_PROTECTION, TRADE_REF_PREFIX
from scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, reconcile_orphans, _log_journal, _log_journal_safe

scheduler = BackgroundScheduler(timezone="UTC")

_daily_state = {"date": None, "pnl": 0.0, "trades": 0}

_traded_sweeps = {"date": None, "keys": set()}

_startup_cooldown_until = None


def _parse_ts(ts_str: str) -> datetime:
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


def _get_active_windows(now: datetime) -> list:
    """Return all consolidation windows currently in their scan phase."""
    cfg = MICRO_ALPHA_SWEEP
    close_start = cfg["market_close_start"]
    close_end = cfg["market_close_end"]
    current_hour = now.hour

    if close_start <= current_hour < close_end:
        return []

    windows = []
    for start_hour in range(0, 24, cfg["scan_gap_hours"]):
        end_hour = (start_hour + cfg["consol_hours"]) % 24
        scan_end_hour = (start_hour + cfg["consol_hours"] + cfg["scan_after_hours"]) % 24

        consol_hours = _hours_in_range(start_hour, end_hour)
        if close_start in consol_hours:
            continue

        if not _hour_past(current_hour, end_hour):
            continue

        if _hour_past(current_hour, scan_end_hour):
            continue

        windows.append({
            "consol_start": start_hour,
            "consol_end": end_hour,
            "scan_until": scan_end_hour,
        })
    return windows


def _hours_in_range(start: int, end: int) -> set:
    if start < end:
        return set(range(start, end))
    return set(range(start, 24)) | set(range(0, end))


def _hour_past(current: int, target: int) -> bool:
    diff = (current - target) % 24
    return 0 < diff <= 12


def micro_sweep_job():
    """Every 3 min — scan all active rolling windows for sweeps + engulfings."""
    now = datetime.now(timezone.utc)
    cfg = MICRO_ALPHA_SWEEP

    global _daily_state, _traded_sweeps
    today = now.date()
    if _daily_state["date"] != today:
        _daily_state = {"date": today, "pnl": 0.0, "trades": 0}
    if _traded_sweeps["date"] != today:
        _traded_sweeps = {"date": today, "keys": set()}

    # Daily max loss check from DB
    daily_pnl_rows = execute(
        f"SELECT COALESCE(SUM(pnl_usd), 0) as daily_pnl FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time::date = %s AND pnl_usd IS NOT NULL",
        (today,), fetch=True
    )
    actual_daily_pnl = float(daily_pnl_rows[0]["daily_pnl"]) if daily_pnl_rows else 0
    _daily_state["pnl"] = actual_daily_pnl
    if DD_PROTECTION["daily_max_loss"] and actual_daily_pnl <= -DD_PROTECTION["daily_max_loss"]:
        return

    active_windows = _get_active_windows(now)
    if not active_windows:
        return

    print(f"  [OIL-MICRO {now.strftime('%H:%M:%S')} UTC] Scanning {len(active_windows)} active windows...")

    try:
        _run_micro_sweep(now, active_windows)
    except Exception as e:
        print(f"  [OIL-MICRO] Error: {e}")
        _log_journal("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "micro_sweep"})


def position_monitor_job():
    """Every 1 min — check positions for SL/TP closures + max hold + break-even +
    reconcile any orphan broker positions not in DB (production safety net for
    the orphan-trade cascade pattern)."""
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
    except Exception as e:
        print(f"  [OIL-MICRO] Position monitor error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "position_monitor"})

    # Orphan reconciliation runs in its own try/except so a check_open_positions
    # failure doesn't skip the safety net, and vice versa.
    try:
        reconcile_orphans()
    except Exception as e:
        print(f"  [OIL-MICRO] Orphan reconciler error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "reconcile_orphans"})


def _run_micro_sweep(now: datetime, active_windows: list):
    """Process all active windows for sweep detection."""
    h1_candles = [c for c in get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    if len(h1_candles) < 6:
        return
    daily_candles = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
    if len(daily_candles) < 2:
        return
    m3_candles = get_candles(instrument="BCO_USD", granularity="M3", count=50, price="BA")
    if not m3_candles:
        return

    return _run_micro_sweep_core(now, active_windows, h1_candles, daily_candles, m3_candles)


def _run_micro_sweep_core(now: datetime, active_windows: list,
                          h1_candles: list, daily_candles: list, m3_candles: list,
                          dry_run: bool = False):
    """Core sweep logic — testable with injected data."""
    cfg = MICRO_ALPHA_SWEEP
    today = now.date()

    # Check trades today (max of DB and local counter)
    existing = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND entry_time::date = %s",
        (today,), fetch=True
    )
    db_trades_today = existing[0]["cnt"] if existing else 0
    trades_today = max(db_trades_today, _daily_state["trades"])
    if trades_today >= cfg["max_trades_per_day"]:
        return [] if dry_run else None

    # Daily bias (Combined V1+V2)
    yesterday = daily_candles[-2]
    mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
    mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
    mid_high = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
    mid_low = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
    prev_range = mid_high - mid_low
    if prev_range <= 0:
        bias = "neutral"
    else:
        body_pct = abs(mid_close - mid_open) / prev_range
        v1_bias = "neutral"
        if body_pct >= 0.4:
            v1_bias = "bullish" if mid_close > mid_open else "bearish"
        close_position = (mid_close - mid_low) / prev_range
        v2_bias = "neutral"
        if close_position >= 0.8:
            v2_bias = "bullish"
        elif close_position <= 0.2:
            v2_bias = "bearish"
        if v1_bias == "bearish" or v2_bias == "bearish":
            bias = "bearish"
        elif v1_bias == "bullish" or v2_bias == "bullish":
            bias = "bullish"
        else:
            bias = "neutral"

    trade_placed_this_cycle = False
    signals_found = []

    # 5-min cooldown after last signal
    recent_signal = execute(
        "SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='micro_alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 1",
        fetch=True
    )
    if recent_signal and recent_signal[0]["timestamp"]:
        last_signal_time = recent_signal[0]["timestamp"]
        if last_signal_time.tzinfo is None:
            last_signal_time = last_signal_time.replace(tzinfo=timezone.utc)
        skip = recent_signal[0].get("skip_reason", "")
        if recent_signal[0]["taken"] or "order_error" in (skip or "") or "sl_too_close" in (skip or ""):
            if now < last_signal_time + timedelta(minutes=5):
                return [] if dry_run else None

    # Startup cooldown (C8 fix)
    if _startup_cooldown_until and now < _startup_cooldown_until:
        return [] if dry_run else None

    for window in active_windows:
        if trades_today >= cfg["max_trades_per_day"] or trade_placed_this_cycle:
            break

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

            sweep_key = f"{bar['timestamp']}_{sweep_dir}"
            if sweep_key in _traded_sweeps["keys"]:
                continue

            # One-at-a-time: check DB
            open_micro = execute(
                f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time IS NULL",
                fetch=True
            )
            if open_micro and open_micro[0]["cnt"] > 0:
                continue
            # Also check MT5/OANDA directly
            mt5_open = get_open_trades()
            if mt5_open and len(mt5_open) > 0:
                continue

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
                    if risk < 0.01 or risk > consol_range * 0.8:
                        continue
                    tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                    tp = range_high - tp_buf
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
                    if risk < 0.01 or risk > consol_range * 0.8:
                        continue
                    tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                    tp = range_low + tp_buf
                    if entry - tp < risk * 0.8:
                        continue
                    direction = "short"

                if dry_run:
                    signals_found.append({
                        "time": c["timestamp"], "direction": direction,
                        "entry": round(entry, 4), "sl": round(sl, 4), "tp": round(tp, 4),
                        "risk": round(risk, 4), "bias": bias,
                        "range_high": range_high, "range_low": range_low,
                        "consol_range": consol_range, "sweep_wick": sweep_wick,
                    })
                    _traded_sweeps["keys"].add(sweep_key)
                    trades_today += 1
                    trade_placed_this_cycle = True
                else:
                    # CRITICAL: Add sweep to blacklist BEFORE placing the order.
                    # If execute_signal raises mid-flight (e.g. JSON serialization
                    # error in journal write), the next 3-min cron must NOT retry
                    # the same sweep. Pre-marking it here breaks the orphan-trade
                    # cascade observed on June 10 (see
                    # docs/JUNE10_OIL_4ORPHANS_INVESTIGATION.md).
                    _traded_sweeps["keys"].add(sweep_key)
                    _daily_state["trades"] += 1  # Optimistic — decremented if signal fails

                    try:
                        trade_ref = execute_signal(
                            strategy="micro_alpha_sweep_oil",
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
                        if trade_ref:
                            trades_today += 1
                            trade_placed_this_cycle = True
                        else:
                            # Signal was skipped (DD, sl_too_close, etc.) — roll back optimistic counter
                            _daily_state["trades"] = max(0, _daily_state["trades"] - 1)
                    except Exception as e:
                        # Order may have been placed even if persistence raised.
                        # Sweep stays blacklisted (above) so we don't re-fire.
                        # Daily counter stays incremented (conservative — assume order went through).
                        print(f"  [OIL-MICRO] execute_signal raised: {e}")
                        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "EXECUTE_SIGNAL_RAISED",
                                          entry, {"error": str(e), "sweep_key": sweep_key, "direction": direction})
                break

            else:
                if now >= window_end:
                    _traded_sweeps["keys"].add(sweep_key)

            if trade_placed_this_cycle:
                break

    return signals_found if dry_run else None


def _restore_traded_sweeps_on_startup():
    """On startup, block re-entry for recent signals (C8 fix)."""
    global _traded_sweeps, _startup_cooldown_until
    today = datetime.now(timezone.utc).date()
    _traded_sweeps = {"date": today, "keys": set()}

    now = datetime.now(timezone.utc)
    recent = execute(
        "SELECT timestamp FROM gd_signals WHERE strategy='micro_alpha_sweep_oil' AND taken=True ORDER BY timestamp DESC LIMIT 1",
        fetch=True
    )
    if recent and recent[0]["timestamp"]:
        last_ts = recent[0]["timestamp"]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        window_hours = MICRO_ALPHA_SWEEP.get("engulfing_window_hours", 0.75)
        window_expiry = last_ts + timedelta(hours=window_hours)
        if now < window_expiry:
            _startup_cooldown_until = window_expiry
            print(f"  [OIL-MICRO STARTUP] Cooldown active until {window_expiry.strftime('%H:%M:%S')} UTC")
        else:
            _startup_cooldown_until = None
            print(f"  [OIL-MICRO STARTUP] No active cooldown (last signal >45 min ago)")
    else:
        _startup_cooldown_until = None
        print(f"  [OIL-MICRO STARTUP] No signals today — clean start")


def daily_recon_job():
    """Send daily reconciliation report at 00:00 UTC. Reports yesterday's stats."""
    from backend.db import daily_recon_stats
    from backend import notify
    from datetime import timedelta
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    try:
        stats = daily_recon_stats("OIL-MI-%", "micro_alpha_sweep_oil", yesterday)
        notify.daily_recon("Oil Micro", str(yesterday), **stats)
    except Exception as e:
        print(f"  [OIL-MICRO] daily_recon_job error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "daily_recon"})


def start_scheduler():
    _restore_traded_sweeps_on_startup()
    scheduler.add_job(micro_sweep_job, "cron", minute="*/3", id="oil_micro_sweep_poll")
    scheduler.add_job(position_monitor_job, "cron", minute="*", id="oil_micro_position_monitor")
    scheduler.add_job(daily_recon_job, "cron", hour=0, minute=5, id="oil_micro_daily_recon")
    scheduler.start()
    print("Oil Micro scheduler started: Rolling window sweep poll (3min) + Position monitor + orphan reconciler (1min) + Daily recon (00:05 UTC)")


def stop_scheduler():
    scheduler.shutdown(wait=False)
