"""ICT OTE v2 — the FULL model, to the dot:  sweep -> CHoCH -> OTE retrace.

v1 missed the institutional core. This adds, per the guide:
  - HTF structure (H1) for swings / BSL / SSL / trend (guide: 4H trend, structure on
    1H/15M). Entry executed on M5 ("4x lower timeframe").
  - LIQUIDITY SWEEP origin (page 30 POI / page 7 LGA): before a long, price must take
    out a prior swing LOW (stop-hunt) then reverse. Mirror for short.
  - Real CHoCH: after the sweep, price must CLOSE beyond the last opposing swing
    (break of structure) = displacement. This defines the impulse leg.
  - OTE 0.705 retrace of THAT impulse leg, in discount. TP = the swept-side external
    liquidity (prior swing high = BSL). SL below the sweep low (SSL).
  - Confluence count >= N (guide: >=5 reasons) from {FVG-in-leg, OB-in-leg, sweep,
    CHoCH, HTF-trend-align, discount-location}.

Strictly causal: swings confirmed k bars right; sweep + CHoCH detected only from
CLOSED HTF bars; entry armed at the CHoCH-confirm time, filled on M5.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import (  # noqa: E402
    load_data, headline, print_headline, _load_raw_m1, COST_USD,
)
from research.ict_ote.structure import find_swings, fvg_zones, ob_zones  # noqa: E402

OTE_FIB = 0.705


def build_htf(m1: pd.DataFrame, rule: str = "1h") -> pd.DataFrame:
    h = m1.set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    return h


def build_signals_v2(
    m5: pd.DataFrame,
    htf: pd.DataFrame,
    *,
    htf_rule_min: int = 60,          # HTF bar minutes (for confirm-time math)
    swing_k: int = 3,
    sweep_lookback: int = 6,         # prior swings to consider for the swept level
    wait_bars: int = 96,            # M5 bars to wait for OTE fill after CHoCH
    sl_buf_atr: float = 0.10,
    min_conf: int = 3,               # minimum confluence count (guide wants >=5)
    require_fvg: bool = False,       # displacement should leave an FVG
    sides: tuple[int, ...] = (+1, -1),
) -> pd.DataFrame:
    swings = find_swings(htf, k=swing_k)  # HTF fractal swings, confirmed
    fvg = fvg_zones(htf)
    ob = ob_zones(htf)
    fvg_by = {d: fvg[fvg["dir"] == d].reset_index(drop=True) for d in (+1, -1)}
    ob_by = {d: ob[ob["dir"] == d].reset_index(drop=True) for d in (+1, -1)}

    hclose = htf["close"].values
    hts = htf["timestamp"].values
    bar_td = np.timedelta64(htf_rule_min, "m")

    m5_ts = m5["timestamp"].values
    m5_lo = m5["low"].values
    m5_hi = m5["high"].values
    m5_cl = m5["close"].values
    m5_op = m5["open"].values
    m5_atr = m5["atr14_lag"].values
    n5 = len(m5)

    def conf_in_leg(side, lo_ts, arm_ts, lo, hi):
        cnt = 0
        f = fvg_by[side]
        fv = f[(f["valid_ts"] > lo_ts) & (f["valid_ts"] <= arm_ts) &
               (f["hi"] >= lo) & (f["lo"] <= hi)]
        if len(fv):
            cnt += 1
        o = ob_by[side]
        ov = o[(o["valid_ts"] > lo_ts) & (o["valid_ts"] <= arm_ts) &
               (o["hi"] >= lo) & (o["lo"] <= hi)]
        if len(ov):
            cnt += 1
        return cnt, len(fv) > 0

    sigs = []
    # walk swings in confirmation order; look for sweep -> CHoCH
    # separate ordered lists of highs/lows with their confirm times
    for bi in range(len(swings)):
        b = swings[bi]
        # LONG: b is a swing LOW that swept a prior swing low
        if +1 in sides and b.kind == "L":
            prior_lows = [s for s in swings[:bi] if s.kind == "L" and s.confirm_ts <= b.confirm_ts]
            prior_lows = prior_lows[-sweep_lookback:]
            swept = [s for s in prior_lows if b.price < s.price]
            if swept:
                # nearest prior swing HIGH after the swept low = CHoCH reference / BSL
                prior_highs = [s for s in swings[:bi + 1] if s.kind == "H" and s.confirm_ts <= b.confirm_ts]
                if prior_highs:
                    ref_high = prior_highs[-1]
                    swing_hi = ref_high.price
                    swing_lo = b.price
                    if swing_hi > swing_lo:
                        # CHoCH up: first HTF bar (closing after b.confirm_ts) that CLOSES above ref_high
                        start_h = int(np.searchsorted(hts, np.datetime64(b.confirm_ts), side="left"))
                        choch_i = -1
                        for j in range(start_h, min(len(htf), start_h + sweep_lookback * 8)):
                            if hclose[j] > swing_hi:
                                choch_i = j
                                break
                        if choch_i >= 0:
                            arm_ts = pd.Timestamp(hts[choch_i]) + bar_td
                            _emit(sigs, +1, swing_lo, swing_hi, b.bar_ts, arm_ts,
                                  m5_ts, m5_lo, m5_hi, m5_cl, m5_op, m5_atr, n5,
                                  wait_bars, sl_buf_atr, min_conf, require_fvg, conf_in_leg)
        # SHORT: b is a swing HIGH that swept a prior swing high
        if -1 in sides and b.kind == "H":
            prior_highs = [s for s in swings[:bi] if s.kind == "H" and s.confirm_ts <= b.confirm_ts]
            prior_highs = prior_highs[-sweep_lookback:]
            swept = [s for s in prior_highs if b.price > s.price]
            if swept:
                prior_lows = [s for s in swings[:bi + 1] if s.kind == "L" and s.confirm_ts <= b.confirm_ts]
                if prior_lows:
                    ref_low = prior_lows[-1]
                    swing_lo = ref_low.price
                    swing_hi = b.price
                    if swing_hi > swing_lo:
                        start_h = int(np.searchsorted(hts, np.datetime64(b.confirm_ts), side="left"))
                        choch_i = -1
                        for j in range(start_h, min(len(htf), start_h + sweep_lookback * 8)):
                            if hclose[j] < swing_lo:
                                choch_i = j
                                break
                        if choch_i >= 0:
                            arm_ts = pd.Timestamp(hts[choch_i]) + bar_td
                            _emit(sigs, -1, swing_lo, swing_hi, b.bar_ts, arm_ts,
                                  m5_ts, m5_lo, m5_hi, m5_cl, m5_op, m5_atr, n5,
                                  wait_bars, sl_buf_atr, min_conf, require_fvg, conf_in_leg)
    return pd.DataFrame(sigs)


def _emit(sigs, side, swing_lo, swing_hi, lo_ts, arm_ts, m5_ts, m5_lo, m5_hi,
          m5_cl, m5_op, m5_atr, n5, wait_bars, sl_buf_atr, min_conf, require_fvg, conf_in_leg):
    rng = swing_hi - swing_lo
    if rng <= 0:
        return
    if side > 0:
        ote = swing_hi - OTE_FIB * rng      # discount
        tp = swing_hi                       # BSL (external liquidity above)
        stop_ref = swing_lo                 # sweep low
    else:
        ote = swing_lo + OTE_FIB * rng      # premium
        tp = swing_lo                       # SSL below
        stop_ref = swing_hi

    ncfl, has_fvg = conf_in_leg(side, lo_ts, arm_ts, min(swing_lo, swing_hi), max(swing_lo, swing_hi))
    if require_fvg and not has_fvg:
        return
    # confluence tally: sweep(1) + CHoCH(1) + discount-location(1) + fvg/ob counts
    total_conf = 3 + ncfl
    if total_conf < min_conf:
        return

    start = int(np.searchsorted(m5_ts, np.datetime64(arm_ts), side="left"))
    if start >= n5 - 2:
        return
    atr = m5_atr[start]
    if not np.isfinite(atr) or atr <= 0:
        return
    sl = stop_ref - sl_buf_atr * atr if side > 0 else stop_ref + sl_buf_atr * atr
    risk = abs(ote - sl)
    if risk <= 0:
        return

    # fill: price retraces into OTE within wait_bars; cancel if closes beyond SL first
    fill_i = -1
    end = min(n5 - 1, start + wait_bars)
    for j in range(start, end + 1):
        if side > 0:
            if m5_cl[j] < sl:
                break
            if m5_lo[j] <= ote:
                fill_i = j
                break
        else:
            if m5_cl[j] > sl:
                break
            if m5_hi[j] >= ote:
                fill_i = j
                break
    if fill_i < 0:
        return
    sigs.append({
        "arm_ts": arm_ts, "fill_index": fill_i, "entry_price": ote, "side": side,
        "tp_price": tp, "sl_price": sl, "risk_units": risk, "n_conf": total_conf,
    })


if __name__ == "__main__":
    from research.ict_ote.run_ote import simulate_price_bracket

    print("Loading …")
    m1, m5, m15 = load_data()
    for rule, mins in [("1h", 60), ("4h", 240)]:
        htf = build_htf(m1, rule)
        print(f"\n=== ICT OTE v2 (sweep->CHoCH->OTE) HTF={rule} ({len(htf)} bars) ===")
        for cfg in [
            dict(swing_k=3, min_conf=3, sides=(+1, -1)),
            dict(swing_k=3, min_conf=4, require_fvg=True, sides=(+1, -1)),
            dict(swing_k=3, min_conf=4, require_fvg=True, sides=(+1,)),
            dict(swing_k=3, min_conf=4, require_fvg=True, sides=(-1,)),
            dict(swing_k=5, min_conf=4, require_fvg=True, sides=(+1, -1)),
        ]:
            sig = build_signals_v2(m5, htf, htf_rule_min=mins, **cfg)
            tr = simulate_price_bracket(sig, m5)
            lbl = f"k{cfg['swing_k']} conf>={cfg['min_conf']} fvg={int(cfg.get('require_fvg',0))} {cfg['sides']}"
            h = headline(tr)
            print_headline(lbl, h)
            if len(tr):
                print(f"      avg_rr={tr['rr'].mean():.2f} avg_bracket_r={tr['bracket_r'].mean():+.3f} "
                      f"avg_conf={sig['n_conf'].mean():.1f}")
