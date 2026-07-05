"""Causal market-structure engine for the SMC/ICT OTE strategy.

Quantised EXACTLY to "The Trader's Guide to SMC & ICT" (Anoop Upadhyaye):
- Swings: fractal highs/lows. A swing is CONFIRMED only after `k` bars to its
  right have CLOSED. `confirm_ts` = close-time of the confirming bar. The swing
  price/level is usable ONLY from `confirm_ts` onward. This kills the look-ahead
  bug in the naive `rolling(center=True)` swing detector.
- HH / HL / LH / LL classified vs the prior same-type confirmed swing.
- BSL = confirmed swing high, SSL = confirmed swing low (guide: "BSL and SSL are
  present at the Swing High and Swing Low").
- CHoCH per guide: uptrend broken when price closes below the last HL; downtrend
  broken when price closes above the last LH. (Structure state is informational;
  entries use confirmed impulse legs.)

NOTHING here reads a bar that closes at/after the timestamp it is attributed to.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Swing:
    idx: int            # index into the m15 frame
    kind: str           # "H" or "L"
    price: float        # high (for H) or low (for L)
    bar_ts: pd.Timestamp        # open ts of the swing bar
    confirm_ts: pd.Timestamp    # close ts of the k-th confirming bar (usable from here)
    label: str = ""     # HH / HL / LH / LL (vs prior same-kind swing)


def find_swings(m15: pd.DataFrame, k: int = 3) -> list[Swing]:
    """Fractal swings with strict right-side confirmation.

    Swing high at bar i: high[i] is the strict max of window [i-k, i+k].
    Confirmed at the CLOSE of bar i+k (i.e. m15 bar i+k close time). label=left
    bars => close time of bar j is timestamp[j] + 15min.
    """
    hi = m15["high"].values
    lo = m15["low"].values
    ts = m15["timestamp"].values
    n = len(m15)
    bar_td = np.timedelta64(15, "m")
    swings: list[Swing] = []
    for i in range(k, n - k):
        wl, wr = i - k, i + k
        # swing high: strictly greater than all others in window
        if hi[i] == hi[wl:wr + 1].max() and (hi[i] > hi[wl:i]).all() and (hi[i] > hi[i + 1:wr + 1]).all():
            confirm = pd.Timestamp(ts[i + k]) + bar_td  # close of confirming bar
            swings.append(Swing(i, "H", float(hi[i]), pd.Timestamp(ts[i]), confirm))
        elif lo[i] == lo[wl:wr + 1].min() and (lo[i] < lo[wl:i]).all() and (lo[i] < lo[i + 1:wr + 1]).all():
            confirm = pd.Timestamp(ts[i + k]) + bar_td
            swings.append(Swing(i, "L", float(lo[i]), pd.Timestamp(ts[i]), confirm))
    # order by confirmation time (the order info actually becomes available)
    swings.sort(key=lambda s: (s.confirm_ts, s.idx))
    # classify HH/HL/LH/LL vs prior same-kind
    last_h = None
    last_l = None
    for s in swings:
        if s.kind == "H":
            s.label = "HH" if (last_h is None or s.price > last_h) else "LH"
            last_h = s.price
        else:
            s.label = "HL" if (last_l is None or s.price > last_l) else "LL"
            last_l = s.price
    return swings


@dataclass
class ImpulseLeg:
    side: int               # +1 long setup (up impulse), -1 short setup (down impulse)
    lo_price: float         # SSL (swing low of the leg)
    hi_price: float         # BSL (swing high of the leg)
    lo_ts: pd.Timestamp
    hi_ts: pd.Timestamp
    arm_ts: pd.Timestamp    # when the leg is fully confirmed (later of the two confirms)
    hh: bool                # was the terminal high a HH (long) / terminal low a LL (short)


def build_legs(swings: list[Swing]) -> list[ImpulseLeg]:
    """An impulse leg = consecutive (confirmed) swing-low then swing-high (long)
    or swing-high then swing-low (short). arm_ts = later confirm of the pair, so
    the whole leg is known before we arm any order.
    """
    legs: list[ImpulseLeg] = []
    for a, b in zip(swings, swings[1:]):
        if a.kind == "L" and b.kind == "H" and b.price > a.price:
            legs.append(ImpulseLeg(
                side=+1, lo_price=a.price, hi_price=b.price,
                lo_ts=a.bar_ts, hi_ts=b.bar_ts,
                arm_ts=max(a.confirm_ts, b.confirm_ts), hh=(b.label == "HH"),
            ))
        elif a.kind == "H" and b.kind == "L" and b.price < a.price:
            legs.append(ImpulseLeg(
                side=-1, lo_price=b.price, hi_price=a.price,
                lo_ts=b.bar_ts, hi_ts=a.bar_ts,
                arm_ts=max(a.confirm_ts, b.confirm_ts), hh=(b.label == "LL"),
            ))
    return legs


def fvg_zones(m15: pd.DataFrame) -> pd.DataFrame:
    """Fair Value Gaps (guide: low[i] > high[i-2] bullish; high[i] < low[i-2] bearish).
    Zone is 'known' once bar i has CLOSED => valid_ts = close of bar i.
    Returns columns: dir(+1/-1), lo, hi, ce, valid_ts.
    """
    hi = m15["high"].values
    lo = m15["low"].values
    ts = m15["timestamp"].values
    bar_td = np.timedelta64(15, "m")
    rows = []
    for i in range(2, len(m15)):
        if lo[i] > hi[i - 2]:  # bullish FVG
            rows.append((+1, hi[i - 2], lo[i], (hi[i - 2] + lo[i]) / 2,
                         pd.Timestamp(ts[i]) + bar_td))
        elif hi[i] < lo[i - 2]:  # bearish FVG
            rows.append((-1, hi[i], lo[i - 2], (hi[i] + lo[i - 2]) / 2,
                         pd.Timestamp(ts[i]) + bar_td))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "ce", "valid_ts"])


def ob_zones(m15: pd.DataFrame, body_frac: float = 0.70) -> pd.DataFrame:
    """High-probability Order Blocks (guide: body >= 70% of candle range).
    Bullish OB = up candle; bearish OB = down candle. valid_ts = close of the bar.
    Returns: dir(+1/-1), lo, hi, valid_ts.
    """
    o = m15["open"].values
    c = m15["close"].values
    hi = m15["high"].values
    lo = m15["low"].values
    ts = m15["timestamp"].values
    bar_td = np.timedelta64(15, "m")
    rng = hi - lo
    body = np.abs(c - o)
    rows = []
    for i in range(len(m15)):
        if rng[i] <= 0:
            continue
        if body[i] / rng[i] >= body_frac:
            d = +1 if c[i] > o[i] else -1
            rows.append((d, float(lo[i]), float(hi[i]), pd.Timestamp(ts[i]) + bar_td))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "valid_ts"])
