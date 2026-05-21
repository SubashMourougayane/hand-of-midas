"""
Cross-Market (formerly V8): Inter-Market Consensus strategy.
Ported from generate_portfolio_dashboard.py lines 109-121.
"""
import numpy as np
import pandas as pd
from backend.strategies.base import Signal
from backend.config import CROSS_MARKET, slippage


def generate_signals(
    gold_d: pd.DataFrame,
    eur: pd.DataFrame,
    us10y: pd.DataFrame,
    spx: pd.DataFrame,
    silver: pd.DataFrame,
    oil: pd.DataFrame,
    us2y: pd.DataFrame,
) -> list[Signal]:
    """Generate Cross-Market signals from daily data."""
    cfg = CROSS_MARKET
    w = cfg["weights"]
    th = cfg["threshold"]
    max_score = sum(w.values())

    aligned = pd.DataFrame(index=gold_d.index)
    aligned["eur_ret"] = eur["close"].reindex(gold_d.index, method="ffill").pct_change(3)
    aligned["us10y_ret"] = us10y["close"].reindex(gold_d.index, method="ffill").pct_change(3)
    aligned["spx_ret"] = spx["close"].reindex(gold_d.index, method="ffill").pct_change(3)
    aligned["silver_ret"] = silver["close"].reindex(gold_d.index, method="ffill").pct_change(3)
    aligned["oil_ret"] = oil["close"].reindex(gold_d.index, method="ffill").pct_change(3)
    aligned["us2y_ret"] = us2y["close"].reindex(gold_d.index, method="ffill").pct_change(3)

    se = np.where(aligned["eur_ret"] > th, 1, np.where(aligned["eur_ret"] < -th, -1, 0))
    sy = np.where(aligned["us10y_ret"] < -th, 1, np.where(aligned["us10y_ret"] > th, -1, 0))
    ss = np.where(aligned["spx_ret"] > th, 1, np.where(aligned["spx_ret"] < -th * 2, 1, np.where(aligned["spx_ret"] < -th, -1, 0)))
    ssi = np.where(aligned["silver_ret"] > th, 1, np.where(aligned["silver_ret"] < -th, -1, 0))
    so = np.where(aligned["oil_ret"] > th, 1, np.where(aligned["oil_ret"] < -th, -1, 0))
    s2 = np.where(aligned["us2y_ret"] < -th, 1, np.where(aligned["us2y_ret"] > th, -1, 0))

    consensus_arr = (
        se * w["eur"] + sy * w["us10y"] + ss * w["spx"] + ssi * w["silver"] + so * w["oil"] + s2 * w["us2y"]
    ) / max_score

    # Compute ATR for SL/TP
    gh = gold_d["mid_high"].values
    gl = gold_d["mid_low"].values
    gc = gold_d["mid_close"].values
    tr = np.maximum(gh - gl, np.maximum(np.abs(gh - np.roll(gc, 1)), np.abs(gl - np.roll(gc, 1))))
    atr = pd.Series(tr).rolling(cfg["atr_period"], min_periods=5).mean().values

    signals = []
    last_bar = -cfg["min_bar_gap"]

    for bar in range(20, len(gold_d) - 20):
        if bar - last_bar < cfg["min_bar_gap"]:
            continue
        if np.isnan(consensus_arr[bar]) or np.isnan(atr[bar]):
            continue
        if consensus_arr[bar] < cfg["consensus_min"]:
            continue

        br = gh[bar] - gl[bar]
        entry = gold_d["ask_close"].iat[bar] + slippage(br)
        sl = entry - atr[bar] * cfg["sl_atr_mult"]
        tp = entry + atr[bar] * cfg["tp_atr_mult"]

        if entry - sl < 1.0:
            continue

        signals.append(Signal(
            date=gold_d.index[bar],
            entry=entry,
            sl=sl,
            tp=tp,
            direction="long",
            risk=entry - sl,
            strategy="cross_market",
            max_bars=cfg["max_hold_days"],
            timeframe="D",
            metadata={"consensus": float(consensus_arr[bar]), "atr": float(atr[bar])},
        ))
        last_bar = bar

    return signals
