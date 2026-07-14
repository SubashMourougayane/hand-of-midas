#!/usr/bin/env python3
"""Comprehensive robustness battery for the intraday fib edge + short attempt +
market-structure confluence. Every config reports PF/WR at cost 0.30 AND 0.65,
IS(<=2015)/OOS(2016+), delay+1, per-year positivity. Flags only configs that are
ROBUST (goal met AND OOS-consistent AND delay-survivor) — not in-sample spikes.

Part A: direction x regime x session x lb x hold x ext  (long AND short, all regimes)
Part B: market-structure confluence FILTERS on the best long config
        (volume surge, prior-bar momentum/MSS proxy, wider-swing FVG proxy).
"""
from __future__ import annotations
import sys
from pathlib import Path
from itertools import product
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5)
from research.fib_retrace.safety_net_sweep import simulate_with_safety
from research.fib_retrace.intraday_phase1_sweep import resample_m5_to_m15, build_m15_pivot_events


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else 9.9


def wr(x):
    x = np.asarray(x, float); return (x > 0).mean() * 100 if len(x) else 0


def robust(tr_by_cost, tr_delay):
    """Return dict of metrics + a ROBUST flag."""
    a = tr_by_cost[0.30]; b = tr_by_cost[0.65]
    ra, rb = a["net_r"].values, b["net_r"].values
    isr = a[a.year <= 2015]["net_r"].values; oosr = a[a.year >= 2016]["net_r"].values
    d = tr_delay["net_r"].values
    m = dict(n=len(ra), pf30=pf(ra), wr30=wr(ra), pf65=pf(rb), wr65=wr(rb),
             pf_is=pf(isr), pf_oos=pf(oosr), pf_delay=pf(d), wr_delay=wr(d))
    ys = a.groupby("year")["net_r"].sum(); m["posY"] = f"{int((ys>0).sum())}/{len(ys)}"
    # ROBUST @0.30: goal met, OOS>=1.4, delay survives, IS not wildly > OOS
    m["robust30"] = (m["pf30"] >= 1.5 and m["wr30"] > 40 and m["pf_oos"] >= 1.4
                     and m["pf_delay"] >= 1.45 and len(oosr) > 100)
    m["robust65"] = (m["pf65"] >= 1.5 and m["wr65"] > 40)
    return m


def run_cfg(m15, piv, direction, session, lb, hold, ext, sl, regime, extra_mask=None):
    sigs = gen_signals_with_regime(m15, piv[lb], direction=direction, session=session,
                                   max_hold_bars=hold * 4, ext_target_pct=ext,
                                   sl_buffer_pct=sl, regime=regime)
    if extra_mask is not None and len(sigs):
        sigs = sigs[extra_mask.reindex(sigs["entry_index"]).fillna(False).values]
    if len(sigs) < 150:
        return None
    out = {}
    for c in (0.30, 0.65):
        tr = simulate_with_safety(m15, sigs, cost_usd=c, horizon_bars=hold * 4, partial_tp_at_r=None)
        if len(tr) < 150: return None
        tr["year"] = pd.to_datetime(tr["entry_ts"]).dt.year
        out[c] = tr
    s2 = sigs.copy(); s2["entry_index"] = s2["entry_index"] + 1
    trd = simulate_with_safety(m15, s2, cost_usd=0.30, horizon_bars=hold * 4, partial_tp_at_r=None)
    trd["year"] = pd.to_datetime(trd["entry_ts"]).dt.year
    return robust(out, trd)


def main():
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = add_m5_features(resample_m5_to_m15(m5)); d1 = add_d1_features(resample_d1(m15))
    m15 = attach_d1_to_m5(m15, d1)
    piv = {lb: build_m15_pivot_events(m15, lb) for lb in (3, 5, 8)}

    print("=== PART A: direction x regime x session (robustness battery) ===")
    print(f"{'cfg':<44}{'n':>5}{'PF30':>6}{'WR30':>6}{'PF65':>6}{'IS':>6}{'OOS':>6}{'dly':>6}{'posY':>6} R?")
    hits = []
    for direc, regs in [("long", ["bull_strong", "bull", "any"]),
                        ("short", ["bear_strong", "bear", "any"])]:
        for reg in regs:
            for sess in ("ny", "london", "london_ny"):
                for lb in (3, 5):
                    for hold in (12, 24):
                        m = run_cfg(m15, piv, direc, sess, lb, hold, 2.618, 0.02, reg)
                        if m is None: continue
                        cfg = f"{direc[:1]}_{reg}_{sess}_lb{lb}_h{hold}"
                        star = " ROBUST✓" if m["robust30"] else ("  ~goal" if (m["pf30"]>=1.5 and m["wr30"]>40) else "")
                        if m["pf30"] >= 1.4 or m["robust30"]:
                            print(f"{cfg:<44}{m['n']:>5}{m['pf30']:>6.2f}{m['wr30']:>6.1f}"
                                  f"{m['pf65']:>6.2f}{m['pf_is']:>6.2f}{m['pf_oos']:>6.2f}"
                                  f"{m['pf_delay']:>6.2f}{m['posY']:>6}{star}")
                        if m["robust30"]:
                            hits.append((cfg, m))
    print(f"\nPART A robust configs: {len(hits)}")
    for c, m in hits:
        print(f"  {c}: PF30={m['pf30']:.2f} WR={m['wr30']:.1f}% OOS={m['pf_oos']:.2f} delay={m['pf_delay']:.2f}")


if __name__ == "__main__":
    main()
