"""ICT Premium/Discount OTE strategy — quantised to the SMC/ICT guide, fully causal.

Setup (LONG, mirror for SHORT):
  1. Confirmed impulse leg: swing-low -> swing-high (both fractal-confirmed, k bars
     right-side). Leg armed at arm_ts = later of the two confirmations.
  2. Fib on the up-leg (0 at swingH, 1 at swingL per guide's "draw down to up").
     OTE = swingH - 0.705*(swingH - swingL).  Discount = below 0.5.
  3. Confluence (optional): a bullish FVG or high-prob bullish OB whose zone
     overlaps the OTE level, valid before arm_ts.
  4. Place a BUY LIMIT at OTE. Fill = first M5 bar within `wait_bars` whose LOW
     touches OTE (price trades into the level). Entry price = OTE (limit fill).
  5. TP = BSL (swingH). SL = below SSL (swingL) by sl_buf_atr * ATR (guide: "SL
     below SSL"). Exit = close-based bracket within `horizon` M5 bars.
  6. Invalidation before fill: price closes beyond SSL (long) => cancel.

Everything used to arm/fill is known from CLOSED bars strictly before the event.
Cost: COST_USD / risk_units (same as XAU harness).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import load_data, COST_USD  # noqa: E402
from research.ict_ote.structure import (  # noqa: E402
    find_swings, build_legs, fvg_zones, ob_zones,
)

OTE_FIB = 0.705
DISCOUNT = 0.5


def _overlaps(level: float, zlo: float, zhi: float) -> bool:
    return zlo <= level <= zhi


def build_signals(
    m5: pd.DataFrame,
    m15: pd.DataFrame,
    *,
    swing_k: int = 3,
    wait_bars: int = 96,          # M5 bars to wait for the OTE limit to fill (~8h)
    sl_buf_atr: float = 0.10,     # SL beyond SSL/BSL in ATR units
    require_confluence: bool = True,
    require_hh: bool = False,     # require terminal swing to be HH/LL (trend continuation)
    require_trend: bool = False,  # M15 EMA20/50 must align with side at arm
    min_rr: float = 0.0,          # skip setups whose BSL/SSL RR < this
    entry_mode: str = "limit",    # "limit" = fill on tap; "confirm" = tap then M5 close-back rejection
    confirm_bars: int = 6,        # bars after tap to wait for the confirmation close
    sides: tuple[int, ...] = (+1, -1),
) -> pd.DataFrame:
    swings = find_swings(m15, k=swing_k)
    legs = build_legs(swings)
    fvg = fvg_zones(m15)
    ob = ob_zones(m15)

    # M5 fill arrays
    m5_ts = m5["timestamp"].values
    m5_lo = m5["low"].values
    m5_hi = m5["high"].values
    m5_cl = m5["close"].values
    m5_atr = m5["atr14_lag"].values          # last-closed-M15 ATR (already lagged)
    n5 = len(m5)

    # precompute searchable arrays for confluence by dir
    fvg_by = {d: fvg[fvg["dir"] == d].reset_index(drop=True) for d in (+1, -1)}
    ob_by = {d: ob[ob["dir"] == d].reset_index(drop=True) for d in (+1, -1)}

    def has_confluence(side: int, ote: float, leg) -> bool:
        """Confluence must be a zone FORMED DURING the impulse leg (guide draws
        OB/FVG inside the current structure) and overlap the OTE level."""
        lo_ts, hi_ts = leg.lo_ts, leg.hi_ts
        f = fvg_by[side]
        fv = f[(f["valid_ts"] > lo_ts) & (f["valid_ts"] <= leg.arm_ts)]
        if len(fv) and ((fv["lo"] <= ote) & (ote <= fv["hi"])).any():
            return True
        o = ob_by[side]
        ov = o[(o["valid_ts"] > lo_ts) & (o["valid_ts"] <= leg.arm_ts)]
        if len(ov) and ((ov["lo"] <= ote) & (ote <= ov["hi"])).any():
            return True
        return False

    # HTF trend alignment: use the lagged M15 EMA50/EMA20 on the fill bar (already
    # sourced from last-closed M15). Long only when ema20>ema50 (up), short reverse.
    m5_e20 = m5["ema20_lag"].values
    m5_e50 = m5["ema50_lag"].values

    sigs = []
    for leg in legs:
        if leg.side not in sides:
            continue
        if require_hh and not leg.hh:
            continue
        rng = leg.hi_price - leg.lo_price
        if rng <= 0:
            continue
        if leg.side > 0:
            ote = leg.hi_price - OTE_FIB * rng            # discount zone
            tp = leg.hi_price                             # BSL
            ssl = leg.lo_price
        else:
            ote = leg.lo_price + OTE_FIB * rng            # premium zone
            tp = leg.lo_price                             # SSL
            ssl = leg.hi_price                            # BSL (stop side)

        if require_confluence and not has_confluence(leg.side, ote, leg):
            continue

        # arm at first M5 bar whose OPEN ts >= arm_ts
        start = int(np.searchsorted(m5_ts, np.datetime64(leg.arm_ts), side="left"))
        if start >= n5 - 2:
            continue
        atr = m5_atr[start]
        if not np.isfinite(atr) or atr <= 0:
            continue
        if require_trend:
            e20, e50 = m5_e20[start], m5_e50[start]
            if not (np.isfinite(e20) and np.isfinite(e50)):
                continue
            if leg.side > 0 and not (e20 > e50):
                continue
            if leg.side < 0 and not (e20 < e50):
                continue
        sl = ssl - sl_buf_atr * atr if leg.side > 0 else ssl + sl_buf_atr * atr
        risk = abs(ote - sl)
        if risk <= 0:
            continue
        rr = abs(tp - ote) / risk
        if rr < min_rr:
            continue

        # wait for tap: price trades into OTE within wait_bars; invalidate if
        # a close breaks the stop side first.
        tap_i = -1
        end = min(n5 - 1, start + wait_bars)
        for j in range(start, end + 1):
            if leg.side > 0:
                if m5_cl[j] < sl:            # invalidated
                    break
                if m5_lo[j] <= ote:          # tapped
                    tap_i = j
                    break
            else:
                if m5_cl[j] > sl:
                    break
                if m5_hi[j] >= ote:
                    tap_i = j
                    break
        if tap_i < 0:
            continue

        if entry_mode == "limit":
            fill_i = tap_i
            entry_px = ote
        else:  # "confirm": after tap, wait for an M5 close back in trade direction
            fill_i = -1
            cend = min(n5 - 1, tap_i + confirm_bars)
            for j in range(tap_i, cend + 1):
                if leg.side > 0:
                    if m5_cl[j] < sl:
                        break
                    # confirmation = bullish close back above OTE
                    if m5_cl[j] > ote and m5_cl[j] > m5["open"].values[j]:
                        fill_i = j + 1 if j + 1 < n5 else -1
                        break
                else:
                    if m5_cl[j] > sl:
                        break
                    if m5_cl[j] < ote and m5_cl[j] < m5["open"].values[j]:
                        fill_i = j + 1 if j + 1 < n5 else -1
                        break
            if fill_i < 0:
                continue
            entry_px = m5["open"].values[fill_i]  # enter at next bar open post-confirm
            # recompute risk off actual entry
            risk = abs(entry_px - sl)
            if risk <= 0:
                continue

        sigs.append({
            "arm_ts": leg.arm_ts,
            "fill_index": fill_i,
            "entry_price": entry_px,
            "side": leg.side,
            "tp_price": tp,
            "sl_price": sl,
            "risk_units": risk,
        })
    return pd.DataFrame(sigs)


def simulate_price_bracket(
    signals: pd.DataFrame,
    m5: pd.DataFrame,
    *,
    horizon: int = 288,          # M5 bars (~24h)
    cost_usd: float = COST_USD,
) -> pd.DataFrame:
    """Fixed-price bracket: entry=OTE limit, TP=BSL/SSL price, SL beyond swept swing.
    Close-based touch. R measured vs risk_units = |entry - sl|.
    """
    cl = m5["close"].values
    ts = m5["timestamp"].values
    yr = m5["year"].values
    n = len(m5)
    outs = []
    for s in signals.itertuples(index=False):
        i = s.fill_index
        side = s.side
        entry = s.entry_price
        tp = s.tp_price
        sl = s.sl_price
        risk = s.risk_units
        if risk <= 0 or i >= n - 2:
            continue
        end = min(n - 1, i + horizon)
        outcome_r = None
        exit_i = end
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= sl:
                    outcome_r = (sl - entry) / risk; exit_i = j; break
                if c >= tp:
                    outcome_r = (tp - entry) / risk; exit_i = j; break
            else:
                if c >= sl:
                    outcome_r = (entry - sl) / risk; exit_i = j; break
                if c <= tp:
                    outcome_r = (entry - tp) / risk; exit_i = j; break
        if outcome_r is None:  # time exit
            outcome_r = side * (cl[exit_i] - entry) / risk
        outs.append({
            "entry_ts": ts[i],
            "side": side,
            "entry_price": entry,
            "tp_price": tp,
            "sl_price": sl,
            "risk_units": risk,
            "exit_index": exit_i,
            "bracket_r": outcome_r,
            "cost_r": cost_usd / risk,
            "net_r": outcome_r - cost_usd / risk,
            "rr": abs(tp - entry) / risk,
            "year": yr[i],
        })
    return pd.DataFrame(outs)


if __name__ == "__main__":
    from research.harness.causal_sim import headline, print_headline, gate

    print("Loading XAU data …")
    m1, m5, m15 = load_data()
    print(f"  m5={len(m5)}  m15={len(m15)}")

    configs = [
        dict(swing_k=3, require_confluence=True,  require_hh=False, require_trend=False, min_rr=0.0, sides=(+1, -1)),
        dict(swing_k=3, require_confluence=True,  require_hh=True,  require_trend=False, min_rr=0.0, sides=(+1, -1)),
        dict(swing_k=3, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=0.0, sides=(+1, -1)),
        dict(swing_k=3, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=2.0, sides=(+1, -1)),
        dict(swing_k=5, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=2.0, sides=(+1, -1)),
        dict(swing_k=5, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=3.0, sides=(+1, -1)),
        dict(swing_k=5, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=2.0, sides=(+1,)),
        dict(swing_k=5, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=2.0, sides=(-1,)),
        # confirmation-entry variants (guide: wait for CHoCH/confirmation candle)
        dict(swing_k=3, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=0.0, entry_mode="confirm", sides=(+1, -1)),
        dict(swing_k=5, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=2.0, entry_mode="confirm", sides=(+1, -1)),
        dict(swing_k=5, require_confluence=True,  require_hh=True,  require_trend=True,  min_rr=2.0, entry_mode="confirm", sides=(+1,)),
    ]
    print("\n=== ICT OTE @ 0.705 — XAUUSD, strict causal ===")
    for cfg in configs:
        sig = build_signals(m5, m15, **cfg)
        tr = simulate_price_bracket(sig, m5)
        rrstr = f"rr>={cfg['min_rr']:.0f}" if cfg['min_rr'] else "rr>=0"
        em = cfg.get("entry_mode", "limit")
        label = (f"k{cfg['swing_k']} hh={int(cfg['require_hh'])} "
                 f"trend={int(cfg['require_trend'])} {rrstr} {em[:4]} sides={cfg['sides']}")
        h = headline(tr)
        print_headline(label, h)
        if len(tr):
            print(f"      avg_rr={tr['rr'].mean():.2f}  avg_bracket_r={tr['bracket_r'].mean():+.3f}")
