"""
Micro Alpha-Sweep: Rolling 4-hour consolidation windows every 2 hours.

Signal generation matches live scheduler exactly:
- Walks each H1 bar chronologically (simulates scheduler poll)
- For each bar, checks ALL active windows
- For each window, checks ALL completed scan bars (not just current)
- Deduplicates by (sweep_bar_ts, window_start) — same as live's DB check
"""
import numpy as np
import pandas as pd
from datetime import timedelta
from backend.strategies.base import Signal
from backend.config import ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE


MICRO_CONFIG = {
    "consol_hours": 4,
    "scan_gap_hours": 2,
    "scan_after_hours": 6,
    "scan_start_hour": 0,
    "scan_end_hour": 20,
}


def generate_signals(
    gold_h1: pd.DataFrame,
    gold_m3: pd.DataFrame,
    daily_bias: dict,
) -> list[Signal]:
    cfg = ALPHA_SWEEP
    mcfg = MICRO_CONFIG
    signals = []

    dates = sorted(set(gold_h1.index.date))

    for date in dates:
        day_h1 = gold_h1[gold_h1.index.date == date]
        if len(day_h1) < 6:
            continue

        bias = daily_bias.get(date, "none")
        day_trades = 0
        max_per_day = cfg.get("max_trades_per_day", 3)
        traded_sweeps = set()

        for bar_ts, bar in day_h1.iterrows():
            if day_trades >= max_per_day:
                break

            now_hour = bar_ts.hour

            for start_hour in range(mcfg["scan_start_hour"], mcfg["scan_end_hour"] - mcfg["consol_hours"] + 1, mcfg["scan_gap_hours"]):
                if day_trades >= max_per_day:
                    break

                end_hour = start_hour + mcfg["consol_hours"]
                scan_end_hour = end_hour + mcfg["scan_after_hours"]

                if now_hour < end_hour or now_hour >= scan_end_hour:
                    continue

                consol = day_h1[(day_h1.index.hour >= start_hour) & (day_h1.index.hour < end_hour)]
                if len(consol) < 2:
                    continue

                range_high = consol["mid_high"].max()
                range_low = consol["mid_low"].min()
                consol_range = range_high - range_low
                if consol_range < cfg["asia_min_range"]:
                    continue

                bearish_level = range_high + cfg["sweep_threshold"]
                bullish_level = range_low - cfg["sweep_threshold"]

                # Check ALL scan bars up to current bar (live sees all past completed bars)
                scan_bars = day_h1[(day_h1.index.hour >= end_hour) & (day_h1.index <= bar_ts)]

                for sbar_ts, sb in scan_bars.iterrows():
                    if day_trades >= max_per_day:
                        break

                    sweep_dir = None
                    sweep_wick = None
                    if sb["mid_high"] > bearish_level and sb["mid_close"] < range_high:
                        sweep_dir = "bearish"
                        sweep_wick = sb["mid_high"]
                    elif sb["mid_low"] < bullish_level and sb["mid_close"] > range_low:
                        sweep_dir = "bullish"
                        sweep_wick = sb["mid_low"]

                    if not sweep_dir:
                        continue

                    # Dedup: already traded this sweep for this window
                    sk = (sbar_ts, start_hour)
                    if sk in traded_sweeps:
                        continue

                    # Bias filter
                    if bias != "neutral":
                        if sweep_dir == "bullish" and bias != "bullish":
                            continue
                        if sweep_dir == "bearish" and bias != "bearish":
                            continue

                    # Engulfing search
                    eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
                    m3_window = gold_m3[(gold_m3.index > sbar_ts) & (gold_m3.index <= eng_end)]
                    if len(m3_window) < 3:
                        traded_sweeps.add(sk)  # Mark as checked (no engulfing possible)
                        continue

                    start_idx = 2 if cfg["skip_first_bar"] else 1
                    found = False

                    for j in range(start_idx, len(m3_window)):
                        idx = gold_m3.index.get_loc(m3_window.index[j])
                        co = gold_m3["mid_open"].iat[idx]
                        cc = gold_m3["mid_close"].iat[idx]
                        po = gold_m3["mid_open"].iat[idx - 1]
                        pc = gold_m3["mid_close"].iat[idx - 1]
                        br = gold_m3["mid_high"].iat[idx] - gold_m3["mid_low"].iat[idx]

                        ct, cb = max(co, cc), min(co, cc)
                        pt, pb = max(po, pc), min(po, pc)

                        tol = ENGULFING_TOLERANCE
                        if sweep_dir == "bullish" and not (cc > co and cb <= pb + tol and ct >= pt - tol):
                            continue
                        if sweep_dir == "bearish" and not (cc < co and cb <= pb + tol and ct >= pt - tol):
                            continue

                        if sweep_dir == "bullish":
                            entry = gold_m3["ask_close"].iat[idx] + slippage(br)
                            slv = sweep_wick - cfg["sl_buffer"]
                            risk = entry - slv
                            if risk < cfg["min_sl"]:
                                slv = entry - cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.3 or risk > consol_range * 0.8:
                                continue
                            tpv = entry + consol_range * cfg["tp_multiplier"]
                            if tpv - entry < risk * 0.8:
                                continue
                            signals.append(Signal(
                                date=gold_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                                direction="long", risk=risk,
                                strategy="micro_alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                                metadata={"sweep_dir": sweep_dir, "sweep_wick": sweep_wick,
                                          "consol_range": consol_range, "window": f"{start_hour}-{end_hour}"},
                            ))
                        else:
                            entry = gold_m3["bid_close"].iat[idx] - slippage(br)
                            slv = sweep_wick + cfg["sl_buffer"]
                            risk = slv - entry
                            if risk < cfg["min_sl"]:
                                slv = entry + cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.3 or risk > consol_range * 0.8:
                                continue
                            tpv = entry - consol_range * cfg["tp_multiplier"]
                            if entry - tpv < risk * 0.8:
                                continue
                            signals.append(Signal(
                                date=gold_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                                direction="short", risk=risk,
                                strategy="micro_alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                                metadata={"sweep_dir": sweep_dir, "sweep_wick": sweep_wick,
                                          "consol_range": consol_range, "window": f"{start_hour}-{end_hour}"},
                            ))

                        traded_sweeps.add(sk)
                        day_trades += 1
                        found = True
                        break

                    if not found:
                        traded_sweeps.add(sk)
                    if found:
                        break  # One trade per sweep bar per window, move to next sweep

    return signals
