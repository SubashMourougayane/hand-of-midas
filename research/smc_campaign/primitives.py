"""Causal SMC/ICT primitives — quantised to the PDF dot, page-referenced.

EVERY object carries a `valid_ts` / `confirm_ts` = the CLOSE time of the last bar
needed to know it exists. Downstream code may only USE an object once the sim's
current time >= that ts. This is the single defense against look-ahead.

PDF map (Anoop Upadhyaye, "Trader's Guide to SMC & ICT"):
  pg4  : CHoCH rules — uptrend broken when 2 lower structure vs prior; the guide's
         table: "Up Trend: 2HH should break 1HL"; "Down Trend: 2LL should break 1LH".
  pg4  : Swing Low = lowest point between two consecutive higher highs (ICT def pg12).
  pg5  : OB = uppermost/lowermost candle at BOS/CHoCH; big-wick -> use wick or body.
         OF = OB + 1 previous candle.
  pg6  : FVG = middle candle uncovered by prev+next candle & shadows.
  pg6-7: IDM = resistance formed between CHoCH/BOS, within the swing (inducement).
         LGA = liquidity grab area, on swing high/low (external).
  pg16 : High-prob OB body>=70% of range; low-prob body<50%.
  pg16 : Bullish Breaker Block: Low-High-HigherHigh-... overlap of green-body region
         and bullish FVG. Bearish mirror.
  pg17 : Mitigation: Bullish Low-High-HL-HH; Bearish High-Low-LH-LL.
  pg18 : QML: uptrend makes LL with MSS then reverses at QML zone (pre-drop head high).
  pg12 : ICT swing low = lowest between two consecutive HH.

All timestamps tz-aware UTC. IST session windows (pg3) via tz_convert Asia/Kolkata.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# Swings (fractal, right-side confirmed) — the causal backbone
# ----------------------------------------------------------------------------
@dataclass
class Swing:
    idx: int
    kind: str            # "H" | "L"
    price: float
    bar_ts: pd.Timestamp        # open ts of the swing bar
    confirm_ts: pd.Timestamp    # close ts of the k-th confirming bar (usable from here)
    label: str = ""             # HH/HL/LH/LL vs prior same-kind


def find_swings(df: pd.DataFrame, k: int = 3, tf_min: int = 15) -> list[Swing]:
    """Fractal swing: extreme of window [i-k, i+k]. Confirmed at close of bar i+k
    = timestamp[i+k] + tf_min. Ordered by confirm_ts (the order info arrives)."""
    hi = df["high"].values
    lo = df["low"].values
    ts = df["timestamp"].values
    n = len(df)
    td = np.timedelta64(tf_min, "m")
    sw: list[Swing] = []
    for i in range(k, n - k):
        wl, wr = i - k, i + k
        if hi[i] == hi[wl:wr + 1].max() and (hi[i] > hi[wl:i]).all() and (hi[i] > hi[i + 1:wr + 1]).all():
            sw.append(Swing(i, "H", float(hi[i]), pd.Timestamp(ts[i]), pd.Timestamp(ts[i + k]) + td))
        elif lo[i] == lo[wl:wr + 1].min() and (lo[i] < lo[wl:i]).all() and (lo[i] < lo[i + 1:wr + 1]).all():
            sw.append(Swing(i, "L", float(lo[i]), pd.Timestamp(ts[i]), pd.Timestamp(ts[i + k]) + td))
    sw.sort(key=lambda s: (s.confirm_ts, s.idx))
    last_h = last_l = None
    for s in sw:
        if s.kind == "H":
            s.label = "HH" if (last_h is None or s.price > last_h) else "LH"
            last_h = s.price
        else:
            s.label = "HL" if (last_l is None or s.price > last_l) else "LL"
            last_l = s.price
    return sw


# ----------------------------------------------------------------------------
# Structure events: BOS / CHoCH (pg4) — computed from CLOSED bars
# ----------------------------------------------------------------------------
@dataclass
class StructEvent:
    kind: str            # "BOS" | "CHOCH"
    dir: int             # +1 up, -1 down
    level: float         # the broken swing level
    break_idx: int       # df index of the breaking close
    confirm_ts: pd.Timestamp
    ref_swing_ts: pd.Timestamp


def structure_events(df: pd.DataFrame, swings: list[Swing], tf_min: int = 15) -> list[StructEvent]:
    """BOS = continuation break of last same-dir swing; CHoCH = first break against
    the prevailing trend. We track trend by the sequence of confirmed swings and mark
    a close beyond the last opposing swing. Causal: uses close[j] and only swings whose
    confirm_ts <= close-time of bar j."""
    close = df["close"].values
    ts = df["timestamp"].values
    td = np.timedelta64(tf_min, "m")
    evs: list[StructEvent] = []
    # iterate bars; maintain last confirmed swing high/low available at each bar
    sw_ptr = 0
    last_high = None  # (price, ts)
    last_low = None
    trend = 0  # +1 up, -1 down, 0 unknown
    for j in range(len(df)):
        close_time = pd.Timestamp(ts[j]) + td
        # ingest swings confirmed by now
        while sw_ptr < len(swings) and swings[sw_ptr].confirm_ts <= close_time:
            s = swings[sw_ptr]
            if s.kind == "H":
                last_high = (s.price, s.bar_ts)
            else:
                last_low = (s.price, s.bar_ts)
            sw_ptr += 1
        c = close[j]
        if last_high and c > last_high[0]:
            kind = "BOS" if trend >= 0 else "CHOCH"
            evs.append(StructEvent(kind, +1, last_high[0], j, close_time, last_high[1]))
            trend = +1
            last_high = None  # consume; next high must re-form
        elif last_low and c < last_low[0]:
            kind = "BOS" if trend <= 0 else "CHOCH"
            evs.append(StructEvent(kind, -1, last_low[0], j, close_time, last_low[1]))
            trend = -1
            last_low = None
    return evs


# ----------------------------------------------------------------------------
# FVG (pg6) + CE
# ----------------------------------------------------------------------------
def fvg_zones(df: pd.DataFrame, tf_min: int = 15) -> pd.DataFrame:
    hi = df["high"].values
    lo = df["low"].values
    ts = df["timestamp"].values
    td = np.timedelta64(tf_min, "m")
    rows = []
    for i in range(2, len(df)):
        if lo[i] > hi[i - 2]:
            rows.append((+1, hi[i - 2], lo[i], (hi[i - 2] + lo[i]) / 2, i, pd.Timestamp(ts[i]) + td))
        elif hi[i] < lo[i - 2]:
            rows.append((-1, hi[i], lo[i - 2], (hi[i] + lo[i - 2]) / 2, i, pd.Timestamp(ts[i]) + td))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "ce", "mid_idx", "valid_ts"])


# ----------------------------------------------------------------------------
# Order Blocks — TWO defs per PDF
#   (a) high-prob body>=70% (pg16); low-prob body<50%
#   (b) structure OB (pg5): last opposite-color candle before the BOS/CHoCH move
# ----------------------------------------------------------------------------
def ob_bodyfrac(df: pd.DataFrame, body_frac: float = 0.70, tf_min: int = 15) -> pd.DataFrame:
    o, c, hi, lo = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    ts = df["timestamp"].values
    td = np.timedelta64(tf_min, "m")
    rng = hi - lo
    body = np.abs(c - o)
    rows = []
    for i in range(len(df)):
        if rng[i] <= 0:
            continue
        if body[i] / rng[i] >= body_frac:
            rows.append((+1 if c[i] > o[i] else -1, float(lo[i]), float(hi[i]), i, pd.Timestamp(ts[i]) + td))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "idx", "valid_ts"])


def ob_structure(df: pd.DataFrame, events: list[StructEvent], tf_min: int = 15) -> pd.DataFrame:
    """Structure OB (pg5): the last opposite-color candle immediately before the
    displacement that caused the BOS/CHoCH. Valid at the break's confirm_ts."""
    o, c, hi, lo = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    rows = []
    for e in events:
        j = e.break_idx
        if e.dir > 0:  # up break -> last DOWN candle before j
            k = j
            while k > 0 and not (c[k] < o[k]):
                k -= 1
            rows.append((+1, float(lo[k]), float(hi[k]), k, e.confirm_ts))
        else:          # down break -> last UP candle before j
            k = j
            while k > 0 and not (c[k] > o[k]):
                k -= 1
            rows.append((-1, float(lo[k]), float(hi[k]), k, e.confirm_ts))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "idx", "valid_ts"])


# ----------------------------------------------------------------------------
# IDM (Inducement, pg6-7): the minor swing (opposite pullback) sitting BETWEEN the
# CHoCH/BOS and the POI — the level the market cheats to grab before the real move.
# Practically: after a directional break, the nearest opposite minor swing inside the
# leg is the IDM. Marked valid at the break confirm_ts.
# ----------------------------------------------------------------------------
def idm_levels(swings: list[Swing], events: list[StructEvent]) -> pd.DataFrame:
    rows = []
    for e in events:
        # nearest opposite-kind swing confirmed before the break, inside the leg
        want = "L" if e.dir > 0 else "H"
        cand = [s for s in swings if s.kind == want and s.confirm_ts <= e.confirm_ts]
        if cand:
            s = cand[-1]
            rows.append((e.dir, s.price, s.bar_ts, e.confirm_ts))
    return pd.DataFrame(rows, columns=["dir", "level", "level_ts", "valid_ts"])


# ----------------------------------------------------------------------------
# Liquidity sweep (pg7 LGA, pg29 POI): a swing that takes out a prior same-kind swing.
# Returns per swing: swept(bool), swept_level, sweep_depth_rank.
# ----------------------------------------------------------------------------
def sweeps(swings: list[Swing], lookback: int = 10) -> pd.DataFrame:
    rows = []
    for bi, b in enumerate(swings):
        priors = [s for s in swings[:bi] if s.kind == b.kind][-lookback:]
        if b.kind == "L":
            hit = [s for s in priors if b.price < s.price]
        else:
            hit = [s for s in priors if b.price > s.price]
        if hit:
            rank = len(priors) - priors.index(hit[-1])
            rows.append((bi, b.kind, b.price, b.bar_ts, b.confirm_ts, hit[-1].price, rank))
    return pd.DataFrame(rows, columns=["swing_i", "kind", "price", "bar_ts", "confirm_ts",
                                       "swept_level", "depth_rank"])


# ----------------------------------------------------------------------------
# MSS (Market Structure Shift, pg18): a CHoCH on the working TF — reuse CHoCH events.
# ----------------------------------------------------------------------------
def mss_events(events: list[StructEvent]) -> list[StructEvent]:
    return [e for e in events if e.kind == "CHOCH"]


# ----------------------------------------------------------------------------
# Sessions (pg3, IST / Asia-Kolkata). Returns hour-of-day in a given tz for a ts array.
# Kill zone for our killzone tests uses NY hours; the PDF's exact IST windows below.
# ----------------------------------------------------------------------------
IST = "Asia/Kolkata"
SESSIONS_IST = {  # (start_hour, start_min, end_hour, end_min) India time, pg3
    "sydney": (3, 30, 10, 0),
    "tokyo": (5, 30, 14, 0),
    "london": (12, 30, 21, 15),
    "newyork": (18, 30, 27, 0),   # 6:30PM -> 3:00AM next day (27=3+24)
    "london_tokyo_overlap": (12, 30, 14, 0),
    "ny_europe_overlap": (18, 30, 21, 15),
}


def in_session_ist(ts_utc: pd.Timestamp, session: str) -> bool:
    t = ts_utc.tz_convert(IST)
    h = t.hour + t.minute / 60.0
    s0h, s0m, s1h, s1m = SESSIONS_IST[session]
    lo = s0h + s0m / 60.0
    hi = s1h + s1m / 60.0
    hh = h if h >= lo else h + 24  # wrap for NY crossing midnight
    return lo <= hh <= hi


def session_hour_ist(df: pd.DataFrame) -> np.ndarray:
    return df["timestamp"].dt.tz_convert(IST).dt.hour.values


# ----------------------------------------------------------------------------
# Breaker Block (pg16) + Mitigation (pg17): pattern of 4 consecutive confirmed swings.
#   Bullish Breaker: L - H - HH - (then break) ; entry zone = overlap of the up-candle
#     body region (L->H leg) and a bullish FVG in the HL->HH leg.
#   Bullish Mitigation: L - H - HL - HH.
# We detect the 4-swing shapes from confirmed swings; zone valid at 4th swing confirm.
# ----------------------------------------------------------------------------
def breaker_blocks(swings: list[Swing]) -> pd.DataFrame:
    rows = []
    for a, b, c, d in zip(swings, swings[1:], swings[2:], swings[3:]):
        # Bullish BBB: Low, High, HigherHigh (c>b price & c.kind H), then LL/pullback d
        if a.kind == "L" and b.kind == "H" and c.kind == "H" and c.price > b.price:
            # zone = a.price .. b.price (the green body region base)
            rows.append((+1, min(a.price, b.price), max(a.price, b.price),
                         d.confirm_ts))
        if a.kind == "H" and b.kind == "L" and c.kind == "L" and c.price < b.price:
            rows.append((-1, min(a.price, b.price), max(a.price, b.price),
                         d.confirm_ts))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "valid_ts"])


def mitigation_blocks(swings: list[Swing]) -> pd.DataFrame:
    rows = []
    for a, b, c, d in zip(swings, swings[1:], swings[2:], swings[3:]):
        # Bullish mitigation: Low - High - HL - HH
        if (a.kind == "L" and b.kind == "H" and c.kind == "L" and d.kind == "H"
                and c.price > a.price and d.price > b.price):
            rows.append((+1, a.price, b.price, d.confirm_ts))
        # Bearish: High - Low - LH - LL
        if (a.kind == "H" and b.kind == "L" and c.kind == "H" and d.kind == "L"
                and c.price < a.price and d.price < b.price):
            rows.append((-1, b.price, a.price, d.confirm_ts))
    return pd.DataFrame(rows, columns=["dir", "lo", "hi", "valid_ts"])
