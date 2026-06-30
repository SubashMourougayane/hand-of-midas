"""Deep audit of M15 OB retest TP=3R candidate."""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

t = pd.read_parquet("/Users/subash/SUBASH/GoldDigger/research/order_block/m15_retest_tp3.0_trades.parquet")
print(f"trades: {len(t)}")
r = t["net_r"].astype(float).values

# 1) Bootstrap
np.random.seed(29062026)
nets = []
dds = []
n = len(r)
for _ in range(5000):
    s = np.random.choice(r, size=n, replace=True)
    eq = s.cumsum()
    nets.append(eq[-1])
    dds.append((eq - np.maximum.accumulate(eq)).min())
nets = np.array(nets); dds = np.array(dds)
print(f"Bootstrap (5000):")
print(f"  net p01={np.percentile(nets,1):+.1f} p05={np.percentile(nets,5):+.1f} p50={np.percentile(nets,50):+.1f} p95={np.percentile(nets,95):+.1f}")
print(f"  dd  p01={np.percentile(dds,1):.1f} p05={np.percentile(dds,5):.1f} p50={np.percentile(dds,50):.1f}")
print(f"  P(net<0) = {(nets<0).mean()*100:.4f}%")
print(f"  P(dd<-200R) = {(dds<-200).mean()*100:.2f}%")

# 2) Permutation MC (preserves net by definition)
np.random.seed(29062026)
dds_p = []
for _ in range(5000):
    eq = np.random.permutation(r).cumsum()
    dds_p.append((eq - np.maximum.accumulate(eq)).min())
dds_p = np.array(dds_p)
print(f"Permutation MC (5000):")
print(f"  dd p01={np.percentile(dds_p,1):.1f} p05={np.percentile(dds_p,5):.1f} p50={np.percentile(dds_p,50):.1f}")
observed_dd = -72.12
print(f"  Observed dd = {observed_dd:.1f}R, percentile = {(dds_p < observed_dd).mean()*100:.2f}%")

# 3) Walk-forward IS/OOS
t["entry_ts"] = pd.to_datetime(t["entry_ts"], utc=True)
t = t.sort_values("entry_ts")
splits = [
    ("2019-2021", "2022-2026"),
    ("2019-2022", "2023-2026"),
    ("2019-2023", "2024-2026"),
]
print()
print("Walk-forward IS/OOS:")
for is_lbl, oos_lbl in splits:
    cut = pd.Timestamp(f"{oos_lbl.split('-')[0]}-01-01", tz="UTC")
    tr = t[t["entry_ts"] < cut]
    oo = t[t["entry_ts"] >= cut]
    for lbl, g in [("IS  ", tr), ("OOS ", oo)]:
        if len(g) == 0: continue
        rr = g["net_r"]
        wins = rr[rr > 0].sum(); losses = -rr[rr < 0].sum()
        pf = wins / losses if losses > 0 else float("inf")
        yrs = max(0.01, (g["entry_ts"].max() - g["entry_ts"].min()).total_seconds() / (365.25*86400))
        ry = rr.sum() / yrs
        eq = rr.cumsum().values
        dd = (eq - np.maximum.accumulate(eq)).min()
        mar = ry / abs(dd) if dd != 0 else 0
        y = g.assign(_y=g["entry_ts"].dt.year).groupby("_y")["net_r"].sum()
        pos = int((y > 0).sum())
        print(f"  {is_lbl}/{oos_lbl} {lbl}: n={len(rr)} net={rr.sum():+.1f}R /yr={ry:+.1f}R PF={pf:.2f} DD={dd:+.1f} MAR={mar:+.2f} pos={pos}/{len(y)}")

# 4) Cost stress
print()
print("Cost stress:")
yrs = max(0.01, (t["entry_ts"].max() - t["entry_ts"].min()).total_seconds() / (365.25*86400))
for extra in [0.000, 0.025, 0.050, 0.075, 0.100, 0.150, 0.200, 0.300]:
    rr = t["net_r"] - extra
    eq = rr.cumsum().values
    dd = (eq - np.maximum.accumulate(eq)).min()
    wins = rr[rr > 0].sum(); losses = -rr[rr < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    ry = rr.sum() / yrs
    y = t.assign(_y=t["entry_ts"].dt.year, _rr=rr).groupby("_y")["_rr"].sum()
    pos = int((y > 0).sum())
    print(f"  +{extra:.3f}R: net={rr.sum():>+7.1f}R /yr={ry:>+6.1f} PF={pf:.2f} DD={dd:+6.1f} pos={pos}/{len(y)}")

# 5) Direction breakdown
print()
print("Direction split:")
for s in [1, -1]:
    g = t[t["side"] == s]
    rr = g["net_r"]
    if len(rr) == 0: continue
    wins = rr[rr > 0].sum(); losses = -rr[rr < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    yrs_g = max(0.01, (g["entry_ts"].max() - g["entry_ts"].min()).total_seconds() / (365.25*86400))
    eq = rr.cumsum().values
    dd = (eq - np.maximum.accumulate(eq)).min()
    print(f"  side={s:>2d}: n={len(rr):>5d} net={rr.sum():>+7.1f}R /yr={rr.sum()/yrs_g:>+6.1f} PF={pf:.2f} DD={dd:+6.1f}")
