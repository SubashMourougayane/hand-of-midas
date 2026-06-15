"""Micro Alpha-Sweep scheduler — rolling 4hr consolidation windows every 2 hours."""
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
from scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, check_alpha_sweep_partial_tp, reconcile_orphans, _log_journal, _log_journal_safe
from scanner import _log

scheduler = BackgroundScheduler(timezone="UTC")

# Daily PnL tracking (resets at midnight UTC)
_daily_state = {"date": None, "pnl": 0.0, "trades": 0}

# Sweep blacklist — persists across scan cycles, resets at midnight.
# Matches backtest behavior: once a sweep is consumed (trade taken, SL hit, or no engulfing found),
# it never fires again that day. Key format: "{bar_timestamp}_{sweep_dir}"
_traded_sweeps = {"date": None, "keys": set()}

# Startup cooldown: blocks new signals until engulfing window from last signal expires.
# Prevents C8: service restart mid-day re-firing old sweeps.
_startup_cooldown_until = None


def _parse_ts(ts_str: str) -> datetime:
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)


def _get_active_windows(now: datetime) -> list:
    """Return all consolidation windows currently in their scan phase.
    Handles midnight wrap: windows can start at 22, 0, 2, ... up to 18.
    Market close: 21:00-22:00 UTC — no scanning during this hour.

    Filter (shipped 2026-06-15): when MICRO_ALPHA_SWEEP['disable_market_close']
    is True, both the live-hour skip and the consolidation-overlap skip are
    bypassed. Backtest gain: PF 4.40→4.52, +$27k 21yr (+8.0%). The 21-22 UTC
    block was inherited from Oil Micro config; Gold Micro doesn't actually
    close at this hour. Oil Micro KEEPS the block (regresses without it).
    """
    cfg = MICRO_ALPHA_SWEEP
    disable_mc = cfg.get("disable_market_close", False)
    close_start = cfg["market_close_start"]  # 21
    close_end = cfg["market_close_end"]      # 22
    current_hour = now.hour

    # Skip during market close (bypassed when disable_market_close is on)
    if not disable_mc and close_start <= current_hour < close_end:
        return []

    windows = []
    # Generate windows starting every 2 hours across full day (0,2,4,...,22)
    for start_hour in range(0, 24, cfg["scan_gap_hours"]):
        end_hour = (start_hour + cfg["consol_hours"]) % 24
        scan_end_hour = (start_hour + cfg["consol_hours"] + cfg["scan_after_hours"]) % 24

        # Skip windows whose consolidation or scan overlaps market close.
        # Bypassed when disable_market_close is on.
        consol_hours = _hours_in_range(start_hour, end_hour)
        if not disable_mc and close_start in consol_hours:
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
        _log.warn("GATE", "daily_max_loss_hit", daily_pnl=actual_daily_pnl, max=-DD_PROTECTION["daily_max_loss"])
        return

    active_windows = _get_active_windows(now)
    if not active_windows:
        _log.debug("SCAN", "no_active_windows", hour=now.hour)
        return

    _log.info("SCAN", "tick", windows=len(active_windows), trades_today=_daily_state["trades"], daily_pnl=actual_daily_pnl)
    print(f"  [MICRO {now.strftime('%H:%M:%S')} UTC] Scanning {len(active_windows)} active windows...")

    try:
        _run_micro_sweep(now, active_windows)
    except Exception as e:
        _log.exception("SYSTEM", "scan_failed", job="micro_sweep_job", err=str(e))
        print(f"  [MICRO] Error: {e}")
        _log_journal("SYSTEM", "micro_alpha_sweep", "ERROR", None, {"error": str(e), "job": "micro_sweep"})


def position_monitor_job():
    """Every 1 min — check positions for SL/TP closures + max hold + break-even +
    reconcile orphan broker positions (production safety net)."""
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
        check_alpha_sweep_partial_tp()  # Filter #7 — bank half at halfway
    except Exception as e:
        _log.exception("SYSTEM", "position_monitor_failed", job="position_monitor", err=str(e))
        print(f"  [MICRO] Position monitor error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep", "ERROR", None, {"error": str(e), "job": "position_monitor"})

    # Orphan reconciliation: separate try/except so a check_open_positions
    # failure doesn't skip the safety net.
    try:
        reconcile_orphans()
    except Exception as e:
        _log.exception("SYSTEM", "orphan_reconciler_failed", job="reconcile_orphans", err=str(e))
        print(f"  [MICRO] Orphan reconciler error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep", "ERROR", None, {"error": str(e), "job": "reconcile_orphans"})


def _run_micro_sweep(now: datetime, active_windows: list):
    """Process all active windows for sweep detection."""
    # Fetch market data
    h1_candles = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    if len(h1_candles) < 6:
        _log.warn("BROKER", "h1_too_few", got=len(h1_candles), need=6)
        return
    daily_candles = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
    if len(daily_candles) < 2:
        _log.warn("BROKER", "daily_too_few", got=len(daily_candles), need=2)
        return
    m3_candles = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")
    if not m3_candles:
        _log.warn("BROKER", "m3_empty")
        return

    return _run_micro_sweep_core(now, active_windows, h1_candles, daily_candles, m3_candles)


def _run_micro_sweep_core(now: datetime, active_windows: list,
                          h1_candles: list, daily_candles: list, m3_candles: list,
                          dry_run: bool = False):
    """Core sweep logic — testable with injected data.

    Args:
        dry_run: If True, returns signals without executing (for harness testing).
    Returns:
        List of signal dicts if dry_run=True, else None.
    """
    cfg = MICRO_ALPHA_SWEEP
    today = now.date()

    # Check trades today
    existing = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND entry_time::date = %s",
        (today,), fetch=True
    )
    db_trades_today = existing[0]["cnt"] if existing else 0
    # Use max of DB count and local counter (DB may miss trades if INSERT failed)
    trades_today = max(db_trades_today, _daily_state["trades"])
    if trades_today >= cfg["max_trades_per_day"]:
        if not dry_run:
            _log.debug("GATE", "max_trades_reached", trades_today=trades_today, max=cfg["max_trades_per_day"])
        return [] if dry_run else None

    # Daily bias (Combined V1+V2: EITHER body% OR close-position triggers directional)
    yesterday = daily_candles[-2]
    mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
    mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
    mid_high = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
    mid_low = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
    prev_range = mid_high - mid_low
    if prev_range <= 0:
        bias = "neutral"
    else:
        # V1: body% > 40% of range = directional
        body_pct = abs(mid_close - mid_open) / prev_range
        v1_bias = "neutral"
        if body_pct >= 0.4:
            v1_bias = "bullish" if mid_close > mid_open else "bearish"
        # V2: close in top/bottom 20% of range
        close_position = (mid_close - mid_low) / prev_range
        v2_bias = "neutral"
        if close_position >= 0.8:
            v2_bias = "bullish"
        elif close_position <= 0.2:
            v2_bias = "bearish"
        # Combined: EITHER one says directional → use it
        if v1_bias == "bearish" or v2_bias == "bearish":
            bias = "bearish"
        elif v1_bias == "bullish" or v2_bias == "bullish":
            bias = "bullish"
        else:
            bias = "neutral"

    trade_placed_this_cycle = False
    signals_found = []  # For dry_run mode

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
        # Issue #19 fix 2026-06-15
        _skip = (skip or "")
        if recent_signal[0]["taken"] or _skip.startswith("order_error") or _skip.startswith("oanda_error") or _skip == "sl_too_close_to_price":
            if now < last_signal_time + _td(minutes=5):
                if not dry_run:
                    _log.debug("GATE", "cooldown_active", last_signal=last_signal_time.isoformat(), age_seconds=int((now - last_signal_time).total_seconds()), reason="recent_signal")
                return [] if dry_run else None

    # Startup cooldown: blocks until engulfing window from pre-restart signal expires (C8 fix)
    if _startup_cooldown_until and now < _startup_cooldown_until:
        if not dry_run:
            _log.debug("GATE", "startup_cooldown", until=_startup_cooldown_until.isoformat() if _startup_cooldown_until else None)
        return [] if dry_run else None

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
            if not dry_run:
                _log.debug("GATE", "consol_too_few_bars", window=f"{window['consol_start']}-{window['consol_end']}", got=len(consol_bars), need=2)
            continue

        range_high = max(c["mid_high"] for c in consol_bars)
        range_low = min(c["mid_low"] for c in consol_bars)
        consol_range = range_high - range_low

        if not dry_run:
            _log.debug("SCAN", "consol_range", window=f"{window['consol_start']}-{window['consol_end']}", high=range_high, low=range_low, range=consol_range, min_required=cfg["min_range"], bias=bias)

        if consol_range < cfg["min_range"]:
            if not dry_run:
                _log.debug("GATE", "range_too_small", window=f"{window['consol_start']}-{window['consol_end']}", range=consol_range, min=cfg["min_range"])
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
            if not dry_run:
                _log.debug("GATE", "no_scan_bars_yet", window=f"{window['consol_start']}-{window['consol_end']}", scan_until=window["scan_until"])
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

            if not dry_run:
                _log.debug("SCAN", "sweep_detected", bar=bar["timestamp"], dir=sweep_dir, wick=sweep_wick, range_high=range_high, range_low=range_low)

            # Dedup: once a sweep is consumed (traded, SL'd, or no engulfing), never re-fire that day.
            # Matches backtest traded_sweeps behavior. Persists across 3-min scan cycles.
            # Issue #9 fix 2026-06-15: also DB-backed for restart safety.
            sweep_key = f"{bar['timestamp']}_{sweep_dir}"
            if sweep_key not in _traded_sweeps["keys"] and not dry_run:
                from backend.db import is_sweep_consumed
                if is_sweep_consumed("gold-micro", today, sweep_key):
                    _traded_sweeps["keys"].add(sweep_key)
            if sweep_key in _traded_sweeps["keys"]:
                if not dry_run:
                    _log.debug("GATE", "sweep_already_traded", sweep_key=sweep_key)
                continue

            # One-at-a-time: check BOTH DB and MT5 (DB may miss trades if INSERT failed)
            open_micro = execute(
                f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time IS NULL",
                fetch=True
            )
            if open_micro and open_micro[0]["cnt"] > 0:
                if not dry_run:
                    _log.debug("GATE", "open_position_db", db_count=open_micro[0]["cnt"])
                continue  # Already have an open Micro position — wait for it to close
            # Also check MT5 directly — catches orphan positions not in DB
            mt5_open = get_open_trades()
            if mt5_open and len(mt5_open) > 0:
                if not dry_run:
                    _log.debug("GATE", "open_position_mt5", mt5_count=len(mt5_open))
                continue  # MT5 has open position (possibly not in DB)

            # Bias filter
            if bias != "neutral":
                if sweep_dir == "bullish" and bias != "bullish":
                    if not dry_run:
                        _log.debug("GATE", "bias_block", bias=bias, side=sweep_dir)
                    continue
                if sweep_dir == "bearish" and bias != "bearish":
                    if not dry_run:
                        _log.debug("GATE", "bias_block", bias=bias, side=sweep_dir)
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
                if not dry_run:
                    _log.debug("GATE", "engulfing_window_too_few_m3", sweep_key=sweep_key, m3_count=len(relevant_m3), window_end=window_end.isoformat(), expired=(now >= window_end))
                if now >= window_end:
                    _traded_sweeps["keys"].add(sweep_key)
                    if not dry_run:
                        from backend.db import mark_sweep_consumed
                        try: mark_sweep_consumed("gold-micro", today, sweep_key)
                        except Exception as e: _log.exception("SYSTEM", "mark_sweep_consumed_failed", err=str(e))
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
                        if not dry_run:
                            _log.debug("GATE", "risk_out_of_band", side="long", risk=risk, min=0.3, max=consol_range*0.8, consol_range=consol_range)
                        continue
                    tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                    tp = range_high - tp_buf
                    if tp - entry < risk * 0.8:
                        if not dry_run:
                            _log.debug("GATE", "tp_too_close", side="long", entry=entry, tp=tp, risk=risk, tp_distance=tp-entry, min_required=risk*0.8)
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
                        if not dry_run:
                            _log.debug("GATE", "risk_out_of_band", side="short", risk=risk, min=0.3, max=consol_range*0.8, consol_range=consol_range)
                        continue
                    tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                    tp = range_low + tp_buf
                    if entry - tp < risk * 0.8:
                        if not dry_run:
                            _log.debug("GATE", "tp_too_close", side="short", entry=entry, tp=tp, risk=risk, tp_distance=entry-tp, min_required=risk*0.8)
                        continue
                    direction = "short"

                # Execute (or collect in dry_run mode)
                if dry_run:
                    signals_found.append({
                        "time": c["timestamp"], "direction": direction,
                        "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
                        "risk": round(risk, 2), "bias": bias,
                        "range_high": range_high, "range_low": range_low,
                        "consol_range": consol_range, "sweep_wick": sweep_wick,
                    })
                    _traded_sweeps["keys"].add(sweep_key)
                    trades_today += 1
                    trade_placed_this_cycle = True
                else:
                    # CRITICAL: Add sweep to blacklist BEFORE placing the order.
                    # If execute_signal raises mid-flight, the next 3-min cron
                    # must NOT retry the same sweep. Pre-marking it breaks the
                    # orphan-trade cascade pattern (see
                    # docs/JUNE10_OIL_4ORPHANS_INVESTIGATION.md).
                    # Issue #9 fix 2026-06-15: also persist to DB for restart safety.
                    _traded_sweeps["keys"].add(sweep_key)
                    from backend.db import mark_sweep_consumed
                    try: mark_sweep_consumed("gold-micro", today, sweep_key)
                    except Exception as e: _log.exception("SYSTEM", "mark_sweep_consumed_failed", err=str(e))
                    _daily_state["trades"] += 1  # Optimistic — rolled back if signal skipped
                    _log.info("SIGNAL", "fired", direction=direction, entry=entry, sl=sl, tp=tp, risk=risk, sweep_wick=sweep_wick, sweep_dir=sweep_dir, bias=bias, range_high=range_high, range_low=range_low)

                    try:
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
                        if trade_ref:
                            trades_today += 1
                            trade_placed_this_cycle = True
                            _log.info("SIGNAL", "executed", trade_ref=trade_ref, direction=direction)
                        else:
                            # Signal skipped (DD, sl_too_close, etc.) — roll back optimistic counter
                            _daily_state["trades"] = max(0, _daily_state["trades"] - 1)
                            _log.warn("SIGNAL", "skipped_by_engine", direction=direction, sweep_key=sweep_key)
                    except Exception as e:
                        # Sweep stays blacklisted, counter stays incremented (conservative)
                        _log.exception("SYSTEM", "execute_signal_raised", direction=direction, sweep_key=sweep_key, err=str(e))
                        print(f"  [MICRO] execute_signal raised: {e}")
                        _log_journal_safe("SYSTEM", "micro_alpha_sweep", "EXECUTE_SIGNAL_RAISED",
                                          entry, {"error": str(e), "sweep_key": sweep_key, "direction": direction})
                break  # One engulfing per sweep

            # No engulfing found — only consume sweep if engulfing window has expired.
            # If window still open, a future M3 bar might form a valid engulfing.
            else:
                if now >= window_end:
                    _traded_sweeps["keys"].add(sweep_key)
                    if not dry_run:
                        from backend.db import mark_sweep_consumed
                        try: mark_sweep_consumed("gold-micro", today, sweep_key)
                        except Exception as e: _log.exception("SYSTEM", "mark_sweep_consumed_failed", err=str(e))

            # If trade was placed, exit scan_bars loop
            if trade_placed_this_cycle:
                break
        # trade_placed_this_cycle checked at top of window loop

    if not dry_run:
        _log.info("SCAN", "complete", trades_today=trades_today, fired_this_cycle=trade_placed_this_cycle)
    return signals_found if dry_run else None


def _restore_traded_sweeps_on_startup():
    """On startup, block re-entry for recent signals to prevent C8 (restart re-fire).

    We can't reconstruct the exact sweep_key (OANDA bar timestamps aren't in DB).
    Instead: if any signal was taken within the last 45 minutes (the engulfing window),
    the same sweep bar is still detectable in the H1 lookback. To prevent re-fire,
    we insert a synthetic 'startup_block' that forces the 5-min cooldown check to
    trigger until the engulfing window has fully expired.

    The approach: insert a fake signal record with timestamp = now, which makes
    the 5-min cooldown (line 182-195) block for 5 min. After that, if the signal
    was taken >45 min ago, the engulfing window has expired (no re-detection).
    If <45 min ago, we need a longer block.

    Simplest correct approach: query the most recent taken signal. If it's within
    the last 45 min, insert a cooldown-extending signal at NOW so the 5-min
    cooldown keeps re-triggering until the engulfing window expires.

    Actually even simpler: just store the last taken signal time in a module var
    and extend the cooldown check in the main loop to use max(DB cooldown, startup cooldown).
    """
    global _traded_sweeps, _startup_cooldown_until
    today = datetime.now(timezone.utc).date()
    _traded_sweeps = {"date": today, "keys": set()}

    now = datetime.now(timezone.utc)
    recent = execute(
        "SELECT timestamp FROM gd_signals WHERE strategy='micro_alpha_sweep' AND taken=True ORDER BY timestamp DESC LIMIT 1",
        fetch=True
    )
    if recent and recent[0]["timestamp"]:
        last_ts = recent[0]["timestamp"]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        # If last taken signal is within the engulfing window (45 min),
        # block until that signal's time + 45 min (window fully expires)
        window_hours = MICRO_ALPHA_SWEEP.get("engulfing_window_hours", 0.75)
        window_expiry = last_ts + timedelta(hours=window_hours)
        if now < window_expiry:
            _startup_cooldown_until = window_expiry
            print(f"  [MICRO STARTUP] Cooldown active until {window_expiry.strftime('%H:%M:%S')} UTC (prevents restart re-fire)")
        else:
            _startup_cooldown_until = None
            print(f"  [MICRO STARTUP] No active cooldown (last signal >45 min ago)")
    else:
        _startup_cooldown_until = None
        print(f"  [MICRO STARTUP] No signals today — clean start")


def daily_recon_job():
    """Send daily reconciliation report at 00:00 UTC. Reports yesterday's stats."""
    from backend.db import daily_recon_stats
    from backend import notify
    from datetime import timedelta
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    _log.info("SYSTEM", "daily_recon_start", yesterday=str(yesterday))
    try:
        stats = daily_recon_stats("GD-MI-%", "micro_alpha_sweep", yesterday)
        _log.info("SYSTEM", "daily_recon_stats", yesterday=str(yesterday), stats=str(stats))
        notify.daily_recon("Gold Micro", str(yesterday), **stats)
    except Exception as e:
        _log.exception("SYSTEM", "daily_recon_job_failed", yesterday=str(yesterday), err=str(e))
        print(f"  [MICRO] daily_recon_job error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep", "ERROR", None, {"error": str(e), "job": "daily_recon"})


def start_scheduler():
    _log.info("SYSTEM", "service_starting", service="gold-micro")
    _restore_traded_sweeps_on_startup()
    scheduler.add_job(micro_sweep_job, "cron", minute="*/3", id="micro_sweep_poll")
    scheduler.add_job(position_monitor_job, "cron", minute="*", id="micro_position_monitor")
    scheduler.add_job(daily_recon_job, "cron", hour=0, minute=5, id="micro_daily_recon")
    scheduler.start()
    _log.info("SYSTEM", "service_started", service="gold-micro", jobs=["micro_sweep_poll@*/3min","position_monitor@1min","daily_recon@00:05"])
    print("Micro scheduler started: Rolling window sweep poll (3min) + Position monitor + orphan reconciler (1min) + Daily recon (00:05 UTC)")


def stop_scheduler():
    _log.info("SYSTEM", "service_stopping", service="gold-micro")
    scheduler.shutdown(wait=False)
    _log.info("SYSTEM", "service_stopped", service="gold-micro")
