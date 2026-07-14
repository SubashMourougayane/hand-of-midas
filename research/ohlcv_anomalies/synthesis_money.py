#!/usr/bin/env python3
"""CAPSTONE — synthesize the OOS-surviving drift-capture edges into one deployable
gold overlay and quantify the actual compounded MONEY vs buy&hold.

Surviving pieces (all causal, OOS-positive on 20yr):
  - strong-months long (Sh 0.69, OOS 0.95, half the DD)
  - MA200 trend filter (DD reducer, same return)
  - overnight-concentration is inside the daily close-to-close capture already

Product: position in {0, base, full} by calendar+trend, VOL-TARGETED to a fixed
annualized vol, then compounded on a real account. Report Sharpe, MAR, maxDD,
CAGR, and $5k -> $X over 20yr, with leverage sensitivity. Honest ruin check.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
COST = 0.65


def load():
    g = pd.read_parquet(XAU_D1)
    ts = pd.to_datetime(g["timestamp"])
    g["date"] = (ts.dt.tz_localize(None) if ts.dt.tz is not None else ts).dt.normalize()
    g = g[["date", "close"]].sort_values("date").reset_index(drop=True)
    g["ret"] = g["close"].pct_change()
    g["lret"] = np.log(g["close"] / g["close"].shift(1))
    g["year"] = g["date"].dt.year
    g["month"] = g["date"].dt.month
    g["ma200"] = g["close"].rolling(200).mean()
    g["vol20"] = g["lret"].rolling(20).std()  # realized daily vol, causal
    return g.dropna().reset_index(drop=True)


def perf(name, dret, dates, ann_target=None, start=5000.0):
    """dret = daily simple strategy return (already net). Compound on $."""
    dret = np.asarray(dret, float)
    m = ~np.isnan(dret); dret = dret[m]; dts = np.asarray(dates)[m]
    yrs = (pd.Timestamp(dts[-1]) - pd.Timestamp(dts[0])).days / 365.25
    eq = start * np.cumprod(1 + dret)
    cagr = (eq[-1] / start) ** (1 / yrs) - 1
    peak = np.maximum.accumulate(eq); dd = (eq - peak) / peak
    maxdd = dd.min()
    sh = dret.mean() / (dret.std() + 1e-12) * np.sqrt(252)
    mar = cagr / abs(maxdd) if maxdd != 0 else 0
    print(f"  {name:<34s} Sh={sh:>+4.2f} CAGR={cagr*100:>+6.1f}% maxDD={maxdd*100:>+6.1f}% "
          f"MAR={mar:>+4.2f} ${start:,.0f}->${eq[-1]:,.0f}")
    return eq


def main():
    g = load()
    dates = g["date"].values
    ret = g["ret"].values                     # today's realized return
    # CAUSAL: signal decided at PRIOR close (shift 1) then earns today's ret. No peek.
    up = (g["close"] > g["ma200"]).shift(1).fillna(False).values.astype(bool)
    strong = g["month"].isin([1, 2, 7, 8, 11, 12]).values  # calendar known in advance
    vol = g["vol20"].shift(1).values          # lagged vol for targeting (causal)
    cost_daily = COST / g["close"].values
    print("=== CAPSTONE: SYNTHESIZED GOLD DRIFT-CAPTURE ===")
    print(f"days {len(g)}  {g['date'].min().date()}->{g['date'].max().date()}\n")

    print("-- benchmark --")
    perf("buy&hold", ret, dates)

    print("\n-- unlevered overlays (position 0/1, net cost on flips) --")
    def net(pos):
        pos = np.asarray(pos, float)
        turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
        return pos * ret - turn * cost_daily
    perf("strong-months long", net(strong.astype(float)), dates)
    perf("trend(MA200) long", net(up.astype(float)), dates)
    perf("strongM & trend", net((strong & up).astype(float)), dates)
    perf("strongM | trend (union)", net((strong | up).astype(float)), dates)

    print("\n-- VOL-TARGETED (scale position to target ann vol), levered --")
    base_sig = (strong | up).astype(float)   # be long when strong month OR uptrend
    for tgt in (0.10, 0.15, 0.20):
        lev = np.clip(tgt / (vol * np.sqrt(252) + 1e-9), 0, 4.0)  # cap 4x
        pos = base_sig * lev
        turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
        dret = pos * ret - turn * cost_daily
        perf(f"union vol-tgt {tgt*100:.0f}% (cap4x)", dret, dates)

    print("\n-- vol-targeted BUY&HOLD (leverage only, no timing) for comparison --")
    for tgt in (0.15, 0.20):
        lev = np.clip(tgt / (vol * np.sqrt(252) + 1e-9), 0, 4.0)
        dret = lev * ret - np.abs(np.diff(np.concatenate([[0.0], lev]))) * cost_daily
        perf(f"B&H vol-tgt {tgt*100:.0f}%", dret, dates)

    print("\nNOTE: leverage/vol-targeting is BETA amplification, not new alpha.")
    print("The timing overlay's value is DD reduction + OOS-stable Sharpe ~0.7, not magic.")


if __name__ == "__main__":
    main()
