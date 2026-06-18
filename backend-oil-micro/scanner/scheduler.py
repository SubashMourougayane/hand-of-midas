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
from scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, check_alpha_sweep_partial_tp, reconcile_orphans, pending_order_monitor, _log_journal, _log_journal_safe
from scanner import _log

# Phase 5.5 (REFACTOR_PLAN_LIVE_BT_UNIFY): unified signal-gen + adapter.
# Live now imports the SAME generate_signals BT uses. Production gates
# (cooldown, open-pos, daily cap, blacklist, F28 override) wrap the call.
from strategies.micro_alpha_sweep_oil import generate_signals as _generate_signals
from backend.scanner.broker_to_dataframe import broker_bars_to_dataframe

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
        _log.warn("GATE", "daily_max_loss_hit", daily_pnl=actual_daily_pnl, max=-DD_PROTECTION["daily_max_loss"])
        return

    active_windows = _get_active_windows(now)
    if not active_windows:
        _log.debug("SCAN", "no_active_windows", hour=now.hour)
        return

    _log.info("SCAN", "tick", windows=len(active_windows), trades_today=_daily_state["trades"], daily_pnl=actual_daily_pnl)
    print(f"  [OIL-MICRO {now.strftime('%H:%M:%S')} UTC] Scanning {len(active_windows)} active windows...")

    try:
        _run_micro_sweep(now, active_windows)
    except Exception as e:
        _log.exception("SYSTEM", "scan_failed", job="micro_sweep_job", err=str(e))
        print(f"  [OIL-MICRO] Error: {e}")
        _log_journal("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "micro_sweep"})


def position_monitor_job():
    """Every 1 min — check positions for SL/TP closures + max hold + break-even +
    reconcile any orphan broker positions not in DB (production safety net for
    the orphan-trade cascade pattern)."""
    try:
        check_open_positions()
        check_alpha_sweep_breakeven()
        check_alpha_sweep_partial_tp()  # Filter #7 — bank half at halfway
    except Exception as e:
        _log.exception("SYSTEM", "position_monitor_failed", job="position_monitor", err=str(e))
        print(f"  [OIL-MICRO] Position monitor error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "position_monitor"})

    # Orphan reconciliation runs in its own try/except so a check_open_positions
    # failure doesn't skip the safety net, and vice versa.
    try:
        reconcile_orphans()
    except Exception as e:
        _log.exception("SYSTEM", "orphan_reconciler_failed", job="reconcile_orphans", err=str(e))
        print(f"  [OIL-MICRO] Orphan reconciler error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "reconcile_orphans"})


def _run_micro_sweep(now: datetime, active_windows: list):
    """Process all active windows for sweep detection."""
    h1_candles = [c for c in get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    if len(h1_candles) < 6:
        _log.warn("BROKER", "h1_too_few", got=len(h1_candles), need=6)
        return
    daily_candles = get_candles(instrument="BCO_USD", granularity="D", count=2, price="BA")
    if len(daily_candles) < 2:
        _log.warn("BROKER", "daily_too_few", got=len(daily_candles), need=2)
        return
    m3_candles = get_candles(instrument="BCO_USD", granularity="M3", count=50, price="BA")
    if not m3_candles:
        _log.warn("BROKER", "m3_empty")
        return

    return _run_micro_sweep_core(now, active_windows, h1_candles, daily_candles, m3_candles)


def _run_micro_sweep_core(now: datetime, active_windows: list,
                          h1_candles: list, daily_candles: list, m3_candles: list,
                          dry_run: bool = False):
    """Core sweep logic — testable with injected data."""
    cfg = MICRO_ALPHA_SWEEP
    today = now.date()

    # Check trades today.
    # Day 1 override fix: LIMIT_TTL_EXPIRED entries don't count toward daily
    # cap. No risk was taken, so they shouldn't lock out the day.
    existing = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades "
        f"WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND entry_time::date = %s "
        f"AND (exit_reason IS NULL OR exit_reason NOT IN ('LIMIT_TTL_EXPIRED', 'LIMIT_TTL_EXPIRED_GRACE'))",
        (today,), fetch=True
    )
    db_trades_today = existing[0]["cnt"] if existing else 0
    # Self-heal in-memory counter from filtered DB so a TTL_EXPIRED that
    # was already counted optimistically gets uncounted on the next tick.
    if db_trades_today < _daily_state["trades"]:
        _daily_state["trades"] = db_trades_today
    trades_today = max(db_trades_today, _daily_state["trades"])
    if trades_today >= cfg["max_trades_per_day"]:
        if not dry_run:
            _log.debug("GATE", "max_trades_reached", trades_today=trades_today, max=cfg["max_trades_per_day"])
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

    # Filter #28 — bias-mode override.
    from config import BIAS_MODE as _bias_mode_cfg
    _computed_bias = bias
    _bias_mode_used = "production"
    if _bias_mode_cfg == "neutral":
        bias = "neutral"
        _bias_mode_used = "neutral"
    if not dry_run:
        _log.info(
            "F28-BIAS", "bias_resolved",
            system="oil-micro",
            day=today.isoformat(),
            mode=_bias_mode_used,
            computed=_computed_bias,
            effective=bias,
            filter_active=(bias != "neutral"),
        )
        print(
            f"  [F28-BIAS] oil-micro day={today.isoformat()} "
            f"mode={_bias_mode_used} computed={_computed_bias} "
            f"effective={bias} filter_active={bias != 'neutral'}"
        )
        # F28-H2: use _log_journal_safe (swallows DB blips) — F28 must NOT
        # introduce a new failure mode. Observability-only event.
        _log_journal_safe(
            "SYSTEM", "micro_alpha_sweep_oil", "F28_BIAS_RESOLVED", None,
            {"system": "oil-micro", "day": today.isoformat(),
             "mode": _bias_mode_used, "computed_bias": _computed_bias,
             "effective_bias": bias, "filter_active": bias != "neutral"},
        )

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
        # Issue #19 fix 2026-06-15
        _skip = (skip or "")
        if recent_signal[0]["taken"] or _skip.startswith("order_error") or _skip.startswith("oanda_error") or _skip == "sl_too_close_to_price":
            if now < last_signal_time + timedelta(minutes=5):
                if not dry_run:
                    _log.debug("GATE", "cooldown_active", last_signal=last_signal_time.isoformat(), age_seconds=int((now - last_signal_time).total_seconds()), reason="recent_signal")
                return [] if dry_run else None

    # Startup cooldown (C8 fix)
    if _startup_cooldown_until and now < _startup_cooldown_until:
        if not dry_run:
            _log.debug("GATE", "startup_cooldown", until=_startup_cooldown_until.isoformat() if _startup_cooldown_until else None)
        return [] if dry_run else None

    # ───────────────────────────────────────────────────────────────────
    # Phase 5.5 refactor: call BT's `generate_signals` directly.
    #
    # Before refactor: 250+ lines of inline strategy logic (range detection,
    # sweep, dedup keying, engulfing, entry math, sl/tp/risk gates) lived
    # right here, separately from BT's identical-but-drifted reimplementation.
    # That drift was Master RCA D2/D5/D9 + drift-bug #7 (Day 1 disaster).
    #
    # After refactor: live calls the SAME `generate_signals(h1_df, m3_df,
    # daily_bias)` BT calls. Production-only gates (sweep blacklist,
    # open-position DB+MT5, daily cap) wrap that call. Strategy logic
    # changes auto-apply to both BT and live.
    #
    # active_windows is now informational only — generate_signals walks
    # all windows internally per the strategy spec. Live still gates on
    # `len(active_windows) == 0` upstream (in micro_sweep_job) so we don't
    # invoke signal-gen during market-close hours.
    # ───────────────────────────────────────────────────────────────────

    # Build BT-format DataFrames using Phase 1 adapter.
    h1_df = broker_bars_to_dataframe(h1_candles)
    m3_df = broker_bars_to_dataframe(m3_candles)
    if h1_df.empty or m3_df.empty:
        if not dry_run:
            _log.warn("BROKER", "empty_dataframe_after_adapter",
                      h1_rows=len(h1_df), m3_rows=len(m3_df))
        return [] if dry_run else None

    # `generate_signals` expects daily_bias as a {date: str} dict. Live
    # operates on a single trading day; BT does multi-day. Build a tiny
    # dict keyed by today + yesterday with the resolved bias.
    daily_bias_dict = {}
    for d in set(h1_df.index.date):
        daily_bias_dict[d] = bias

    # Generate the signal universe for the data we have. Returns
    # list[Signal] (date, entry, sl, tp, direction, risk, strategy,
    # max_bars, timeframe, metadata).
    signals = _generate_signals(h1_df, m3_df, daily_bias_dict)

    if not dry_run:
        _log.debug("SCAN", "signals_from_strategy", count=len(signals), bias=bias)

    # Iterate signals, applying production-only gates.
    # Signals are sorted by date (M3 engulfing time). We stop at first
    # successful execution this cycle (one-at-a-time semantics) so a
    # cluster of signals from a single sweep doesn't fire multiple orders.
    for signal in signals:
        if trades_today >= cfg["max_trades_per_day"] or trade_placed_this_cycle:
            break

        # Drop signals whose engulfing time is in the future relative to
        # `now`. Defensive — shouldn't happen with broker data but the BT
        # signal-gen will return any signal in its data window.
        if signal.date.to_pydatetime() > now:
            continue

        # NOTE: no time-based staleness gate. Persistent sweep blacklist
        # (_traded_sweeps + DB-backed is_sweep_consumed) is the single
        # dedup source of truth. BT-style signal-gen may emit signals
        # whose engulfing time was minutes ago; the blacklist handles
        # repeats across cron ticks.

        # Reconstruct sweep_key for the persistent blacklist.
        # Master RCA D5: BT keys by `(sbar_ts, start_hour)` per-window
        # tuple. Live now does the same — sweep_time is the SWEEP H1 bar
        # timestamp (NOT the engulfing M3 timestamp). Without this, a
        # cluster of signals from the same sweep but different engulfing
        # M3 bars (e.g. 13:27, 13:36 within same window) would each pass
        # dedup and fire as separate orders.
        sweep_dir = signal.metadata.get("sweep_dir") if signal.metadata else None
        sweep_wick = signal.metadata.get("sweep_wick") if signal.metadata else None
        consol_range = signal.metadata.get("consol_range") if signal.metadata else None
        sweep_time = signal.metadata.get("sweep_time") if signal.metadata else None
        start_hour = signal.metadata.get("start_hour") if signal.metadata else None
        if sweep_time is None or start_hour is None:
            if not dry_run:
                _log.warn("SCAN", "signal_missing_sweep_metadata", date=str(signal.date))
            continue
        sweep_key = f"{sweep_time}_{start_hour}_{sweep_dir}"

        # Persistent sweep blacklist (DB-backed since Issue #9, 2026-06-15).
        if sweep_key not in _traded_sweeps["keys"] and not dry_run:
            from backend.db import is_sweep_consumed
            if is_sweep_consumed("oil-micro", today, sweep_key):
                _traded_sweeps["keys"].add(sweep_key)
        if sweep_key in _traded_sweeps["keys"]:
            if not dry_run:
                _log.debug("GATE", "sweep_already_traded", sweep_key=sweep_key)
            continue

        # One-at-a-time: DB check.
        open_micro = execute(
            f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time IS NULL",
            fetch=True,
        )
        if open_micro and open_micro[0]["cnt"] > 0:
            if not dry_run:
                _log.debug("GATE", "open_position_db", db_count=open_micro[0]["cnt"])
            continue

        # Account-wide MT5/OANDA check (Master RCA D4 — kept by user
        # decision 2026-06-19 as deliberate cross-system safety).
        mt5_open = get_open_trades()
        if mt5_open and len(mt5_open) > 0:
            if not dry_run:
                _log.debug("GATE", "open_position_mt5", mt5_count=len(mt5_open))
            continue

        direction = signal.direction
        entry = signal.entry
        sl = signal.sl
        tp = signal.tp
        risk = signal.risk
        # window string used in journal context — derived from signal
        # metadata so we don't need active_windows here.
        window_str = signal.metadata.get("window", "?-?") if signal.metadata else "?-?"

        if dry_run:
            signals_found.append({
                "time": signal.date.isoformat(), "direction": direction,
                "entry": round(entry, 4), "sl": round(sl, 4), "tp": round(tp, 4),
                "risk": round(risk, 4), "bias": bias,
                "range_high": None, "range_low": None,
                "consol_range": consol_range, "sweep_wick": sweep_wick,
            })
            _traded_sweeps["keys"].add(sweep_key)
            trades_today += 1
            trade_placed_this_cycle = True
            continue

        # Live path.
        # CRITICAL: Add sweep to blacklist BEFORE placing the order.
        # If execute_signal raises mid-flight (e.g. JSON serialization error
        # in journal write), the next 3-min cron must NOT retry the same
        # sweep. Pre-marking it here breaks the orphan-trade cascade
        # observed on June 10 (see docs/JUNE10_OIL_4ORPHANS_INVESTIGATION.md).
        _traded_sweeps["keys"].add(sweep_key)
        from backend.db import mark_sweep_consumed
        try:
            mark_sweep_consumed("oil-micro", today, sweep_key)
        except Exception as e:
            _log.exception("SYSTEM", "mark_sweep_consumed_failed", err=str(e))
        _daily_state["trades"] += 1  # Optimistic — decremented if signal fails
        _log.info(
            "SIGNAL", "fired",
            direction=direction, entry=entry, sl=sl, tp=tp, risk=risk,
            sweep_wick=sweep_wick, sweep_dir=sweep_dir, bias=bias,
            consol_range=consol_range,
        )

        try:
            trade_ref = execute_signal(
                strategy="micro_alpha_sweep_oil",
                direction=direction,
                entry_price=entry,
                sl_price=sl,
                tp_price=tp,
                context={
                    "consol_range": consol_range,
                    "consol_window": window_str,
                    "sweep_dir": sweep_dir, "sweep_wick": sweep_wick, "bias": bias,
                },
                daily_pnl=_daily_state["pnl"],
            )
            if trade_ref:
                trades_today += 1
                trade_placed_this_cycle = True
                _log.info("SIGNAL", "executed", trade_ref=trade_ref, direction=direction)
            else:
                # Signal was skipped (DD, sl_too_close, etc.) — roll back optimistic counter
                _daily_state["trades"] = max(0, _daily_state["trades"] - 1)
                _log.warn("SIGNAL", "skipped_by_engine", direction=direction, sweep_key=sweep_key)
        except Exception as e:
            # Order may have been placed even if persistence raised.
            # Sweep stays blacklisted (above) so we don't re-fire.
            # Daily counter stays incremented (conservative — assume order went through).
            _log.exception("SYSTEM", "execute_signal_raised", direction=direction, sweep_key=sweep_key, err=str(e))
            print(f"  [OIL-MICRO] execute_signal raised: {e}")
            _log_journal_safe(
                "SYSTEM", "micro_alpha_sweep_oil", "EXECUTE_SIGNAL_RAISED",
                entry, {"error": str(e), "sweep_key": sweep_key, "direction": direction},
            )

    if not dry_run:
        _log.info("SCAN", "complete", trades_today=trades_today, fired_this_cycle=trade_placed_this_cycle)
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
    _log.info("SYSTEM", "daily_recon_start", yesterday=str(yesterday))
    try:
        stats = daily_recon_stats("OIL-MI-%", "micro_alpha_sweep_oil", yesterday)
        _log.info("SYSTEM", "daily_recon_stats", yesterday=str(yesterday), stats=str(stats))
        notify.daily_recon("Oil Micro", str(yesterday), **stats)
    except Exception as e:
        _log.exception("SYSTEM", "daily_recon_job_failed", yesterday=str(yesterday), err=str(e))
        print(f"  [OIL-MICRO] daily_recon_job error: {e}")
        _log_journal_safe("SYSTEM", "micro_alpha_sweep_oil", "ERROR", None, {"error": str(e), "job": "daily_recon"})


def pending_order_monitor_job():
    """Filter #27: every 30s, reconcile mode='pending' rows. Wrapped so a
    transient error never crashes the scheduler."""
    try:
        pending_order_monitor()
    except Exception as e:
        _log.exception("SYSTEM", "pending_order_monitor_crashed", err=str(e))


def start_scheduler():
    _log.info("SYSTEM", "service_starting", service="oil-micro")
    _restore_traded_sweeps_on_startup()
    scheduler.add_job(micro_sweep_job, "cron", minute="*/3", id="oil_micro_sweep_poll")
    scheduler.add_job(position_monitor_job, "cron", minute="*", id="oil_micro_position_monitor")
    # Filter #27 pending-limit reconciler. No-op when no mode='pending' rows exist.
    scheduler.add_job(pending_order_monitor_job, "interval", seconds=30, id="oil_micro_pending_order_monitor")
    scheduler.add_job(daily_recon_job, "cron", hour=0, minute=5, id="oil_micro_daily_recon")
    scheduler.start()
    _log.info("SYSTEM", "service_started", service="oil-micro",
              jobs=["micro_sweep_poll@*/3min", "position_monitor@1min",
                    "pending_order_monitor@30s", "daily_recon@00:05"])
    print("Oil Micro scheduler started: Rolling window sweep poll (3min) + Position monitor + orphan reconciler (1min) + Pending-order monitor (30s, Filter #27) + Daily recon (00:05 UTC)")


def stop_scheduler():
    _log.info("SYSTEM", "service_stopping", service="oil-micro")
    scheduler.shutdown(wait=False)
    _log.info("SYSTEM", "service_stopped", service="oil-micro")
