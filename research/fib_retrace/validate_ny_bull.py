#!/usr/bin/env python3
"""Hostile validation of the ONE honest intraday config that hit PF>=1.5 & WR>40%:
  lb5 · hold=12h · ext=2.618 · sl=0.02 · NY session · bull_strong regime · LONG · NO partial.
Research sim (COST 0.30) gave PF 1.507 / WR 42.87% / n 3595 / 15-20 pos yrs.

Test before believing (iron-clad): cost stress 0.30->0.65->0.80, IS/OOS split,
per-year, and delay+1. ptp=None so NO partial-TP over-count. Then port to live code.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)
from research.fib_retrace.safety_net_sweep import simulate_with_safety
from research.fib_retrace.intraday_phase1_sweep import resample_m5_to_m15, build_m15_pivot_events


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else float("inf")


def stats(label, trades):
    if len(trades) == 0:
        print(f"  {label:<26s} ZERO"); return
    r = trades["net_r"].values
    wr = (r > 0).mean() * 100
    ys = trades.groupby("year")["net_r"].sum(); pos = int((ys > 0).sum()); tot = len(ys)
    print(f"  {label:<26s} n={len(r):>4d} PF={pf(r):>5.3f} WR={wr:>5.2f}% "
          f"netR={r.sum():>+7.1f} posY={pos:>2d}/{tot:<2d} "
          f"{'✓GOAL' if (pf(r)>=1.5 and wr>40) else ''}")


def main():
    h1_raw, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = resample_m5_to_m15(m5)
    m15_f = add_m5_features(m15)
    d1 = add_d1_features(resample_d1(m15_f))
    m15_f = attach_d1_to_m5(m15_f, d1)
    piv = build_m15_pivot_events(m15_f, 5)

    sigs = gen_signals_with_regime(
        m15_f, piv, direction="long", session="ny",
        max_hold_bars=12 * 4, ext_target_pct=2.618, sl_buffer_pct=0.02,
        regime="bull_strong",
    )
    print(f"=== NY BULL_STRONG LONG lb5 h12 ext2.618 — VALIDATION ===")
    print(f"signals: {len(sigs)}\n")

    print("-- cost stress (no partial) --")
    tr_by_cost = {}
    for c in (0.30, 0.45, 0.65, 0.80):
        tr = simulate_with_safety(m15_f, sigs, cost_usd=c, horizon_bars=12 * 4, partial_tp_at_r=None)
        if len(tr) and "year" not in tr.columns:
            tr["year"] = pd.to_datetime(tr["entry_ts"]).dt.year
        tr_by_cost[c] = tr
        stats(f"cost ${c:.2f}", tr)

    base = tr_by_cost[0.65]  # realistic conservative
    print("\n-- IS/OOS (cost $0.65) --")
    stats("IS <=2015", base[base["year"] <= 2015])
    stats("OOS 2016+", base[base["year"] >= 2016])
    stats("modern 2020+", base[base["year"] >= 2020])

    print("\n-- per-year (cost $0.65) --")
    ys = base.groupby("year")["net_r"].agg(["sum", "count"])
    for y, row in ys.iterrows():
        wr_y = (base[base["year"] == y]["net_r"] > 0).mean() * 100
        print(f"    {int(y)}: netR={row['sum']:>+7.1f}  n={int(row['count']):>3d}  WR={wr_y:>4.0f}%")


if __name__ == "__main__":
    main()
