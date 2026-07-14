#!/usr/bin/env python3
"""Focused intraday sweep at HONEST cost $0.65, no partial (no over-count), extended
targets. Goal: ANY config with PF>=1.5 AND WR>40% AND n>=200 AND OOS-positive?
Region: strong regimes + directional, ny/london/london_ny, lb {3,5,8}, hold {8,12,24},
ext {2.618, 3.0, 3.618, 4.236}, sl {0.02, 0.10}. Report goal-passers with IS/OOS.
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

COST = 0.65


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else 9.9


def main():
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = add_m5_features(resample_m5_to_m15(m5))
    d1 = add_d1_features(resample_d1(m15)); m15 = attach_d1_to_m5(m15, d1)
    piv = {lb: build_m15_pivot_events(m15, lb) for lb in (3, 5, 8)}

    grid = product((3, 5, 8), (8, 12, 24), (2.618, 3.0, 3.618, 4.236), (0.02, 0.10),
                   ("ny", "london", "london_ny"),
                   [("long", "bull_strong"), ("long", "bull"),
                    ("short", "bear_strong"), ("short", "bear")])
    print(f"=== FOCUSED SWEEP @ cost ${COST}, ptp=none ===")
    print(f"{'cfg':<48}{'n':>5}{'PF':>7}{'WR%':>7}{'posY':>7}{'OOSpf':>7}")
    passers = []
    for lb, hold, ext, sl, sess, (direc, reg) in grid:
        sigs = gen_signals_with_regime(m15, piv[lb], direction=direc, session=sess,
                                       max_hold_bars=hold * 4, ext_target_pct=ext,
                                       sl_buffer_pct=sl, regime=reg)
        if len(sigs) < 200:
            continue
        tr = simulate_with_safety(m15, sigs, cost_usd=COST, horizon_bars=hold * 4, partial_tp_at_r=None)
        if len(tr) < 200:
            continue
        tr["year"] = pd.to_datetime(tr["entry_ts"]).dt.year
        r = tr["net_r"].values; wr = (r > 0).mean() * 100; p = pf(r)
        ys = tr.groupby("year")["net_r"].sum(); posY = int((ys > 0).sum()); tot = len(ys)
        oos = tr[tr["year"] >= 2016]; oospf = pf(oos["net_r"].values) if len(oos) > 50 else 0
        cfg = f"lb{lb}_h{hold}_ext{ext}_sl{sl}_{sess}_{direc[:1]}_{reg}"
        if p >= 1.45 and wr > 39:
            flag = "  <== GOAL" if (p >= 1.5 and wr > 40 and oospf >= 1.4) else "  ~near"
            print(f"{cfg:<48}{len(tr):>5}{p:>7.3f}{wr:>7.2f}   {posY}/{tot}{oospf:>7.2f}{flag}")
            if p >= 1.5 and wr > 40:
                passers.append((cfg, len(tr), p, wr, posY, tot, oospf))
    print(f"\n{len(passers)} configs PF>=1.5 & WR>40% @ ${COST}")
    for c in sorted(passers, key=lambda x: -x[2]):
        print(f"  {c[0]:<48} n={c[1]} PF={c[2]:.3f} WR={c[3]:.1f}% posY={c[4]}/{c[5]} OOSpf={c[6]:.2f}")


if __name__ == "__main__":
    main()
