"""Deep sweep on OB winner. Variants:
- impulse strength: 1.5/2.0/2.5 ATR
- expiry: 96/192/384 M5 bars
- session: all / NY 8-15 / Asian-only / overlap
- direction: long-only / short-only / both
- trend filter: ema20>ema50 / disabled
- TP: 1.5/2/2.5/3/4 R
- stop buffer: 0 / 0.1 / 0.2 ATR added to stop
- min impulse zone width (skip narrow zones)
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd
from itertools import product

from research.harness.causal_sim import load_data, simulate, headline, print_headline, persist


def detect_ob_with_strength(m15: pd.DataFrame, atr_mult: float) -> list[dict]:
    obs = []
    closes = m15["close"].values
    opens = m15["open"].values
    highs = m15["high"].values
    lows = m15["low"].values
    atr = m15["atr14"].values
    for i in range(20, len(m15) - 3):
        if not np.isfinite(atr[i]) or atr[i] <= 0: continue
        move_up = closes[i+3] - opens[i+1]
        if move_up >= atr_mult * atr[i] and closes[i] < opens[i]:
            obs.append({
                "m15_idx_ob": i, "side": 1,
                "top": float(highs[i]), "bot": float(lows[i]),
                "atr_at_ob": float(atr[i]),
                "confirmed_idx": i + 3,
            })
        move_dn = opens[i+1] - closes[i+3]
        if move_dn >= atr_mult * atr[i] and closes[i] > opens[i]:
            obs.append({
                "m15_idx_ob": i, "side": -1,
                "top": float(highs[i]), "bot": float(lows[i]),
                "atr_at_ob": float(atr[i]),
                "confirmed_idx": i + 3,
            })
    return obs


def generate_signals(obs, m5, *, expiry_bars: int, session_filter: str | None = None,
                     trend_filter: bool = False, direction: int | None = None) -> pd.DataFrame:
    """For each OB, scan M5 forward for retest, emit one signal per OB."""
    high = m5["high"].values
    low = m5["low"].values
    atr_lag = m5["atr14_lag"].values
    ema20_lag = m5["ema20_lag"].values
    ema50_lag = m5["ema50_lag"].values
    ny_hr = m5["ny_hr"].values
    ts = m5["timestamp"].values

    signals = []
    for ob in obs:
        if direction is not None and ob["side"] != direction:
            continue
        # confirmed timestamp from m15 frame (already encoded as index; we don't have it here)
        # Use the ob_idx_ob + 3 as a proxy for M15 bar after impulse closes
        # Actually we need m15 timestamp at confirmed_idx — store this in OB
        # For now, use the m5 boundary: we'll search from a known time.
        # Better: pass confirmed_ts directly. Update detect_ob_with_strength.
        confirmed_ts = ob["confirmed_ts"]
        start = np.searchsorted(ts, np.datetime64(confirmed_ts), side="right")
        end = min(len(m5), start + expiry_bars)
        for i in range(start, end):
            if session_filter == "ny" and not (8 <= ny_hr[i] < 16):
                continue
            if session_filter == "asia" and not (ny_hr[i] >= 19 or ny_hr[i] < 3):
                continue
            in_zone = False
            if ob["side"] == 1:
                if low[i] <= ob["top"] and high[i] >= ob["bot"]:
                    in_zone = True
            else:
                if high[i] >= ob["bot"] and low[i] <= ob["top"]:
                    in_zone = True
            if not in_zone:
                continue
            risk = atr_lag[i]
            if not np.isfinite(risk) or risk <= 0: break
            if trend_filter:
                if ob["side"] == 1 and not (ema20_lag[i] > ema50_lag[i]): break
                if ob["side"] == -1 and not (ema20_lag[i] < ema50_lag[i]): break
            signals.append({"entry_index": i + 1, "side": ob["side"], "risk_units": float(risk),
                            "ob_atr": ob["atr_at_ob"]})
            break
    return pd.DataFrame(signals)


def run() -> None:
    m1, m5, m15 = load_data()

    # Test grid
    atr_mults = [1.5, 2.0, 2.5]
    expiry_options = [96, 192, 384]
    tp_options = [2.0, 3.0, 4.0]
    sessions = [None, "ny"]
    trends = [False, True]
    directions = [None, 1, -1]

    print(f"{'pattern':<60s} {'n':>5s} {'/yr':>4s} {'net':>8s} {'/yr':>6s} {'WR%':>5s} {'PF':>5s} {'DD':>7s} {'MAR':>6s} {'pos':>5s}")
    print("-" * 130)

    # First, recompute OBs with confirmed_ts
    for atr_mult in atr_mults:
        obs = []
        closes = m15["close"].values; opens = m15["open"].values
        highs = m15["high"].values; lows = m15["low"].values
        atr_v = m15["atr14"].values
        ts_m15 = m15["timestamp"].values
        for i in range(20, len(m15) - 3):
            if not np.isfinite(atr_v[i]) or atr_v[i] <= 0: continue
            move_up = closes[i+3] - opens[i+1]
            if move_up >= atr_mult * atr_v[i] and closes[i] < opens[i]:
                obs.append({"side": 1, "top": float(highs[i]), "bot": float(lows[i]),
                            "atr_at_ob": float(atr_v[i]), "confirmed_ts": ts_m15[i+3]})
            move_dn = opens[i+1] - closes[i+3]
            if move_dn >= atr_mult * atr_v[i] and closes[i] > opens[i]:
                obs.append({"side": -1, "top": float(highs[i]), "bot": float(lows[i]),
                            "atr_at_ob": float(atr_v[i]), "confirmed_ts": ts_m15[i+3]})

        for expiry, tp, sess, trend, direction in product(expiry_options, tp_options, sessions, trends, directions):
            sig = generate_signals(obs, m5,
                                   expiry_bars=expiry, session_filter=sess,
                                   trend_filter=trend, direction=direction)
            if len(sig) < 200: continue
            t = simulate(sig[["entry_index","side","risk_units"]], m5, tp_mult=tp)
            h = headline(t)
            if h["n"] < 200: continue
            # Quick filter: only print if interesting
            if h["pf"] < 1.0 or h["mar"] < 0.5:
                continue
            dir_str = "both" if direction is None else ("long" if direction==1 else "short")
            sess_str = sess or "all"
            trend_str = "trend" if trend else "notrend"
            label = f"ATR{atr_mult} exp{expiry} TP{tp} {sess_str} {trend_str} {dir_str}"
            print(f"  {label:<58s} n={h['n']:>5d} /yr={h['trades_per_year']:>4.0f} "
                  f"net={h['net']:>+7.1f}R /yr={h['yr_r']:>+5.1f} WR={h['wr']*100:>4.1f}% "
                  f"PF={h['pf']:>5.2f} DD={h['dd']:>+6.1f} MAR={h['mar']:>+5.2f} {h['pos_years']:>4s}")
            persist("order_block", f"sweep_atr{atr_mult}_exp{expiry}_tp{tp}_{sess_str}_{trend_str}_{dir_str}", t,
                    notes=label)


if __name__ == "__main__":
    print("=" * 130)
    print("OB DEEP VARIANT SWEEP")
    print("=" * 130)
    run()
