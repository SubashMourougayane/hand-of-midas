"""
Alpha-Sweep for Brent Crude Oil (BCO/USD).
IDENTICAL logic to Gold Alpha-Sweep, different config thresholds.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ALPHA_SWEEP, slippage


@dataclass
class Signal:
    date: pd.Timestamp
    entry: float
    sl: float
    tp: float
    direction: str
    risk: float
    strategy: str
    max_bars: int
    timeframe: str
    metadata: Optional[dict] = None


def generate_signals(
    oil_h1: pd.DataFrame,
    oil_m3: pd.DataFrame,
    daily_bias: dict,
) -> list[Signal]:
    """Generate Alpha-Sweep signals for Oil."""
    cfg = ALPHA_SWEEP
    signals = []
    dates = sorted(set(oil_h1.index.date))

    for date in dates:
        day_h1 = oil_h1[oil_h1.index.date == date]
        asia = day_h1[(day_h1.index.hour >= 0) & (day_h1.index.hour < 8)]
        london = day_h1[(day_h1.index.hour >= 8) & (day_h1.index.hour < 16)]

        if len(asia) < 3 or len(london) < 2:
            continue

        ah = asia["mid_high"].max()
        al = asia["mid_low"].min()
        ar = ah - al

        if ar < cfg["asia_min_range"]:
            continue

        bias = daily_bias.get(date, "none")

        # Detect sweep
        sweep_dir = None
        sweep_wick = 0.0
        sweep_time = None

        for i in range(len(london)):
            bh = london["mid_high"].iloc[i]
            bl = london["mid_low"].iloc[i]
            bc = london["mid_close"].iloc[i]

            if bh > ah + cfg["sweep_threshold"] and bc < ah:
                sweep_dir = "bearish"
                sweep_wick = bh
                sweep_time = london.index[i]
                break
            elif bl < al - cfg["sweep_threshold"] and bc > al:
                sweep_dir = "bullish"
                sweep_wick = bl
                sweep_time = london.index[i]
                break

        if sweep_dir is None:
            continue

        if sweep_dir == "bullish" and bias != "bullish":
            continue
        if sweep_dir == "bearish" and bias != "bearish":
            continue

        # Find M3 engulfing
        end_time = sweep_time + pd.Timedelta(hours=cfg["engulfing_window_hours"])
        m3_window = oil_m3[(oil_m3.index > sweep_time) & (oil_m3.index <= end_time)]

        if len(m3_window) < 3:
            continue

        traded = False
        start_idx = 2 if cfg["skip_first_bar"] else 1

        for j in range(start_idx, len(m3_window)):
            if traded:
                break

            idx = oil_m3.index.get_loc(m3_window.index[j])
            co = oil_m3["mid_open"].iat[idx]
            cc = oil_m3["mid_close"].iat[idx]
            po = oil_m3["mid_open"].iat[idx - 1]
            pc = oil_m3["mid_close"].iat[idx - 1]
            br = oil_m3["mid_high"].iat[idx] - oil_m3["mid_low"].iat[idx]

            ct = max(co, cc)
            cb = min(co, cc)
            pt = max(po, pc)
            pb = min(po, pc)

            if sweep_dir == "bullish" and not (cc > co and cb <= pb and ct >= pt):
                continue
            if sweep_dir == "bearish" and not (cc < co and cb <= pb and ct >= pt):
                continue

            if sweep_dir == "bullish":
                entry = oil_m3["ask_close"].iat[idx] + slippage(br)
                slv = sweep_wick - cfg["sl_buffer"]
                risk = entry - slv
                if risk < cfg["min_sl"]:
                    slv = entry - cfg["min_sl"]
                    risk = cfg["min_sl"]
                if risk < 0.01 or risk > ar * 0.8:
                    continue
                tpv = entry + ar * cfg["tp_multiplier"]
                if tpv - entry < risk * 0.8:
                    continue
                signals.append(Signal(
                    date=oil_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                    direction="long", risk=risk, strategy="alpha_sweep",
                    max_bars=cfg["max_bars"], timeframe="M3",
                    metadata={"asia_high": ah, "asia_low": al, "sweep_dir": sweep_dir},
                ))
            else:
                entry = oil_m3["bid_close"].iat[idx] - slippage(br)
                slv = sweep_wick + cfg["sl_buffer"]
                risk = slv - entry
                if risk < cfg["min_sl"]:
                    slv = entry + cfg["min_sl"]
                    risk = cfg["min_sl"]
                if risk < 0.01 or risk > ar * 0.8:
                    continue
                tpv = entry - ar * cfg["tp_multiplier"]
                if entry - tpv < risk * 0.8:
                    continue
                signals.append(Signal(
                    date=oil_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                    direction="short", risk=risk, strategy="alpha_sweep",
                    max_bars=cfg["max_bars"], timeframe="M3",
                    metadata={"asia_high": ah, "asia_low": al, "sweep_dir": sweep_dir},
                ))
            traded = True

    return signals
