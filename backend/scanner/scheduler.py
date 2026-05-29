"""
Trading scheduler — orchestrates the three strategies on their schedules.

Schedule:
  22:00 UTC daily → Cross-Market + Mean-Rev signal check
  08:00-10:30 UTC → Alpha-Sweep London session monitoring (every 3 min)
  Every 1 min → Position monitoring (SL/TP detection, break-even)
"""
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from backend.execution import get_candles, get_current_price
from backend.scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, _get_dd_state, _log_journal
from backend.db import execute, get_conn
import re

def _parse_ts(ts_str: str) -> datetime:
    """Parse OANDA timestamp (handles nanosecond precision)."""
    # Truncate nanoseconds to microseconds: .000000000 → .000000
    cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
    return datetime.fromisoformat(cleaned)
from backend.config import CROSS_MARKET, MEAN_REV, ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE

scheduler = BackgroundScheduler(timezone="UTC")

# Sweep blacklist — persists across scan cycles, resets daily.
# Once a sweep produces a trade (or SL), it never re-fires that day.
_traded_sweeps_macro = {"date": None, "keys": set()}


def daily_close_job():
    """
    22:00 UTC — Run Cross-Market consensus + Mean-Rev dip check.
    Also: check Mean-Rev condition exits, enforce max hold, manage open trades.
    """
    print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC] Daily close job running...")
    _log_journal("SYSTEM", "system", "DAILY_SCAN_START", context={"time": datetime.now(timezone.utc).isoformat()})

    # First: manage open positions (exits before new entries)
    try:
        _check_mean_rev_exit()
    except Exception as e:
        print(f"  Mean-Rev exit check error: {e}")

    try:
        _check_max_hold_exits()
    except Exception as e:
        print(f"  Max hold check error: {e}")

    # Then: check for new signals
    try:
        _run_cross_market()
    except Exception as e:
        print(f"  Cross-Market error: {e}")
        _log_journal("SYSTEM", "cross_market", "ERROR", context={"error": str(e)})

    try:
        _run_mean_rev()
    except Exception as e:
        print(f"  Mean-Rev error: {e}")
        _log_journal("SYSTEM", "mean_rev", "ERROR", context={"error": str(e)})

    print(f"  Daily close job complete.")


def _check_mean_rev_exit():
    """Check if open Mean-Rev trades should exit (conditions reversed or max 5 days)."""
    from backend.execution import close_trade, get_candles; from backend.scanner.live_engine import _get_gbp_usd_rate

    open_mr = execute(
        "SELECT * FROM gd_trades WHERE strategy='mean_rev' AND exit_time IS NULL AND oanda_trade_id IS NOT NULL",
        fetch=True
    )
    if not open_mr:
        return

    # Fetch daily data for condition check
    candles = get_candles(instrument="XAU_USD", granularity="D", count=15, price="BA")
    if len(candles) < 12:
        return

    closes = [(c["bid_close"] + c["ask_close"]) / 2 for c in candles]
    highs = [(c["bid_high"] + c["ask_high"]) / 2 for c in candles]
    lows = [(c["bid_low"] + c["ask_low"]) / 2 for c in candles]
    ranges = [h - l for h, l in zip(highs, lows)]

    ma10_low = np.mean(lows[-11:-1])
    ma10_high = np.mean(highs[-12:-2])
    close_2d_ago = closes[-3]
    close_yesterday = closes[-2]
    range_yesterday = ranges[-2]

    c1 = (ma10_low - close_2d_ago) / range_yesterday if range_yesterday > 0 else 0
    c2 = (close_yesterday - ma10_high) / range_yesterday if range_yesterday > 0 else 0

    # Conditions reversed if c1 >= -0.4 OR c2 >= -0.8
    conditions_reversed = (c1 >= MEAN_REV["condition1_threshold"] or c2 >= MEAN_REV["condition2_threshold"])

    for trade in open_mr:
        entry_time = trade["entry_time"]
        days_held = (datetime.now(timezone.utc) - entry_time.replace(tzinfo=timezone.utc if entry_time.tzinfo is None else entry_time.tzinfo)).days

        should_exit = conditions_reversed or days_held >= MEAN_REV["max_hold_days"]

        if should_exit:
            reason = "CONDITION_EXIT" if conditions_reversed else "MAX_HOLD"
            print(f"  [mean_rev] Closing trade {trade['trade_ref']}: {reason} (held {days_held}d, c1={c1:.2f}, c2={c2:.2f})")

            result = close_trade(trade["oanda_trade_id"])
            if result.get("success"):
                gbp_usd = _get_gbp_usd_rate()
                realized_pl = result["realized_pl"]
                pnl_usd = realized_pl * gbp_usd

                execute(
                    "UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s WHERE trade_ref=%s",
                    (result["time"], result["close_price"], realized_pl, pnl_usd, reason, trade["trade_ref"])
                )

                # Update DD state
                dd_state = _get_dd_state()
                if realized_pl > 0:
                    new_consec = 0
                else:
                    new_consec = dd_state["consecutive_losses"] + 1
                    if new_consec >= 5:
                        execute("UPDATE gd_dd_state SET pause_counter = 2 WHERE id = 1")
                new_eq = dd_state["equity"] + pnl_usd
                _update_dd_state(new_consec, dd_state["pause_counter"], new_eq, max(dd_state["peak_equity"], new_eq))

                _log_journal(trade["trade_ref"], "mean_rev", "EXIT_FILLED", result["close_price"],
                    {"reason": reason, "pnl_gbp": realized_pl, "pnl_usd": pnl_usd, "days_held": days_held})


def _check_max_hold_exits():
    """Close Cross-Market trades held > 20 days."""
    from backend.execution import close_trade; from backend.scanner.live_engine import _get_gbp_usd_rate

    open_cm = execute(
        "SELECT * FROM gd_trades WHERE strategy='cross_market' AND exit_time IS NULL AND oanda_trade_id IS NOT NULL",
        fetch=True
    )
    if not open_cm:
        return

    for trade in open_cm:
        entry_time = trade["entry_time"]
        days_held = (datetime.now(timezone.utc) - entry_time.replace(tzinfo=timezone.utc if entry_time.tzinfo is None else entry_time.tzinfo)).days

        if days_held >= CROSS_MARKET["max_hold_days"]:
            print(f"  [cross_market] Closing trade {trade['trade_ref']}: MAX_HOLD ({days_held}d)")

            result = close_trade(trade["oanda_trade_id"])
            if result.get("success"):
                gbp_usd = _get_gbp_usd_rate()
                realized_pl = result["realized_pl"]
                pnl_usd = realized_pl * gbp_usd

                execute(
                    "UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s WHERE trade_ref=%s",
                    (result["time"], result["close_price"], realized_pl, pnl_usd, "MAX_HOLD", trade["trade_ref"])
                )

                dd_state = _get_dd_state()
                new_consec = 0 if realized_pl > 0 else dd_state["consecutive_losses"] + 1
                if new_consec >= 5:
                    execute("UPDATE gd_dd_state SET pause_counter = 2 WHERE id = 1")
                new_eq = dd_state["equity"] + pnl_usd
                _update_dd_state(new_consec, dd_state["pause_counter"], new_eq, max(dd_state["peak_equity"], new_eq))

                _log_journal(trade["trade_ref"], "cross_market", "EXIT_FILLED", result["close_price"],
                    {"reason": "MAX_HOLD", "pnl_gbp": realized_pl, "pnl_usd": pnl_usd, "days_held": days_held})


def _run_cross_market():
    """Check Cross-Market consensus signal."""
    cfg = CROSS_MARKET

    # Don't open a new Cross-Market if one is already open
    open_cm = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='cross_market' AND exit_time IS NULL",
        fetch=True
    )
    if open_cm and open_cm[0]["cnt"] > 0:
        print(f"  Cross-Market: skipping — already has open position")
        return

    # Enforce 2-bar (2-day) minimum gap between signals
    last_signal = execute(
        "SELECT timestamp FROM gd_signals WHERE strategy='cross_market' AND taken=TRUE ORDER BY timestamp DESC LIMIT 1",
        fetch=True
    )
    if last_signal:
        last_ts = last_signal[0]["timestamp"]
        days_since = (datetime.now(timezone.utc) - last_ts.replace(tzinfo=timezone.utc if last_ts.tzinfo is None else last_ts.tzinfo)).days
        if days_since < cfg["min_bar_gap"]:
            print(f"  Cross-Market: skipping — last signal {days_since}d ago (min gap: {cfg['min_bar_gap']}d)")
            return
    w = cfg["weights"]
    th = cfg["threshold"]
    max_score = sum(w.values())

    # Fetch 5 days of daily data for each instrument
    instruments = {
        "eur": "EUR_USD", "us10y": "USB10Y_USD", "spx": "SPX500_USD",
        "silver": "XAG_USD", "oil": "BCO_USD", "us2y": "USB02Y_USD",
    }
    returns = {}
    for key, inst in instruments.items():
        candles = get_candles(instrument=inst, granularity="D", count=5, price="M")
        if len(candles) < 4:
            print(f"  Cross-Market: insufficient data for {inst}")
            return
        closes = [c["bid_close"] for c in candles]
        ret_3d = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] > 0 else 0
        returns[key] = ret_3d

    # Compute consensus
    se = 1 if returns["eur"] > th else (-1 if returns["eur"] < -th else 0)
    sy = 1 if returns["us10y"] < -th else (-1 if returns["us10y"] > th else 0)
    ss = 1 if returns["spx"] > th else (1 if returns["spx"] < -th * 2 else (-1 if returns["spx"] < -th else 0))
    ssi = 1 if returns["silver"] > th else (-1 if returns["silver"] < -th else 0)
    so = 1 if returns["oil"] > th else (-1 if returns["oil"] < -th else 0)
    s2 = 1 if returns["us2y"] < -th else (-1 if returns["us2y"] > th else 0)

    consensus = (se * w["eur"] + sy * w["us10y"] + ss * w["spx"] + ssi * w["silver"] + so * w["oil"] + s2 * w["us2y"]) / max_score

    print(f"  Cross-Market consensus: {consensus:.3f} (threshold: {cfg['consensus_min']})")

    if consensus < cfg["consensus_min"]:
        _log_journal("SYSTEM", "cross_market", "NO_SIGNAL", context={"consensus": consensus})
        return

    # Signal triggered — compute entry, SL, TP using mid prices (matches backtest)
    gold_candles = get_candles(instrument="XAU_USD", granularity="D", count=20, price="BA")
    if len(gold_candles) < 15:
        return

    # ATR(14) using mid prices
    highs = [(c["bid_high"] + c["ask_high"]) / 2 for c in gold_candles]
    lows = [(c["bid_low"] + c["ask_low"]) / 2 for c in gold_candles]
    closes = [(c["bid_close"] + c["ask_close"]) / 2 for c in gold_candles]
    tr_vals = []
    for i in range(1, len(gold_candles)):
        tr_vals.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = np.mean(tr_vals[-14:]) if len(tr_vals) >= 14 else np.mean(tr_vals)

    price = get_current_price()
    if not price or not price["tradeable"]:
        return

    br = price["ask"] - price["bid"]
    entry = price["ask"] + slippage(br)  # Match backtest: ask + slippage
    sl = entry - atr * cfg["sl_atr_mult"]
    tp = entry + atr * cfg["tp_atr_mult"]

    if entry - sl < 1.0:
        return

    print(f"  Cross-Market SIGNAL: LONG @ {entry:.2f}, SL={sl:.2f}, TP={tp:.2f}, ATR={atr:.1f}")
    execute_signal("cross_market", "long", entry, sl, tp, context={"consensus": consensus, "atr": atr})


def _run_mean_rev():
    """Check Mean-Rev dip-buy conditions."""
    cfg = MEAN_REV

    # Only 1 Mean-Rev trade at a time (matches backtest in_trade logic)
    open_mr = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='mean_rev' AND exit_time IS NULL",
        fetch=True
    )
    if open_mr and open_mr[0]["cnt"] > 0:
        print(f"  Mean-Rev: skipping — already has open position")
        return

    # Fetch 15 daily candles — use mid prices (matches backtest)
    candles = get_candles(instrument="XAU_USD", granularity="D", count=15, price="BA")
    if len(candles) < 12:
        return

    closes = [(c["bid_close"] + c["ask_close"]) / 2 for c in candles]
    highs = [(c["bid_high"] + c["ask_high"]) / 2 for c in candles]
    lows = [(c["bid_low"] + c["ask_low"]) / 2 for c in candles]
    ranges = [h - l for h, l in zip(highs, lows)]

    # MA10 of lows and highs
    ma10_low = np.mean(lows[-11:-1])  # yesterday's 10-period MA of lows
    ma10_high = np.mean(highs[-12:-2])  # 2-days-ago MA10 of highs
    close_2d_ago = closes[-3]
    close_yesterday = closes[-2]
    range_yesterday = ranges[-2]
    avg_range_10 = np.mean(ranges[-11:-1])

    if range_yesterday < 0.5:
        return

    c1 = (ma10_low - close_2d_ago) / range_yesterday
    c2 = (close_yesterday - ma10_high) / range_yesterday

    print(f"  Mean-Rev conditions: c1={c1:.3f} (<{cfg['condition1_threshold']}?), c2={c2:.3f} (<{cfg['condition2_threshold']}?)")

    if c1 >= cfg["condition1_threshold"] or c2 >= cfg["condition2_threshold"]:
        _log_journal("SYSTEM", "mean_rev", "NO_SIGNAL", context={"c1": c1, "c2": c2})
        return

    # Signal! Entry at next open (which is NOW since we run at 22:00 UTC = daily close)
    price = get_current_price()
    if not price or not price["tradeable"]:
        return

    br = price["ask"] - price["bid"]
    entry = price["ask"] + slippage(br)  # Match backtest: ask + slippage
    sl = entry - avg_range_10 * cfg["sl_range_multiplier"]

    if entry - sl < 1.0:
        return

    print(f"  Mean-Rev SIGNAL: LONG @ {entry:.2f}, SL={sl:.2f}, avg_range={avg_range_10:.1f}")
    execute_signal("mean_rev", "long", entry, sl, 0, context={"c1": c1, "c2": c2, "avg_range": avg_range_10})


# Alpha-Sweep state (persisted in DB between polls)
def london_session_job():
    """
    08:00-20:00 UTC — Poll every 3 min for Alpha-Sweep.
    Detects Asia sweep + M3 engulfing across London + NY sessions.
    """
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    cfg = ALPHA_SWEEP

    if hour < cfg["scan_start"] or hour > cfg["scan_end"]:
        return

    print(f"  [{now.strftime('%H:%M:%S')} UTC] Alpha-Sweep polling...")

    try:
        _run_alpha_sweep()
    except Exception as e:
        print(f"  Alpha-Sweep error: {e}")
        _log_journal("SYSTEM", "alpha_sweep", "ERROR", context={"error": str(e)})


def _run_alpha_sweep():
    """Check for Asia sweep + M3 engulfing setup. Allows up to max_trades_per_day."""
    global _traded_sweeps_macro
    cfg = ALPHA_SWEEP

    # Check how many trades today
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    # Reset sweep blacklist at midnight
    if _traded_sweeps_macro["date"] != today:
        _traded_sweeps_macro = {"date": today, "keys": set()}

    existing = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep' AND entry_time::date = %s",
        (today,), fetch=True
    )
    trades_today = existing[0]["cnt"] if existing else 0
    if trades_today >= cfg["max_trades_per_day"]:
        return

    # 5-min cooldown after last signal attempt (taken OR failed with execution error)
    recent_signal = execute(
        "SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='alpha_sweep' ORDER BY timestamp DESC LIMIT 1",
        fetch=True
    )
    if recent_signal and recent_signal[0]["timestamp"]:
        last_signal_time = recent_signal[0]["timestamp"]
        if last_signal_time.tzinfo is None:
            last_signal_time = last_signal_time.replace(tzinfo=timezone.utc)
        skip = recent_signal[0].get("skip_reason", "")
        if recent_signal[0]["taken"] or "order_error" in (skip or "") or "sl_too_close" in (skip or ""):
            if now < last_signal_time + timedelta(minutes=5):
                return  # Cooldown: same signal can't re-fire within 5 min

    # One position at a time (skip if open Macro trade exists)
    open_macro = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL AND trade_ref LIKE 'GD-AS-%%'",
        fetch=True
    )
    if open_macro and open_macro[0]["cnt"] > 0:
        return  # Already have an open position

    # Get H1 bars (need up to 20 hours of today's data) — only use complete bars
    h1_candles = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    if len(h1_candles) < 8:
        return

    # Identify Asia bars (00:00-08:00 UTC) — use MID prices for parity with backtest
    asia_bars = []
    for c in h1_candles:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and 0 <= ts.hour < 8:
            c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
            c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
            c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
            c["mid_open"] = (c["bid_open"] + c["ask_open"]) / 2
            asia_bars.append(c)

    if len(asia_bars) < 3:
        return

    asia_high = max(c["mid_high"] for c in asia_bars)
    asia_low = min(c["mid_low"] for c in asia_bars)
    asia_range = asia_high - asia_low

    if asia_range < cfg["asia_min_range"]:
        return

    # Check for sweep in scan window bars — use MID prices for parity
    scan_bars = []
    for c in h1_candles:
        ts = _parse_ts(c["timestamp"])
        if ts.date() == today and ts.hour >= cfg["scan_start"]:
            c["mid_high"] = (c["bid_high"] + c["ask_high"]) / 2
            c["mid_low"] = (c["bid_low"] + c["ask_low"]) / 2
            c["mid_close"] = (c["bid_close"] + c["ask_close"]) / 2
            scan_bars.append(c)

    if not scan_bars:
        return

    # Daily bias filter — Variant C: strong body = directional, weak body = neutral (allow both)
    yesterday_candles = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
    if len(yesterday_candles) < 2:
        return
    yesterday = yesterday_candles[-2]
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

    # Detect ALL sweeps in scan window (not just first)
    sweeps = []
    for bar in scan_bars:
        mh = bar["mid_high"]
        ml = bar["mid_low"]
        mc = bar["mid_close"]

        if mh > asia_high + cfg["sweep_threshold"] and mc < asia_high:
            sweeps.append(("bearish", mh, bar["timestamp"]))
        elif ml < asia_low - cfg["sweep_threshold"] and mc > asia_low:
            sweeps.append(("bullish", ml, bar["timestamp"]))

    if not sweeps:
        return

    # Log sweep detection
    for sd, sw, st in sweeps:
        _log_journal("SYSTEM", "alpha_sweep", "SWEEP_DETECTED",
            price=sw, context={"direction": sd, "sweep_wick": sw, "sweep_time": str(st),
                               "asia_high": asia_high, "asia_low": asia_low, "bias": bias})
        print(f"  [SWEEP] {sd.upper()} sweep detected @ {sw:.2f} (wick)")

    # Get M3 candles for engulfing detection
    m3_candles = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")
    _persist_m3_candles(m3_candles)

    # Process each sweep until max_trades_per_day reached
    for sweep_dir, sweep_wick, sweep_ts in sweeps:
        if trades_today >= cfg["max_trades_per_day"]:
            break

        # Sweep blacklist: once consumed (traded or SL'd), never re-fires that day
        sweep_key = f"{sweep_ts}_{sweep_dir}"
        if sweep_key in _traded_sweeps_macro["keys"]:
            continue

        # Bias filter (Variant C: neutral = allow both directions)
        if bias != "neutral":
            if sweep_dir == "bullish" and bias != "bullish":
                continue
            if sweep_dir == "bearish" and bias != "bearish":
                continue

        # Find engulfing after this sweep
        sweep_time = _parse_ts(sweep_ts) if isinstance(sweep_ts, str) else sweep_ts
        window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])

        relevant_m3 = []
        for c in m3_candles:
            ts = _parse_ts(c["timestamp"])
            if sweep_time < ts <= window_end:
                relevant_m3.append(c)

        if len(relevant_m3) < 3:
            continue

        for j in range(2, len(relevant_m3)):
            c = relevant_m3[j]
            prev = relevant_m3[j - 1]

            co = (c["bid_open"] + c["ask_open"]) / 2
            cc = (c["bid_close"] + c["ask_close"]) / 2
            po = (prev["bid_open"] + prev["ask_open"]) / 2
            pc = (prev["bid_close"] + prev["ask_close"]) / 2

            ct = max(co, cc)
            cb = min(co, cc)
            pt = max(po, pc)
            pb = min(po, pc)

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
                if risk < 0.3 or risk > asia_range * 0.8:
                    continue
                tp_buf = cfg.get("tp_structure_buffer", asia_range * cfg["tp_multiplier"])
                tp = asia_high - tp_buf
                if tp - entry < risk * 0.8:
                    continue

                print(f"  Alpha-Sweep SIGNAL: LONG @ {entry:.2f}, SL={sl:.2f}, TP={tp:.2f}")
                execute_signal("alpha_sweep", "long", entry, sl, tp, context={
                    "asia_high": asia_high, "asia_low": asia_low, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick
                })
            else:
                entry = c["bid_close"] - slippage(br)
                sl = sweep_wick + cfg["sl_buffer"]
                risk = sl - entry
                if risk < cfg["min_sl"]:
                    sl = entry + cfg["min_sl"]
                    risk = cfg["min_sl"]
                if risk < 0.3 or risk > asia_range * 0.8:
                    continue
                tp_buf = cfg.get("tp_structure_buffer", asia_range * cfg["tp_multiplier"])
                tp = asia_low + tp_buf
                if entry - tp < risk * 0.8:
                    continue

                print(f"  Alpha-Sweep SIGNAL: SHORT @ {entry:.2f}, SL={sl:.2f}, TP={tp:.2f}")
                execute_signal("alpha_sweep", "short", entry, sl, tp, context={
                    "asia_high": asia_high, "asia_low": asia_low, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick
                })

            _traded_sweeps_macro["keys"].add(sweep_key)
            trades_today += 1
            break  # One engulfing per sweep
        else:
            # No engulfing found — consume only if window expired
            if now >= window_end:
                _traded_sweeps_macro["keys"].add(sweep_key)
            _log_journal("SYSTEM", "alpha_sweep", "NO_ENGULFING",
                price=sweep_wick, context={"direction": sweep_dir, "sweep_wick": sweep_wick,
                                           "m3_bars_checked": len(relevant_m3), "bias": bias})
            print(f"  [SWEEP] {sweep_dir} sweep — no engulfing found ({len(relevant_m3)} M3 bars checked)")


def _persist_m3_candles(candles: list[dict]):
    """Save M3 candles to DB for audit trail."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for c in candles:
                cur.execute(
                    """INSERT INTO gd_journal (strategy, event_type, price, context)
                       VALUES ('alpha_sweep', 'M3_CANDLE', %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (c["bid_close"], str(c))
                )
        conn.commit()
    except:
        conn.rollback()
    finally:
        conn.close()


def position_monitor_job():
    """Every 1 min — check if OANDA closed any positions (SL/TP hit).
    Break-even is handled by the real-time price stream (tick-by-tick), not here."""
    check_open_positions()


def heartbeat_job():
    """Hourly heartbeat during scan window — sends Telegram status."""
    try:
        from backend.execution import get_current_price, get_candles
        from backend import notify

        now = datetime.now(timezone.utc)
        today = now.date()

        # Current price
        price = get_current_price(instrument="XAU_USD")
        gold_price = f"${price['mid']:.2f}" if price else "N/A"

        # Asia range
        h1 = get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA")
        asia_high, asia_low = 0, 999999
        for c in h1:
            ts = _parse_ts(c["timestamp"])
            if ts.date() == today and 0 <= ts.hour < 8:
                asia_high = max(asia_high, (c["bid_high"] + c["ask_high"]) / 2)
                asia_low = min(asia_low, (c["bid_low"] + c["ask_low"]) / 2)

        asia_range = asia_high - asia_low if asia_high > 0 and asia_low < 999999 else 0

        # Today's trades
        trades_today = execute(
            "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep' AND entry_time::date = %s",
            (today,), fetch=True
        )
        trade_count = trades_today[0]["cnt"] if trades_today else 0

        # Open positions
        open_pos = execute("SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL", fetch=True)
        open_count = open_pos[0]["cnt"] if open_pos else 0

        # Convert to IST
        ist_hour = (now.hour + 5) % 24 + (1 if now.minute >= 30 else 0)
        ist_min = (now.minute + 30) % 60
        ist_ampm = "AM" if ist_hour < 12 else "PM"
        ist_display = f"{ist_hour if ist_hour <= 12 else ist_hour - 12}:{ist_min:02d} {ist_ampm} IST"

        # Distance from sweep levels
        dist_high = f"+${price['mid'] - asia_high:.1f}" if price and asia_high > 0 else "?"
        dist_low = f"+${asia_low - price['mid']:.1f}" if price and asia_low < 999999 else "?"
        sweep_needed_high = f"${asia_high + 2:.0f}" if asia_high > 0 else "?"
        sweep_needed_low = f"${asia_low - 2:.0f}" if asia_low < 999999 else "?"

        # Oil price
        oil_price_data = get_current_price(instrument="BCO_USD")
        oil_str = f"${oil_price_data['mid']:.2f}" if oil_price_data else "N/A"

        notify._send(
            f"🫀 Heartbeat — {ist_display}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Gold: {gold_price} | Oil: {oil_str}\n"
            f"Asia: ${asia_low:.0f} – ${asia_high:.0f} (${asia_range:.0f} range)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Bearish sweep: need >{sweep_needed_high} ({dist_high} away)\n"
            f"Bullish sweep: need <{sweep_needed_low} ({dist_low} away)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Trades: {trade_count}/3 | Open: {open_count}\n"
            f"Status: {'🟢 Scanning' if price and price.get('tradeable') else '🔴 Closed'}"
        )
    except Exception as e:
        print(f"  Heartbeat error: {e}")


def start_scheduler():
    """Start all scheduled jobs."""
    # 22:00 UTC daily — Cross-Market + Mean-Rev
    scheduler.add_job(daily_close_job, "cron", hour=22, minute=0, id="daily_close")

    # Every 3 min during 08:00-20:00 UTC — Alpha-Sweep (London + NY)
    scheduler.add_job(london_session_job, "cron", minute="*/3", hour="8-19", id="alpha_sweep_poll")

    # Every 1 min — position monitoring
    scheduler.add_job(position_monitor_job, "interval", minutes=1, id="position_monitor")

    # Hourly heartbeat during scan window
    scheduler.add_job(heartbeat_job, "cron", minute=0, hour="8-19", id="heartbeat")

    scheduler.start()
    print("Scheduler started:")
    print("  - Daily close (Cross-Market + Mean-Rev): 22:00 UTC")
    print("  - Alpha-Sweep poll: every 3 min, 08:00-20:00 UTC (London + NY)")
    print("  - Position monitor: every 1 min")
    print("  - Heartbeat: hourly during scan window")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    scheduler.shutdown(wait=False)
