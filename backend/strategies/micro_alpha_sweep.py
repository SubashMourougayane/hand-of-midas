"""
Micro Alpha-Sweep: Rolling 4-hour consolidation windows every 2 hours.

Same edge as Alpha-Sweep (sweep + snapback + engulfing) but with shorter
consolidation periods generating more opportunities.

Key difference from original:
- Original: Fixed 00:00-08:00 Asia = 1 window/day
- Micro: Rolling 4hr windows starting every 2hrs = up to 8 windows/day
- Same fill model, same slippage, same engulfing, same bias filter
"""
import numpy as np
import pandas as pd
from backend.strategies.base import Signal
from backend.config import ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE


MICRO_CONFIG = {
    "consol_hours": 4,        # Each consolidation window is 4 hours
    "scan_gap_hours": 2,      # New window starts every 2 hours
    "scan_after_hours": 6,    # Scan up to 6 hours after consolidation ends
    "scan_start_hour": 0,     # First consolidation starts at 00:00 UTC
    "scan_end_hour": 20,      # Last consolidation starts at 16:00 (ends 20:00)
}


def generate_signals(
    gold_h1: pd.DataFrame,
    gold_m3: pd.DataFrame,
    daily_bias: dict,
) -> list[Signal]:
    """
    Generate Micro Alpha-Sweep signals using rolling 4hr consolidation windows.
    """
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
        used_sweep_times = set()

        # Generate rolling consolidation windows
        for start_hour in range(mcfg["scan_start_hour"], mcfg["scan_end_hour"] - mcfg["consol_hours"] + 1, mcfg["scan_gap_hours"]):
            if day_trades >= max_per_day:
                break

            end_hour = start_hour + mcfg["consol_hours"]

            # Get consolidation bars
            consol = day_h1[(day_h1.index.hour >= start_hour) & (day_h1.index.hour < end_hour)]
            if len(consol) < 2:
                continue

            range_high = consol["mid_high"].max()
            range_low = consol["mid_low"].min()
            consol_range = range_high - range_low

            if consol_range < cfg["asia_min_range"]:
                continue

            # Scan window: bars AFTER consolidation, up to scan_after_hours
            scan_start = end_hour
            scan_end = min(end_hour + mcfg["scan_after_hours"], 24)
            scan_bars = day_h1[(day_h1.index.hour >= scan_start) & (day_h1.index.hour < scan_end)]

            if len(scan_bars) < 1:
                continue

            # Detect sweeps in scan window
            bearish_level = range_high + cfg["sweep_threshold"]
            bullish_level = range_low - cfg["sweep_threshold"]

            for i in range(len(scan_bars)):
                if day_trades >= max_per_day:
                    break

                mh = scan_bars["mid_high"].iloc[i]
                ml = scan_bars["mid_low"].iloc[i]
                mc = scan_bars["mid_close"].iloc[i]
                sweep_time = scan_bars.index[i]

                # Deduplicate: don't process same H1 bar for sweep twice
                if sweep_time in used_sweep_times:
                    continue

                sweep_dir = None
                sweep_wick = None

                if mh > bearish_level and mc < range_high:
                    sweep_dir = "bearish"
                    sweep_wick = mh
                elif ml < bullish_level and mc > range_low:
                    sweep_dir = "bullish"
                    sweep_wick = ml

                if not sweep_dir:
                    continue

                # Bias filter (Variant C)
                if bias != "neutral":
                    if sweep_dir == "bullish" and bias != "bullish":
                        continue
                    if sweep_dir == "bearish" and bias != "bearish":
                        continue

                # Find M3 engulfing within window
                eng_end_time = sweep_time + pd.Timedelta(hours=cfg["engulfing_window_hours"])
                m3_window = gold_m3[(gold_m3.index > sweep_time) & (gold_m3.index <= eng_end_time)]

                if len(m3_window) < 3:
                    continue

                start_idx = 2 if cfg["skip_first_bar"] else 1
                found_engulfing = False

                for j in range(start_idx, len(m3_window)):
                    idx = gold_m3.index.get_loc(m3_window.index[j])
                    co = gold_m3["mid_open"].iat[idx]
                    cc = gold_m3["mid_close"].iat[idx]
                    po = gold_m3["mid_open"].iat[idx - 1]
                    pc = gold_m3["mid_close"].iat[idx - 1]
                    br = gold_m3["mid_high"].iat[idx] - gold_m3["mid_low"].iat[idx]

                    ct = max(co, cc)
                    cb = min(co, cc)
                    pt = max(po, pc)
                    pb = min(po, pc)

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
                            date=gold_m3.index[idx],
                            entry=entry, sl=slv, tp=tpv,
                            direction="long", risk=risk,
                            strategy="micro_alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                            metadata={"range_high": range_high, "range_low": range_low,
                                      "consol_start": start_hour, "consol_end": end_hour,
                                      "sweep_dir": sweep_dir, "sweep_wick": sweep_wick},
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
                            date=gold_m3.index[idx],
                            entry=entry, sl=slv, tp=tpv,
                            direction="short", risk=risk,
                            strategy="micro_alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                            metadata={"range_high": range_high, "range_low": range_low,
                                      "consol_start": start_hour, "consol_end": end_hour,
                                      "sweep_dir": sweep_dir, "sweep_wick": sweep_wick},
                        ))

                    used_sweep_times.add(sweep_time)
                    day_trades += 1
                    found_engulfing = True
                    break

    return signals
