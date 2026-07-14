#!/usr/bin/env python3
"""B3 — Intraday VWAP mean-reversion on gold M5 (proper bar-level, intraday exit).

THESIS: the US session is choppy/flat (B1 proved intraday drift ~0). So price
stretched far from the session VWAP should snap back. Fade the stretch, target
VWAP, intraday exit. Distinct from the session-level gap-fade (which lost) — this
is a within-session reversion with a real exit/stop.

CAUSAL: VWAP + bands computed from bars closed BEFORE the entry bar (shift). Entry
at next bar open. Exit: target=VWAP, stop=k2*band, or session close (17:00 NY).
Cost applied. Optional 'declining volume' exhaustion filter (per the PDF spec).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
COST = 0.65
OPEN_HR, CLOSE_HR = 8, 17


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny_date"] = ny.dt.normalize(); m5["ny_hr"] = ny.dt.hour
    m5["year"] = ny.dt.year
    us = m5[(m5["ny_hr"] >= OPEN_HR) & (m5["ny_hr"] < CLOSE_HR)].copy()
    return us


def backtest(us, k_entry, k_stop, vol_filter, delay=0):
    rows = []
    for (d,), g in us.groupby(["ny_date"], sort=True):
        g = g.reset_index(drop=True)
        n = len(g)
        if n < 30: continue
        o = g["open"].values; h = g["high"].values; l = g["low"].values
        cl = g["close"].values; vol = g["volume"].values
        tp = (h + l + cl) / 3.0
        cum_v = np.cumsum(vol) + 1e-9
        cum_pv = np.cumsum(tp * vol)
        vwap = cum_pv / cum_v
        # rolling dispersion of price around vwap (session-to-date std of close-vwap)
        dev = cl - vwap
        band = pd.Series(dev).expanding(min_periods=6).std().values
        yr = g["year"].values
        for i in range(6, n - 1):
            b = band[i]
            if not np.isfinite(b) or b <= 0: continue
            # signal uses bar i (closed); entry at i+1 open
            stretch = (cl[i] - vwap[i]) / b
            if vol_filter and not (vol[i] < vol[i-1] < vol[i-2]):  # declining volume = exhaustion
                continue
            side = 0
            if stretch >= k_entry: side = -1   # stretched up -> short back to vwap
            elif stretch <= -k_entry: side = 1  # stretched down -> long
            if side == 0: continue
            ei = i + 1 + delay
            if ei >= n: continue
            ent = o[ei]
            target = vwap[i]                    # snap back to vwap (frozen at signal)
            risk = k_stop * b
            stop = ent - side * risk
            if risk <= 0: continue
            out_r = None
            for j in range(ei, n):
                if side > 0:
                    if l[j] <= stop: out_r = -1.0; break
                    if h[j] >= target: out_r = (target - ent) / risk; break
                else:
                    if h[j] >= stop: out_r = -1.0; break
                    if l[j] <= target: out_r = (ent - target) / risk; break
            if out_r is None:  # session close exit
                out_r = side * (cl[n-1] - ent) / risk
            rows.append((yr[ei], out_r - COST / risk))
    return pd.DataFrame(rows, columns=["year", "net"])


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, d):
    if len(d) == 0: print(f"  {name:<34s} ZERO"); return
    r = d["net"].values; ys = d.groupby("year")["net"].sum()
    pos = int((ys > 0).sum()); tot = d["year"].nunique()
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252 * 10)  # ~10 trades/session scale rough
    print(f"  {name:<34s} n={len(r):>5d} netR={r.sum():>+7.1f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d}")


def main():
    us = load()
    print("=== B3 INTRADAY VWAP REVERSION (gold M5) ===")
    print(f"US-session bars {len(us)}\n")
    print("-- no volume filter --")
    for ke in (1.5, 2.0, 2.5, 3.0):
        for ks in (0.5, 1.0):
            rep(f"entry {ke}std stop {ks}band", backtest(us, ke, ks, False))
    print("\n-- declining-volume exhaustion filter --")
    for ke in (2.0, 2.5, 3.0):
        rep(f"entry {ke}std stop1.0 volfilt", backtest(us, ke, 1.0, True))
    print("\n-- delay+1 robustness on best --")
    rep("entry 2.5 stop1.0 delay+1", backtest(us, 2.5, 1.0, False, delay=1))


if __name__ == "__main__":
    main()
