"""
Mean-Rev (formerly V7): Daily Mean Reversion Dip-Buy.
Ported from generate_portfolio_dashboard.py lines 122-138.
"""
import numpy as np
import pandas as pd
from backend.strategies.base import Signal
from backend.config import MEAN_REV, slippage


def generate_signals(gold_d: pd.DataFrame) -> list[Signal]:
    """Generate Mean-Rev signals from daily data. Long only."""
    cfg = MEAN_REV

    close_d = gold_d["mid_close"].values
    high_d = gold_d["mid_high"].values
    low_d = gold_d["mid_low"].values
    bar_range_d = high_d - low_d

    ma10_low = pd.Series(low_d).rolling(cfg["ma_period"]).mean().values
    ma10_high = pd.Series(high_d).rolling(cfg["ma_period"]).mean().values
    avg_range_10 = pd.Series(bar_range_d).rolling(cfg["ma_period"]).mean().values

    signals = []
    in_trade = False
    entry_bar = 0
    sl_val = 0.0

    for i in range(12, len(gold_d) - 1):
        if np.isnan(ma10_low[i]) or bar_range_d[i] < 0.5:
            continue

        c1 = (ma10_low[i - 1] - close_d[i - 2]) / bar_range_d[i - 1] if bar_range_d[i - 1] > 0 else 0
        c2 = (close_d[i - 1] - ma10_high[i - 2]) / bar_range_d[i - 1] if bar_range_d[i - 1] > 0 else 0

        # Exit check (if in trade)
        if in_trade:
            if c1 >= cfg["condition1_threshold"] or c2 >= cfg["condition2_threshold"]:
                in_trade = False
            elif (i - entry_bar) >= cfg["max_hold_days"]:
                in_trade = False
            elif gold_d["bid_low"].iat[i] <= sl_val:
                in_trade = False

        # Entry check
        if not in_trade:
            if c1 < cfg["condition1_threshold"] and c2 < cfg["condition2_threshold"]:
                br = bar_range_d[i]
                entry = gold_d["ask_open"].iat[i] + slippage(br)
                sl_val = entry - avg_range_10[i] * cfg["sl_range_multiplier"]
                risk = entry - sl_val

                if risk > 0:
                    signals.append(Signal(
                        date=gold_d.index[i],
                        entry=entry,
                        sl=sl_val,
                        tp=0,  # condition-based exit, no fixed TP
                        direction="long",
                        risk=risk,
                        strategy="mean_rev",
                        max_bars=cfg["max_hold_days"],
                        timeframe="D",
                        metadata={"c1": float(c1), "c2": float(c2)},
                    ))
                    in_trade = True
                    entry_bar = i

    return signals
