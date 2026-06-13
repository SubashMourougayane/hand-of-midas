"""Oil trading scheduler — Alpha-Sweep during London 08:00-10:30 UTC + position monitor."""
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

def _parse_ts(ts_str: str) -> datetime:
    """Parse OANDA timestamp (handles nanosecond precision)."""
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)

from config import ALPHA_SWEEP, STRATEGY_RISK, MAX_UNITS, slippage, ENGULFING_TOLERANCE
from scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, check_alpha_sweep_partial_tp, reconcile_orphans, _log_journal, _log_journal_safe
from scanner import _log

scheduler = BackgroundScheduler(timezone="UTC")

# Sweep blacklist — persists across scan cycles, resets daily.
_traded_sweeps_oil = {"date": None, "keys": set()}


def london_session_job():
    """Every 3 min during 08:00-20:00 UTC — Oil Alpha-Sweep (London + NY)."""
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    cfg = ALPHA_SWEEP
    if hour < cfg["scan_start"] or hour > cfg["scan_end"]:
        _log.debug("SCAN", "outside_scan_window", hour=hour, scan_start=cfg["scan_start"], scan_end=cfg["scan_end"])
        return

    _log.info("SCAN", "tick", scan_start=cfg["scan_start"], scan_end=cfg["scan_end"])
    print(f"  [OIL {now.strftime('%H:%M:%S')} UTC] Alpha-Sweep polling...")
    try:
        _run_alpha_sweep()
    except Exception as e:
        _log.exception("SYSTEM", "alpha_sweep_failed", err=str(e))
        print(f"  [OIL] Alpha-Sweep error: {e}")
        _log_journal("SYSTEM", "alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "london_session"})


def position_monitor_job():
    """Every 1 min — Oil positions: SL/TP closures + max hold + break-even +
    reconcile orphan broker positions (production safety net)."""
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
        check_alpha_sweep_partial_tp()  # Filter #7 — bank half at halfway
    except Exception as e:
        _log.exception("SYSTEM", "position_monitor_failed", job="position_monitor", err=str(e))
        print(f"  [OIL] Position monitor error: {e}")
        _log_journal_safe("SYSTEM", "alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "position_monitor"})

    try:
        reconcile_orphans()
    except Exception as e:
        _log.exception("SYSTEM", "orphan_reconciler_failed", job="reconcile_orphans", err=str(e))
        print(f"  [OIL] Orphan reconciler error: {e}")
        _log_journal_safe("SYSTEM", "alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "reconcile_orphans"})


def _run_alpha_sweep():
    """Check for Oil Asia sweep + M3 engulfing. Production entry point.

    Thin wrapper: fetches live data + clock, delegates to _run_alpha_sweep_core.
    The core is testable via tests/harness/parity/ with dry_run=True.
    """
    now = datetime.now(timezone.utc)
    h1_candles = [c for c in get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    if len(h1_candles) < 8:
        _log.warn("BROKER", "h1_too_few", got=len(h1_candles), need=8)
        return
    daily_candles = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
    if len(daily_candles) < 2:
        _log.warn("BROKER", "daily_too_few", got=len(daily_candles), need=2)
        return
    m3_candles = get_candles(instrument="BCO_USD", granularity="M3", count=50, price="BA")
    return _run_alpha_sweep_core(now, h1_candles, daily_candles, m3_candles)


def _run_alpha_sweep_core(now: datetime, h1_candles: list, daily_candles: list,
                          m3_candles: list, dry_run: bool = False):
    """Core Oil Asia-sweep + M3-engulfing logic — testable with injected data.

    Args:
        now: timezone-aware datetime to use as "current time".
        h1_candles: list of H1 candle dicts (bid_*/ask_*) covering today.
        daily_candles: list of daily candle dicts; daily_candles[-2] = yesterday.
        m3_candles: list of M3 candle dicts for engulfing detection.
        dry_run: if True, returns list of signal dicts and SKIPS execute_signal,
                 _log_journal, DB writes. For harness use.

    Returns:
        list of signal dicts when dry_run=True, else None.
    """
    global _traded_sweeps_oil
    cfg = ALPHA_SWEEP
    today = now.date()

    if _traded_sweeps_oil["date"] != today:
        _traded_sweeps_oil = {"date": today, "keys": set()}

    signals_found: list[dict] = []

    if not dry_run:
        # Check how many trades today
        existing = execute(
            "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep_oil' AND entry_time::date = %s",
            (today,), fetch=True
        )
        trades_today = existing[0]["cnt"] if existing else 0
        if trades_today >= cfg["max_trades_per_day"]:
            _log.debug("GATE", "max_trades_reached", trades_today=trades_today, max=cfg["max_trades_per_day"])
            return None

        # 5-min cooldown after last signal attempt (taken OR failed with
        # execution error). Mirrors Gold Macro line 401-412.
        # Without this, a sweep that's still in scan_bars on the next 3-min
        # cron tick can re-fire even after we just tried to trade it.
        recent_signal = execute(
            "SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 1",
            fetch=True
        )
        if recent_signal and recent_signal[0]["timestamp"]:
            last_signal_time = recent_signal[0]["timestamp"]
            if last_signal_time.tzinfo is None:
                last_signal_time = last_signal_time.replace(tzinfo=timezone.utc)
            skip = recent_signal[0].get("skip_reason", "")
            if recent_signal[0]["taken"] or "order_error" in (skip or "") or "sl_too_close" in (skip or ""):
                if now < last_signal_time + timedelta(minutes=5):
                    _log.debug("GATE", "cooldown_active", last_signal=last_signal_time.isoformat(), age_seconds=int((now - last_signal_time).total_seconds()))
                    return None  # Cooldown

        # One position at a time (skip if open Oil Macro trade exists in DB).
        # Mirrors Gold Macro line 415-420. THIS IS THE MISSING GATE that
        # let OIL-AS-f5e9710a fire on 2026-06-11 14:45 UTC while
        # OIL-AS-59a94823 was still stuck in the DB at EXIT_AMBIGUOUS
        # streak 62. The check uses trade_ref prefix (not strategy alone)
        # so it catches orphan rows from the reconciler too.
        open_oil_macro = execute(
            "SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL AND trade_ref LIKE 'OIL-AS-%%'",
            fetch=True
        )
        if open_oil_macro and open_oil_macro[0]["cnt"] > 0:
            _log.debug("GATE", "open_position_db", db_count=open_oil_macro[0]["cnt"])
            return None
    else:
        trades_today = 0

    # Asia bars (00:00-08:00 UTC) with mid prices
    asia_bars = []
    for c in h1_candles:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and 0 <= ts.hour < 8:
            c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
            c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
            c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
            asia_bars.append(c)

    if len(asia_bars) < 3:
        if not dry_run:
            _log.debug("GATE", "asia_too_few_bars", got=len(asia_bars), need=3)
        return signals_found if dry_run else None

    asia_high = max(c["mid_high"] for c in asia_bars)
    asia_low = min(c["mid_low"] for c in asia_bars)
    asia_range = asia_high - asia_low

    if not dry_run:
        _log.debug("SCAN", "asia_range", high=asia_high, low=asia_low, range=asia_range, min_required=cfg["asia_min_range"])

    if asia_range < cfg["asia_min_range"]:
        if not dry_run:
            _log.debug("GATE", "asia_range_too_small", range=asia_range, min=cfg["asia_min_range"])
            _log_journal("SYSTEM", "alpha_sweep_oil", "NO_SIGNAL", None, {
                "reason": "asia_range_too_small", "asia_range": round(asia_range, 4),
                "min_required": cfg["asia_min_range"],
            })
        return signals_found if dry_run else None

    # Scan window bars with mid prices
    scan_bars = []
    for c in h1_candles:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and ts.hour >= cfg["scan_start"]:
            c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
            c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
            c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
            scan_bars.append(c)

    if not scan_bars:
        if not dry_run:
            _log.debug("GATE", "no_scan_bars_yet", scan_start=cfg["scan_start"])
        return signals_found if dry_run else None

    # Daily bias — Combined V1+V2 (matches Gold Macro/Micro and Oil Micro)
    # V1: body% > 40% of range = directional. V2: close in top/bottom 20% = directional.
    # EITHER trigger → directional. Both neutral → neutral.
    if len(daily_candles) < 2:
        return signals_found if dry_run else None
    yesterday = daily_candles[-2]
    mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
    mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
    mid_high = (yesterday["bid_high"] + yesterday["ask_high"]) / 2
    mid_low = (yesterday["bid_low"] + yesterday["ask_low"]) / 2
    prev_range = mid_high - mid_low
    if prev_range <= 0:
        bias = "neutral"
    else:
        # V1: body % of range
        body_pct = abs(mid_close - mid_open) / prev_range
        v1_bias = "neutral"
        if body_pct >= 0.4:
            v1_bias = "bullish" if mid_close > mid_open else "bearish"
        # V2: close position in range
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

    # Detect ALL sweeps in scan window
    sweeps = []
    for bar in scan_bars:
        if bar["mid_high"] > asia_high + cfg["sweep_threshold"] and bar["mid_close"] < asia_high:
            sweeps.append(("bearish", bar["mid_high"], bar["timestamp"]))
        elif bar["mid_low"] < asia_low - cfg["sweep_threshold"] and bar["mid_close"] > asia_low:
            sweeps.append(("bullish", bar["mid_low"], bar["timestamp"]))

    if not sweeps:
        if not dry_run:
            _log.debug("SCAN", "no_sweeps", asia_high=asia_high, asia_low=asia_low, scan_bars_checked=len(scan_bars))
        return signals_found if dry_run else None

    if not dry_run:
        for sd, sw, st in sweeps:
            _log.debug("SCAN", "sweep_detected", dir=sd, wick=sw, time=str(st), asia_high=asia_high, asia_low=asia_low, bias=bias)

    # M3 candles passed in via parameter (live wrapper fetches; harness injects).

    # Process each sweep
    for sweep_dir, sweep_wick, sweep_ts in sweeps:
        if trades_today >= cfg["max_trades_per_day"]:
            break

        sweep_key = f"{sweep_ts}_{sweep_dir}"
        if sweep_key in _traded_sweeps_oil["keys"]:
            if not dry_run:
                _log.debug("GATE", "sweep_already_traded", sweep_key=sweep_key)
            continue

        # Bias filter (Variant C: neutral = allow both directions)
        if bias != "neutral":
            if sweep_dir == "bullish" and bias != "bullish":
                if not dry_run:
                    _log.debug("GATE", "bias_block", bias=bias, side=sweep_dir)
                continue
            if sweep_dir == "bearish" and bias != "bearish":
                if not dry_run:
                    _log.debug("GATE", "bias_block", bias=bias, side=sweep_dir)
                continue

        sweep_time = _parse_ts(sweep_ts) if isinstance(sweep_ts, str) else sweep_ts
        window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])

        relevant_m3 = []
        for c in m3_candles:
            ts = _parse_ts(c["timestamp"])
            if sweep_time < ts <= window_end:
                relevant_m3.append(c)

        if len(relevant_m3) < 3:
            if not dry_run:
                _log.debug("GATE", "engulfing_window_too_few_m3", sweep_key=sweep_key, m3_count=len(relevant_m3), expired=(now >= window_end))
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

            # Engulfing confirmed
            br = (c["ask_high"] + c["bid_high"]) / 2 - (c["ask_low"] + c["bid_low"]) / 2

            if sweep_dir == "bullish":
                entry = c["ask_close"] + slippage(br)
                sl = sweep_wick - cfg["sl_buffer"]
                risk = entry - sl
                if risk < cfg["min_sl"]:
                    sl = entry - cfg["min_sl"]
                    risk = cfg["min_sl"]
                if risk < 0.01 or risk > asia_range * 0.8:
                    if not dry_run:
                        _log.debug("GATE", "risk_out_of_band", side="long", risk=risk, min=0.01, max=asia_range*0.8, asia_range=asia_range)
                    continue
                tp_buf = cfg.get("tp_structure_buffer", asia_range * cfg["tp_multiplier"])
                tp = asia_high - tp_buf
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
                if risk < 0.01 or risk > asia_range * 0.8:
                    if not dry_run:
                        _log.debug("GATE", "risk_out_of_band", side="short", risk=risk, min=0.01, max=asia_range*0.8, asia_range=asia_range)
                    continue
                tp_buf = cfg.get("tp_structure_buffer", asia_range * cfg["tp_multiplier"])
                tp = asia_low + tp_buf
                if entry - tp < risk * 0.8:
                    if not dry_run:
                        _log.debug("GATE", "tp_too_close", side="short", entry=entry, tp=tp, risk=risk, tp_distance=entry-tp, min_required=risk*0.8)
                    continue
                direction = "short"

            if dry_run:
                signals_found.append({
                    "time": c["timestamp"], "direction": direction,
                    "entry": round(entry, 4), "sl": round(sl, 4), "tp": round(tp, 4),
                    "risk": round(risk, 4), "bias": bias,
                    "asia_high": asia_high, "asia_low": asia_low,
                    "sweep_wick": sweep_wick, "sweep_dir": sweep_dir,
                })
                _traded_sweeps_oil["keys"].add(sweep_key)
                trades_today += 1
                break  # dry_run path: parity with live's pre-add behavior
            else:
                # Filter #15: Pre-add sweep to blacklist BEFORE execute_signal.
                # If execute_signal raises (DB INSERT failure, MT5 timeout,
                # JSON serialization error), the next 3-min cron MUST NOT retry
                # the same sweep. Pre-marking here breaks the orphan-trade
                # cascade pattern (mirrors Oil Micro line 422; June 10 fix).
                _log.info("SIGNAL", "fired", direction=direction, entry=entry, sl=sl, tp=tp, risk=risk, sweep_wick=sweep_wick, sweep_dir=sweep_dir, bias=bias, asia_high=asia_high, asia_low=asia_low)
                _traded_sweeps_oil["keys"].add(sweep_key)
                trades_today += 1
                try:
                    trade_ref = execute_signal(
                        direction=direction,
                        entry_price=entry,
                        sl_price=sl,
                        tp_price=tp,
                        context={
                            "asia_high": asia_high, "asia_low": asia_low, "asia_range": asia_range,
                            "sweep_dir": sweep_dir, "sweep_wick": sweep_wick, "bias": bias,
                        },
                    )
                    if trade_ref:
                        _log.info("SIGNAL", "executed", trade_ref=trade_ref, direction=direction)
                    else:
                        _log.warn("SIGNAL", "skipped_by_engine", direction=direction, sweep_key=sweep_key)
                except Exception as e:
                    # Order may have placed even if persistence raised. Sweep stays
                    # blacklisted (above) so we don't re-fire. Conservative: assume
                    # order went through, daily counter stays incremented.
                    _log.exception("SYSTEM", "execute_signal_raised", direction=direction, sweep_key=sweep_key, err=str(e))
                    print(f"  [OIL] execute_signal raised: {e}")
                    _log_journal_safe("SYSTEM", "alpha_sweep_oil", "EXECUTE_SIGNAL_RAISED",
                                      entry, {"error": str(e), "sweep_key": sweep_key, "direction": direction})
                break  # One engulfing per sweep
        else:
            # No engulfing found — consume only if window expired
            if now >= window_end:
                _traded_sweeps_oil["keys"].add(sweep_key)
            if not dry_run:
                _log.debug("GATE", "no_engulfing", direction=sweep_dir, sweep_wick=sweep_wick, m3_bars_checked=len(relevant_m3), expired=(now >= window_end), bias=bias)

    if not dry_run:
        _log.info("SCAN", "complete", trades_today=trades_today)
    return signals_found if dry_run else None


def daily_recon_job():
    """Send daily reconciliation report at 00:05 UTC for yesterday."""
    from backend.db import daily_recon_stats
    from backend import notify
    from datetime import timedelta
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    _log.info("SYSTEM", "daily_recon_start", yesterday=str(yesterday))
    try:
        stats = daily_recon_stats("OIL-AS-%", "alpha_sweep_oil", yesterday)
        _log.info("SYSTEM", "daily_recon_stats", yesterday=str(yesterday), stats=str(stats))
        notify.daily_recon("Oil Macro", str(yesterday), **stats)
    except Exception as e:
        _log.exception("SYSTEM", "daily_recon_job_failed", yesterday=str(yesterday), err=str(e))
        print(f"  [OIL] daily_recon_job error: {e}")
        _log_journal_safe("SYSTEM", "alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "daily_recon"})


def start_scheduler():
    _log.info("SYSTEM", "service_starting", service="oil-macro")
    scheduler.add_job(london_session_job, "cron", minute="*/3", hour="8-19", id="oil_alpha_sweep_poll")
    scheduler.add_job(position_monitor_job, "cron", minute="*", id="oil_position_monitor")
    scheduler.add_job(daily_recon_job, "cron", hour=0, minute=5, id="oil_daily_recon")
    scheduler.start()
    _log.info("SYSTEM", "service_started", service="oil-macro", jobs=["alpha_sweep_poll@*/3min","position_monitor@1min","daily_recon@00:05"])
    print("Oil scheduler started: Alpha-Sweep poll (08-20 UTC) + Position monitor + orphan reconciler (1min) + Daily recon (00:05 UTC)")


def stop_scheduler():
    _log.info("SYSTEM", "service_stopping", service="oil-macro")
    scheduler.shutdown(wait=False)
    _log.info("SYSTEM", "service_stopped", service="oil-macro")
