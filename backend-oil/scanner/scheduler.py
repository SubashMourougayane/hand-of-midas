"""Oil trading scheduler — Alpha-Sweep only during London 08:00-10:30 UTC."""
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution.oanda_executor import get_candles, get_current_price, place_market_order, get_account_summary
from backend.execution.oanda_executor import _get_gbp_usd_rate
from backend.db import execute
from config import ALPHA_SWEEP, STRATEGY_RISK, MAX_UNITS, slippage

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


def _run_alpha_sweep():
    """Check for Oil Asia sweep + M3 engulfing."""
    cfg = ALPHA_SWEEP
    today = datetime.now(timezone.utc).date()

    # Already traded today?
    existing = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE strategy='alpha_sweep' AND entry_time::date = %s AND oanda_trade_id LIKE 'BCO%%'",
        (today,), fetch=True
    )
    # Simpler check: look for oil trades today via a comment or separate tracking
    # For now use instrument-aware check once we add instrument column
    # TODO: add instrument column to gd_trades for proper filtering

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
        return
    if sweep_dir == "bearish" and bias != "bearish":
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

        # Engulfing confirmed — place order
        br = (c["ask_high"] + c["bid_high"]) / 2 - (c["ask_low"] + c["bid_low"]) / 2

        if sweep_dir == "bullish":
            entry = c["ask_close"] + slippage(br)
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
            entry = c["bid_close"] - slippage(br)
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

        # Position sizing
        acct = get_account_summary()
        equity_usd = acct.get("nav_usd", acct.get("nav", 5000))
        risk_dollar = equity_usd * (STRATEGY_RISK["alpha_sweep"] / 100)
        units = int(min(risk_dollar / risk, MAX_UNITS))
        if units < 1:
            return

        oanda_units = units if direction == "long" else -units
        print(f"  [OIL] Alpha-Sweep SIGNAL: {direction.upper()} {units} barrels @ {entry:.4f}, SL={sl:.4f}, TP={tp:.4f}")

        result = place_market_order(
            instrument="BCO_USD",
            units=oanda_units,
            sl_price=sl,
            tp_price=tp,
            comment=f"oil_alpha_sweep",
        )

        if result.get("success"):
            import uuid
            trade_ref = f"OIL-AS-{uuid.uuid4().hex[:8]}"
            execute(
                """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
                   VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)""",
                (trade_ref, "alpha_sweep", direction.upper(), result["fill_price"], sl, tp, units / 1000.0, units, result["trade_id"])
            )
            execute(
                "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
                (trade_ref, "alpha_sweep", "ENTRY_FILLED", result["fill_price"],
                 f'{{"instrument":"BCO_USD","units":{units},"sl":{sl},"tp":{tp}}}')
            )
            print(f"  [OIL] FILLED: {direction.upper()} {units} barrels @ {result['fill_price']:.4f}")
        else:
            print(f"  [OIL] Order FAILED: {result.get('error')}")

        return  # One trade per day


def position_monitor_job():
    """Every 1 min — check Oil positions (shared monitor handles max hold)."""
    # The shared Gold position monitor in backend/scanner/live_engine.py
    # already handles ALL open trades including Oil (checks strategy column).
    # This is just a placeholder for Oil-specific monitoring if needed later.
    pass


def start_scheduler():
    scheduler.add_job(london_session_job, "cron", minute="*/3", hour="8-10", id="oil_alpha_sweep_poll")
    scheduler.start()
    print("Oil scheduler started: Alpha-Sweep London poll every 3 min, 08:00-10:30 UTC")


def stop_scheduler():
    scheduler.shutdown(wait=False)
