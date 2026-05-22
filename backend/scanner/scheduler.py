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

from backend.execution.oanda_executor import get_candles, get_current_price
from backend.scanner.live_engine import execute_signal, check_open_positions, check_alpha_sweep_breakeven, _get_dd_state, _log_journal
from backend.db import execute
from backend.config import CROSS_MARKET, MEAN_REV, ALPHA_SWEEP, slippage

scheduler = BackgroundScheduler(timezone="UTC")


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
    from backend.execution.oanda_executor import close_trade, get_candles, _get_gbp_usd_rate

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
    from backend.execution.oanda_executor import close_trade, _get_gbp_usd_rate

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

    # Signal triggered — compute entry, SL, TP
    gold_candles = get_candles(instrument="XAU_USD", granularity="D", count=20, price="BA")
    if len(gold_candles) < 15:
        return

    # ATR(14)
    highs = [c["bid_high"] for c in gold_candles]
    lows = [c["bid_low"] for c in gold_candles]
    closes = [c["bid_close"] for c in gold_candles]
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

    # Fetch 15 daily candles
    candles = get_candles(instrument="XAU_USD", granularity="D", count=15, price="BA")
    if len(candles) < 12:
        return

    closes = [c["bid_close"] for c in candles]
    highs = [c["bid_high"] for c in candles]
    lows = [c["bid_low"] for c in candles]
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
    08:00-10:30 UTC — Poll M3 candles every 3 min for Alpha-Sweep.
    Detects Asia sweep + M3 engulfing during London open.
    """
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0

    # Only active 08:00-10:30 UTC
    if hour < 8.0 or hour > 10.5:
        return

    print(f"  [{now.strftime('%H:%M:%S')} UTC] Alpha-Sweep polling...")

    try:
        _run_alpha_sweep()
    except Exception as e:
        print(f"  Alpha-Sweep error: {e}")
        _log_journal("SYSTEM", "alpha_sweep", "ERROR", context={"error": str(e)})


def _run_alpha_sweep():
    """Check for Asia sweep + M3 engulfing setup."""
    cfg = ALPHA_SWEEP

    # Check if we already traded today
    today = datetime.now(timezone.utc).date()
    existing = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep' AND entry_time::date = %s",
        (today,), fetch=True
    )
    if existing and existing[0]["cnt"] > 0:
        return  # Already traded today

    # Get H1 bars for Asia session (00:00-08:00 UTC today)
    h1_candles = get_candles(instrument="XAU_USD", granularity="H1", count=12, price="BA")
    if len(h1_candles) < 8:
        return

    # Identify Asia bars (00:00-08:00 UTC)
    asia_bars = []
    for c in h1_candles:
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if ts.date() == today and 0 <= ts.hour < 8:
            asia_bars.append(c)

    if len(asia_bars) < 3:
        return

    asia_high = max(c["bid_high"] for c in asia_bars)
    asia_low = min(c["bid_low"] for c in asia_bars)
    asia_range = asia_high - asia_low

    if asia_range < cfg["asia_min_range"]:
        return

    # Check for sweep in London bars (08:00+)
    london_bars = []
    for c in h1_candles:
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if ts.date() == today and ts.hour >= 8:
            london_bars.append(c)

    if not london_bars:
        return

    # Detect sweep
    sweep_dir = None
    sweep_wick = 0.0
    for bar in london_bars:
        bh = bar["bid_high"]
        bl = bar["bid_low"]
        bc = (bar["bid_close"] + bar["ask_close"]) / 2

        if bh > asia_high + cfg["sweep_threshold"] and bc < asia_high:
            sweep_dir = "bearish"
            sweep_wick = bar["ask_high"]
            break
        elif bl < asia_low - cfg["sweep_threshold"] and bc > asia_low:
            sweep_dir = "bullish"
            sweep_wick = bar["bid_low"]
            break

    if sweep_dir is None:
        return

    # Daily bias filter
    yesterday_candles = get_candles(instrument="XAU_USD", granularity="D", count=2, price="M")
    if len(yesterday_candles) < 2:
        return
    yesterday = yesterday_candles[-2]
    bias = "bullish" if yesterday["bid_close"] > yesterday["bid_open"] else "bearish"

    if sweep_dir == "bullish" and bias != "bullish":
        return
    if sweep_dir == "bearish" and bias != "bearish":
        return

    # Now check M3 for engulfing
    m3_candles = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")

    # Persist M3 candles to DB
    _persist_m3_candles(m3_candles)

    # Find engulfing after sweep (skip first bar)
    sweep_time = datetime.fromisoformat(london_bars[0]["timestamp"].replace("Z", "+00:00"))
    window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])

    relevant_m3 = []
    for c in m3_candles:
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if sweep_time < ts <= window_end:
            relevant_m3.append(c)

    if len(relevant_m3) < 3:
        return

    # Skip first bar (spread spike avoidance), start from bar index 2
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

        # Check engulfing
        if sweep_dir == "bullish" and not (cc > co and cb <= pb and ct >= pt):
            continue
        if sweep_dir == "bearish" and not (cc < co and cb <= pb and ct >= pt):
            continue

        # Engulfing confirmed!
        br = c["ask_high"] - c["bid_low"]

        if sweep_dir == "bullish":
            entry = c["ask_close"]
            sl = sweep_wick - cfg["sl_buffer"]
            risk = entry - sl
            if risk < cfg["min_sl"]:
                sl = entry - cfg["min_sl"]
                risk = cfg["min_sl"]
            if risk < 0.3 or risk > asia_range * 0.8:
                continue
            tp = entry + asia_range * cfg["tp_multiplier"]
            if tp - entry < risk * 0.8:
                continue

            print(f"  Alpha-Sweep SIGNAL: LONG @ {entry:.2f}, SL={sl:.2f}, TP={tp:.2f}")
            execute_signal("alpha_sweep", "long", entry, sl, tp, context={
                "asia_high": asia_high, "asia_low": asia_low, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick
            })
        else:
            entry = c["bid_close"]
            sl = sweep_wick + cfg["sl_buffer"]
            risk = sl - entry
            if risk < cfg["min_sl"]:
                sl = entry + cfg["min_sl"]
                risk = cfg["min_sl"]
            if risk < 0.3 or risk > asia_range * 0.8:
                continue
            tp = entry - asia_range * cfg["tp_multiplier"]
            if entry - tp < risk * 0.8:
                continue

            print(f"  Alpha-Sweep SIGNAL: SHORT @ {entry:.2f}, SL={sl:.2f}, TP={tp:.2f}")
            execute_signal("alpha_sweep", "short", entry, sl, tp, context={
                "asia_high": asia_high, "asia_low": asia_low, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick
            })

        return  # Only one trade per day


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
    """Every 1 min — check if OANDA closed any positions (SL/TP hit)."""
    check_open_positions()
    check_alpha_sweep_breakeven()


def start_scheduler():
    """Start all scheduled jobs."""
    # 22:00 UTC daily — Cross-Market + Mean-Rev
    scheduler.add_job(daily_close_job, "cron", hour=22, minute=0, id="daily_close")

    # Every 3 min during 08:00-10:30 UTC — Alpha-Sweep
    scheduler.add_job(london_session_job, "cron", minute="*/3", hour="8-10", id="alpha_sweep_poll")

    # Every 1 min — position monitoring
    scheduler.add_job(position_monitor_job, "interval", minutes=1, id="position_monitor")

    scheduler.start()
    print("Scheduler started:")
    print("  - Daily close (Cross-Market + Mean-Rev): 22:00 UTC")
    print("  - Alpha-Sweep London poll: every 3 min, 08:00-10:30 UTC")
    print("  - Position monitor: every 1 min")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    scheduler.shutdown(wait=False)
