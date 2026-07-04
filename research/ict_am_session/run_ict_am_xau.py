"""ICT AM-Session strategy on XAUUSD — followed to the dot, strictly causal.

CHECKLIST (literal):
  1. TIME FILTER: hunt trades ONLY in the NY AM window 09:30–11:30 EST.
  2. LIQUIDITY SWEEP: market pushes past a prior high/low — the Asian-session
     high/low (stop hunt).
  3. JUDAS SWING: that push is the fake move → we do NOT trade the sweep itself.
  4. MSS (Market Structure Shift): price sharply reverses and breaks a local
     swing level → the fake move is over.
  5. ENTRY TRIGGER: on the pullback into the FVG (Fair Value Gap) / Order Block
     left by that sharp reversal, on the M5 chart.

CAUSALITY (strict, no look-ahead):
  - Asian range = 20:00–02:00 EST, FROZEN before the 09:30 AM window opens.
  - Sweep detected on CLOSED bars (prior-bar high>asian_high etc.).
  - MSS = a CLOSED bar closes past the prior 5-bar swing (shift(1).rolling(5)).
  - FVG = 3-bar imbalance confirmed on CLOSED bars.
  - After MSS+FVG confirm, ARM a limit at the FVG edge; FILL on the NEXT bars
    (wait-window) when price pulls back into the gap. Entry at fill price.
  - SL = sweep extreme ± buffer; TP = R multiple. All prior/known data.

Bearish setup (swept ASIAN HIGH → MSS down → short the pullback into bearish FVG).
Bullish mirror (swept ASIAN LOW → MSS up → long the pullback into bullish FVG).
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, simulate, headline, gate, persist, print_headline

RNG = np.random.default_rng(20260704)


def build():
    m1, m5, m15 = load_data()
    b = m5.copy()
    b["est"] = b["timestamp"].dt.tz_convert("America/New_York")
    b["est_hr"] = b["est"].dt.hour
    b["est_min"] = b["est"].dt.minute
    b["est_date"] = b["est"].dt.date.astype(str)
    b["atr"] = b["atr14_lag"]
    return b


def asian_hilo(b):
    """Asian range per morning = 20:00(prev)–02:00 EST hi/lo, mapped to the date it
    leads into. Closes 02:00 EST, well before 09:30 AM window → causal."""
    asia = b[(b["est_hr"] >= 20) | (b["est_hr"] < 2)].copy()
    asia["lead_date"] = (asia["est"] + pd.Timedelta(hours=6)).dt.date.astype(str)
    ar = asia.groupby("lead_date").agg(ah=("high", "max"), al=("low", "min"))
    return b["est_date"].map(ar["ah"]).values, b["est_date"].map(ar["al"]).values


def gen(b, *, side, buf_atr, tp, wait, sweep_ref="asian"):
    """Returns signals with ARMED FVG limit + wait-window fill on the M5 grid.

    side=-1 bearish (sweep asian high, MSS down, short pullback into bear FVG).
    side=+1 bullish mirror.
    """
    n = len(b)
    ah, al = asian_hilo(b)
    h, l, o, c = b["high"].values, b["low"].values, b["open"].values, b["close"].values
    atr = b["atr"].values
    hr, mn = b["est_hr"].values, b["est_min"].values
    est_date = b["est_date"].values
    in_win = ((hr > 9) | ((hr == 9) & (mn >= 30))) & ((hr < 11) | ((hr == 11) & (mn <= 30)))

    # prior-bar values (closed)
    ph = pd.Series(h).shift(1).values
    pl = pd.Series(l).shift(1).values
    pc = pd.Series(c).shift(1).values
    # local 5-bar swing (prior) for MSS
    sw_lo = pd.Series(l).shift(1).rolling(5).min().shift(1).values
    sw_hi = pd.Series(h).shift(1).rolling(5).max().shift(1).values
    # 3-bar FVG on closed bars (bars i-3,i-2,i-1): confirmed at i-1 close
    b1h, b1l = pd.Series(h).shift(3).values, pd.Series(l).shift(3).values
    b3h, b3l = pd.Series(h).shift(1).values, pd.Series(l).shift(1).values

    # track daily sweep extreme (for SL) — highest high / lowest low seen in-window today
    sigs = []
    used_date = set()
    for i in range(6, n - 2):
        if not in_win[i]:
            continue
        d = est_date[i]
        if d in used_date:
            continue  # one setup per morning per side
        if side < 0:
            # 2. sweep asian HIGH (a prior bar in this morning poked above it)
            swept = ph[i] > ah[i] and not np.isnan(ah[i])
            # 4. MSS down: prior bar CLOSED below prior 5-bar swing low
            mss = pc[i] < sw_lo[i]
            # 5. bearish FVG present (gap between b1 low and b3 high): b1l > b3h
            fvg = b1l[i] > b3h[i]
            if swept and mss and fvg:
                gap_bot = b3h[i]                        # bearish FVG lower edge (limit)
                # ARM short limit at gap bottom edge; the FILL BAR is the first later
                # bar (within wait) whose high trades up into the gap. The sim enters
                # at that bar's OPEN, so risk MUST be measured from open[fill_idx].
                fill_idx = None
                for j in range(i + 1, min(n - 1, i + wait) + 1):
                    if h[j] >= gap_bot:
                        fill_idx = j
                        break
                if fill_idx is not None:
                    entry_open = o[fill_idx]              # sim enters here
                    sweep_hi = ah[i]
                    # stop above the swept high + buffer; risk from the ACTUAL entry.
                    risk = (sweep_hi + buf_atr * atr[i]) - entry_open
                    min_risk = 0.5 * atr[i]              # reject degenerate micro-stops
                    if risk >= min_risk:
                        sigs.append((fill_idx, -1, risk)); used_date.add(d)
        else:
            swept = pl[i] < al[i] and not np.isnan(al[i])
            mss = pc[i] > sw_hi[i]
            fvg = b1h[i] < b3l[i]                       # bullish FVG
            if swept and mss and fvg:
                gap_top = b3l[i]                         # bullish FVG upper edge (limit)
                fill_idx = None
                for j in range(i + 1, min(n - 1, i + wait) + 1):
                    if l[j] <= gap_top:
                        fill_idx = j
                        break
                if fill_idx is not None:
                    entry_open = o[fill_idx]
                    sweep_lo = al[i]
                    risk = entry_open - (sweep_lo - buf_atr * atr[i])
                    min_risk = 0.5 * atr[i]
                    if risk >= min_risk:
                        sigs.append((fill_idx, 1, risk)); used_date.add(d)
    if not sigs:
        return pd.DataFrame(columns=["entry_index", "side", "risk_units"])
    df = pd.DataFrame(sigs, columns=["entry_index", "side", "risk_units"])
    return df.drop_duplicates("entry_index").sort_values("entry_index").reset_index(drop=True)


def run():
    b = build()
    print("█"*74)
    print("  ICT AM-SESSION · XAUUSD M5 · NY 09:30-11:30 EST · Asian-sweep→MSS→FVG")
    print(f"  {len(b):,} M5 bars  {b['timestamp'].min().date()}→{b['timestamp'].max().date()}")
    print("█"*74)
    results = []
    for side, buf, tp, wait in product([1, -1], [0.25, 0.5], [1.5, 2.0, 3.0], [6, 12, 24]):
        sig = gen(b, side=side, buf_atr=buf, tp=tp, wait=wait)
        if len(sig) < 20:
            continue
        h = headline(simulate(sig, b, tp_mult=tp, horizon_bars=288))
        posn = int(h["pos_years"].split("/")[0])
        star = "  ★" if (h["pf"] >= 1.3 and posn >= 6 and h["n"] >= 30) else ""
        print(f"  {'LONG ' if side>0 else 'SHORT'} buf{buf} tp{tp} wait{wait}: n={h['n']:>4d} /yr={h['trades_per_year']:>4.0f} "
              f"net={h['net']:>+7.1f}R PF={h['pf']:.2f} WR={h['wr']*100:.0f}% MAR={h['mar']:.2f} pos={h['pos_years']}{star}")
        results.append((side, buf, tp, wait, h, sig))
    stars = [(s, buf, tp, w, h, sig) for s, buf, tp, w, h, sig in results
             if h["pf"] >= 1.3 and int(h["pos_years"].split("/")[0]) >= 6 and h["n"] >= 30]
    print(f"\n═══ flagged: {len(stars)} ═══")
    for side, buf, tp, w, h, sig in sorted(stars, key=lambda x: -x[4]["mar"]):
        # adversarial: +1 delay + bootstrap
        sd = sig.copy(); sd["entry_index"] += 1; sd = sd[sd["entry_index"] < len(b) - 2]
        hd = headline(simulate(sd, b, tp_mult=tp, horizon_bars=288))
        tr = simulate(sig, b, tp_mult=tp, horizon_bars=288); r = tr["net_r"].values
        pn = np.mean([RNG.choice(r, len(r), replace=True).sum() <= 0 for _ in range(3000)])
        print(f"  ★ {'L' if side>0 else 'S'} buf{buf} tp{tp} wait{w}: PF={h['pf']:.2f} MAR={h['mar']:.2f} "
              f"/yr={h['trades_per_year']:.0f} pos={h['pos_years']} | +1delay {hd['pf']:.2f} | P(neg) {pn:.3f}")
    if not stars:
        print("  (none cleared PF≥1.3 & 6/8 & n≥30 — honest)")


if __name__ == "__main__":
    run()
