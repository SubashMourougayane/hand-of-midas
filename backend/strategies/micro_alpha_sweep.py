"""
Micro Alpha-Sweep: Rolling 4-hour consolidation windows every 2 hours.

Signal generation matches live scheduler exactly:
- Full 24hr coverage with midnight wrap (windows: 22-02, 00-04, ..., 16-20)
- Market close skip: windows whose consolidation includes hour 21 are excluded
- Walks each H1 bar chronologically (simulates scheduler poll)
- For each bar, checks ALL active windows
- For each window, checks ALL completed scan bars (not just current)
- Deduplicates by (sweep_bar_ts, window_start)
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
    "market_close_start": 21,
    "market_close_end": 22,
    "max_trades_per_day": 3,
}


def _hours_in_range(start: int, end: int) -> set:
    """Return set of hours in [start, end) handling midnight wrap."""
    if start < end:
        return set(range(start, end))
    return set(range(start, 24)) | set(range(0, end))


def _hour_past(current: int, target: int) -> bool:
    """Check if current hour is past target (within last 12 hours)."""
    diff = (current - target) % 24
    return 0 < diff <= 12


def generate_signals(
    gold_h1: pd.DataFrame,
    gold_m3: pd.DataFrame,
    daily_bias: dict,
    wick_to_body_ratio_max: float | None = None,
) -> list[Signal]:
    """wick_to_body_ratio_max: Filter #13 — reject engulfing if rejection-wick/body
    exceeds this ratio. None = read from config (no filter = legacy)."""
    cfg = ALPHA_SWEEP
    mcfg = MICRO_CONFIG
    if wick_to_body_ratio_max is None:
        wick_to_body_ratio_max = cfg.get("wick_to_body_ratio_max", float("inf"))
    close_start = mcfg["market_close_start"]
    signals = []

    dates = sorted(set(gold_h1.index.date))

    for date in dates:
        day_h1 = gold_h1[gold_h1.index.date == date]
        if len(day_h1) < 6:
            continue

        bias = daily_bias.get(date, "none")
        day_trades = 0
        max_per_day = mcfg["max_trades_per_day"]
        traded_sweeps = set()

        for bar_ts, bar in day_h1.iterrows():
            if day_trades >= max_per_day:
                break

            now_hour = bar_ts.hour

            # Skip during market close (same as live)
            if mcfg["market_close_start"] <= now_hour < mcfg["market_close_end"]:
                continue

            # Check all windows (0, 2, 4, ..., 22) — same as live scheduler
            for start_hour in range(0, 24, mcfg["scan_gap_hours"]):
                if day_trades >= max_per_day:
                    break

                end_hour = (start_hour + mcfg["consol_hours"]) % 24
                scan_end_hour = (start_hour + mcfg["consol_hours"] + mcfg["scan_after_hours"]) % 24

                # Skip windows whose consolidation overlaps market close
                consol_hours = _hours_in_range(start_hour, end_hour)
                if close_start in consol_hours:
                    continue

                # Check if consolidation is done
                if not _hour_past(now_hour, end_hour):
                    continue

                # Check if scan window hasn't expired
                if _hour_past(now_hour, scan_end_hour):
                    continue

                # Build consolidation range (handles midnight wrap)
                consol = day_h1[day_h1.index.hour.isin(consol_hours)]
                if len(consol) < 2:
                    continue

                range_high = consol["mid_high"].max()
                range_low = consol["mid_low"].min()
                consol_range = range_high - range_low
                if consol_range < cfg["asia_min_range"]:
                    continue

                bearish_level = range_high + cfg["sweep_threshold"]
                bullish_level = range_low - cfg["sweep_threshold"]

                # Check ALL scan bars up to current bar (handles midnight wrap)
                scan_hours = _hours_in_range(end_hour, scan_end_hour)
                scan_bars = day_h1[(day_h1.index.hour.isin(scan_hours)) & (day_h1.index <= bar_ts)]

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

                    # Bias filter (Variant C)
                    if bias != "neutral":
                        if sweep_dir == "bullish" and bias != "bullish":
                            continue
                        if sweep_dir == "bearish" and bias != "bearish":
                            continue

                    # Engulfing search
                    eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
                    m3_window = gold_m3[(gold_m3.index > sbar_ts) & (gold_m3.index <= eng_end)]
                    if len(m3_window) < 3:
                        traded_sweeps.add(sk)
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

                        # Filter #13: reject engulfing with large rejection wick
                        if wick_to_body_ratio_max < float("inf"):
                            body = abs(cc - co)
                            if body > 0:
                                m3_high = gold_m3["mid_high"].iat[idx]
                                m3_low = gold_m3["mid_low"].iat[idx]
                                if sweep_dir == "bullish":
                                    upper_wick = m3_high - ct
                                    if upper_wick > body * wick_to_body_ratio_max:
                                        continue
                                else:
                                    lower_wick = cb - m3_low
                                    if lower_wick > body * wick_to_body_ratio_max:
                                        continue

                        # Entry calculation
                        if sweep_dir == "bullish":
                            entry = gold_m3["ask_close"].iat[idx] + slippage(br)
                            slv = sweep_wick - cfg["sl_buffer"]
                            risk = entry - slv
                            if risk < cfg["min_sl"]:
                                slv = entry - cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.3 or risk > consol_range * 0.8:
                                continue
                            tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                            tpv = range_high - tp_buf
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
                            tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                            tpv = range_low + tp_buf
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
                        break  # One trade per sweep, move to next window
                if day_trades >= max_per_day:
                    break

    return signals
