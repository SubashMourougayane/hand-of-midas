#!/usr/bin/env python3
"""Test the ICT-OTE hypothesis on REAL fib_v2 trades WITHOUT re-running:
reconstruct each entry's retracement depth from (entry, sl, tp) and split PF by depth.

A+D enters anywhere in 0.382..0.786 retrace. ICT OTE = deep 0.62..0.79 zone.
If deep entries have higher PF than shallow, gating to OTE cuts losers.

Reconstruction (long): sl=L-0.02*diff, tp=H+1.618*diff, diff=H-L
  => diff=(tp-sl)/2.638 ; H=tp-1.618*diff ; L=sl+0.02*diff
  depth = (H-entry)/diff   (0=no retrace @H, 1=full @L). Zone => 0.382..0.786.
Short mirror. Fully causal: depth known at entry. Splits net_r by depth bucket.
"""
from __future__ import annotations
import glob
import numpy as np
import pandas as pd

SL_BUF, EXT = 0.02, 1.618
DENOM = 1.0 + EXT + SL_BUF  # 2.638


def depth_of(row):
    tp, sl, e, side = row["tp_price"], row["stop_price"], row["entry_price"], row["side"]
    diff = abs(tp - sl) / DENOM
    if diff <= 0:
        return np.nan
    if side > 0:
        H = tp - EXT * diff
        return (H - e) / diff
    else:
        L = sl - SL_BUF * diff  # short: sl = H + buf*diff ... recompute
        H = sl - SL_BUF * diff
        # short: entry retrace from L upward; depth = (entry - L)/diff
        L = tp + EXT * diff
        return (e - L) / diff


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else float("inf")


def stats(d, label):
    if len(d) == 0:
        print(f"  {label:<26s} EMPTY"); return
    r = d["net_r"].values
    ys = d.groupby("year")["net_r"].sum(); pos = int((ys > 0).sum()); tot = d["year"].nunique()
    print(f"  {label:<26s} n={len(d):>5d} netR={r.sum():>+8.1f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% avgR={r.mean():>+5.3f} posY={pos:>2d}/{tot}")


def main():
    files = sorted(glob.glob("research/fib_retrace/fib_v2_oanda*ensemble*trades.parquet"))
    print("=== ICT-OTE DEPTH SPLIT on real fib_v2 trades ===\n")
    for f in files:
        d = pd.read_parquet(f)
        d = d.dropna(subset=["entry_price", "stop_price", "tp_price"]).copy()
        d["depth"] = d.apply(depth_of, axis=1)
        d = d[(d["depth"] > 0.30) & (d["depth"] < 0.85)].copy()  # sane zone
        print(f"### {f.split('/')[-1]}  ({len(d)} trades)")
        stats(d, "ALL (0.382-0.786)")
        # depth buckets
        for lo, hi in [(0.382, 0.5), (0.5, 0.62), (0.62, 0.705), (0.705, 0.786)]:
            stats(d[(d["depth"] >= lo) & (d["depth"] < hi)], f"depth {lo:.3f}-{hi:.3f}")
        # OTE gate (deep >= 0.62) vs shallow
        stats(d[d["depth"] >= 0.62], "OTE (>=0.62)")
        stats(d[d["depth"] < 0.62], "shallow (<0.62)")
        # monotonic threshold sweep
        print("  -- shallow-bound sweep (keep depth >= X) --")
        for X in (0.382, 0.45, 0.5, 0.55, 0.62, 0.705):
            sub = d[d["depth"] >= X]
            if len(sub) > 30:
                r = sub["net_r"].values
                ys = sub.groupby("year")["net_r"].sum(); pos = int((ys > 0).sum())
                print(f"     >= {X:.3f}  n={len(sub):>5d} PF={pf(r):>5.2f} netR={r.sum():>+7.1f} "
                      f"avgR={r.mean():>+5.3f} posY={pos}/{sub['year'].nunique()}")
        print()


if __name__ == "__main__":
    main()
