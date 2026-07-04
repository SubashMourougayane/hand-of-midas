"""ICT AM-Session Sweep → MSS → FVG entry, causal, on BTC M5.

Literal port of the described checklist (strict causality, no look-ahead):
  1. TIME FILTER: NY 09:30–11:30 EST window only.
  2. LIQUIDITY SWEEP: price pushes past the Asian-session range hi/lo
     (Asian range = 20:00–00:00 EST prior, i.e. that day's overnight range,
     FROZEN before the AM window opens → causal).
  3. JUDAS SWING: that push is the fake move (we don't trade the sweep itself).
  4. MSS (Market Structure Shift): price sharply reverses and CLOSES past a
     local 5-bar swing (prior, shift(1).rolling(5)) in the opposite direction.
  5. ENTRY: on the pullback into the FVG left by the MSS displacement.
     - Bearish setup (swept ASIAN HIGH, then MSS down): short when price
       pulls back UP into the bearish FVG (3-bar gap from the down-move).
     - Bullish mirror (swept ASIAN LOW, then MSS up).
  6. SL = sweep extreme ± 0.25 ATR ; TP = R multiple.

Everything lagged: Asian range frozen pre-window; MSS swing from shift(1);
FVG confirmed on closed bars; entry at NEXT M5 open.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.btc_sweep.sweep_all_families import frame, simulate, headline

RNG = np.random.default_rng(20260704)


def build_m5():
    b = frame("5min")
    b["est"] = b["timestamp"].dt.tz_convert("America/New_York")
    b["est_hr"] = b["est"].dt.hour
    b["est_min"] = b["est"].dt.minute
    b["est_date"] = b["est"].dt.date.astype(str)
    return b


def asian_range(b):
    """Asian/overnight range per EST date = 20:00(prev)–02:00 EST hi/lo.
    Attach to each bar the range of the SAME est_date's overnight block, which
    closes 02:00 EST — well before the 09:30 AM window → causal for AM trades."""
    asia = b[(b["est_hr"] >= 20) | (b["est_hr"] < 2)].copy()
    # bucket overnight into the date it LEADS INTO (the following morning)
    asia["lead_date"] = (asia["est"] + pd.Timedelta(hours=6)).dt.date.astype(str)
    ar = asia.groupby("lead_date").agg(ah=("high", "max"), al=("low", "min"))
    return b["est_date"].map(ar["ah"]).values, b["est_date"].map(ar["al"]).values


def gen_ict_am(b, *, side, atr_sl=0.5, tp=2.0, win=(9, 30, 11, 30)):
    ah, al = asian_range(b)
    h, l, o, c = b["high"].values, b["low"].values, b["open"].values, b["close"].values
    atr = b["atr_lag"].values
    hr, mn = b["est_hr"].values, b["est_min"].values
    in_win = ((hr > win[0]) | ((hr == win[0]) & (mn >= win[1]))) & ((hr < win[2]) | ((hr == win[2]) & (mn <= win[3])))
    # local 5-bar swing (prior) for MSS
    sw_lo = pd.Series(l).shift(1).rolling(5).min().shift(1).values
    sw_hi = pd.Series(h).shift(1).rolling(5).min().shift(1).values
    sw_hi = pd.Series(h).shift(1).rolling(5).max().shift(1).values
    # sweep flags on the PRIOR bar (Judas already happened), MSS confirmed by close
    ph, pl, pc = pd.Series(h).shift(1).values, pd.Series(l).shift(1).values, pd.Series(c).shift(1).values
    # 3-bar FVG (i-3,i-2,i-1)
    b1h, b1l = pd.Series(h).shift(3).values, pd.Series(l).shift(3).values
    b3h, b3l = pd.Series(h).shift(1).values, pd.Series(l).shift(1).values
    if side < 0:
        # swept ASIAN HIGH (prior bar high > asian high), MSS down (prior close < swing low),
        # bearish FVG present, enter short at open pulling back up into gap
        swept = ph > ah
        mss = pc < sw_lo
        bear_fvg = b1l > b3h
        near = o >= b3h  # pulling back up into the gap top
        sig = in_win & swept & mss & bear_fvg & near & (atr > 0) & ~np.isnan(ah)
        risk = (b["high"].shift(1).rolling(3).max().shift(1).values - o) + atr_sl * atr
        risk = np.where(risk > 0, risk, atr_sl * atr)
    else:
        swept = pl < al
        mss = pc > sw_hi
        bull_fvg = b1h < b3l
        near = o <= b3l
        sig = in_win & swept & mss & bull_fvg & near & (atr > 0) & ~np.isnan(al)
        risk = (o - b["low"].shift(1).rolling(3).min().shift(1).values) + atr_sl * atr
        risk = np.where(risk > 0, risk, atr_sl * atr)
    idx = np.where(np.nan_to_num(sig))[0]
    # cooldown: 1 setup per day per side
    if len(idx):
        keep = []; last_date = None
        for i in idx:
            d = b["est_date"].values[i]
            if d != last_date:
                keep.append(i); last_date = d
        idx = np.array(keep)
    return pd.DataFrame({"entry_index": idx, "side": side, "risk_units": risk[idx]})


def run():
    b = build_m5()
    print("█"*70)
    print("  ICT AM-SESSION: Asian-sweep → MSS → FVG entry · BTC M5 · NY 09:30-11:30 EST")
    print(f"  {len(b):,} M5 bars")
    print("█"*70)
    results = []
    for side, sl, tp in product([1, -1], [0.25, 0.5], [1.5, 2.0, 3.0]):
        sig = gen_ict_am(b, side=side, atr_sl=sl, tp=tp)
        if len(sig) < 20:
            print(f"  {'L' if side>0 else 'S'} sl{sl} tp{tp}: only {len(sig)} signals — skip")
            continue
        h = headline(simulate(sig, b, tp_mult=tp, horizon=288))
        posn = int(h["pos_years"].split("/")[0])
        star = "  ★" if (h["pf"] >= 1.3 and posn >= 6 and h["n"] >= 30) else ""
        print(f"  {'LONG ' if side>0 else 'SHORT'} sl{sl} tp{tp}: n={h['n']:>4d} /yr={h['trades_per_year']:>4.0f} "
              f"net={h['net']:>+7.1f}R PF={h['pf']:.2f} WR={h['wr']*100:.0f}% MAR={h['mar']:.2f} pos={h['pos_years']}{star}")
        results.append((side, sl, tp, h))
    # adversarial on any star
    stars = [(s, sl, tp, h) for s, sl, tp, h in results if h["pf"] >= 1.3 and int(h["pos_years"].split("/")[0]) >= 6 and h["n"] >= 30]
    if stars:
        print("\n═══ adversarial on flagged ═══")
        for side, sl, tp, h in stars:
            sig = gen_ict_am(b, side=side, atr_sl=sl, tp=tp)
            sd = sig.copy(); sd["entry_index"] += 1; sd = sd[sd["entry_index"] < len(b)-2]
            hd = headline(simulate(sd, b, tp_mult=tp, horizon=288))
            tr = simulate(sig, b, tp_mult=tp, horizon=288)
            r = tr["net_r"].values
            pn = np.mean([RNG.choice(r, len(r), replace=True).sum() <= 0 for _ in range(3000)]) if len(r) >= 10 else 1.0
            print(f"  {'L' if side>0 else 'S'} sl{sl} tp{tp}: +1delay PF {hd['pf']:.2f} (base {h['pf']:.2f}) | bootstrap P(neg) {pn:.3f}")
    else:
        print("\n  (no config flagged — honest)")


if __name__ == "__main__":
    run()
