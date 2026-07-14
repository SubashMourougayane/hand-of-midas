#!/usr/bin/env python3
"""MEGA fresh sweep — both directions, all regimes/sessions/lb/hold/target/sl/volume.
Goal: robust edges with 1-5 trades/DAY, long AND short. Every config scored at
cost 0.30 AND 0.65, IS(<=2015)/OOS(2016+), delay+1, trades/day. Robust = goal-met
AND OOS-consistent AND delay-survivor. Logs incrementally to CSV for monitoring.

Runs autonomously (AFK grind). ~thousands of configs.
"""
from __future__ import annotations
import sys, time
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

OUT = Path(__file__).parent / "mega_sweep_out"
OUT.mkdir(exist_ok=True)
CSV = OUT / "matrix.csv"
LOG = OUT / "sweep.log"

DIRECTIONS = ["long", "short"]
REGIMES = ["any", "bull", "bull_strong", "bear", "bear_strong"]
SESSIONS = ["all", "ny", "london", "london_ny"]
LBS = [3, 5, 8]
HOLDS = [4, 8, 12, 24]
EXTS = [1.618, 2.618, 3.618]
SLS = [0.02, 0.10]
VOLS = [None, 1.5]     # volume-surge multiple (None=off)

TRADING_DAYS_PER_YEAR = 252


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else 9.9


def log(m):
    with LOG.open("a") as f:
        f.write(f"[{pd.Timestamp.utcnow():%H:%M:%S}] {m}\n")


def main():
    LOG.write_text("");
    if CSV.exists(): CSV.unlink()
    log("loading data...")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = add_m5_features(resample_m5_to_m15(m5)); d1 = add_d1_features(resample_d1(m15))
    m15 = attach_d1_to_m5(m15, d1)
    piv = {lb: build_m15_pivot_events(m15, lb) for lb in LBS}
    V = m15["volume"].values; volavg = pd.Series(V).rolling(20).mean().shift(1).values
    span_days = (pd.to_datetime(m15["timestamp"].iloc[-1]) - pd.to_datetime(m15["timestamp"].iloc[0])).days
    span_years = span_days / 365.25

    grid = list(product(DIRECTIONS, REGIMES, SESSIONS, LBS, HOLDS, EXTS, SLS, VOLS))
    log(f"grid: {len(grid)} configs")
    rows = []
    t0 = time.time()
    first = True
    for i, (direc, reg, sess, lb, hold, ext, sl, vol) in enumerate(grid, 1):
        try:
            sigs = gen_signals_with_regime(m15, piv[lb], direction=direc, session=sess,
                                           max_hold_bars=hold * 4, ext_target_pct=ext,
                                           sl_buffer_pct=sl, regime=reg)
            if vol is not None and len(sigs):
                mask = (V > vol * volavg)
                sigs = sigs[mask[sigs["entry_index"].values]]
            if len(sigs) < 150:
                continue
            tr30 = simulate_with_safety(m15, sigs, cost_usd=0.30, horizon_bars=hold * 4, partial_tp_at_r=None)
            if len(tr30) < 150:
                continue
            tr30["year"] = pd.to_datetime(tr30["entry_ts"]).dt.year
            tr65 = simulate_with_safety(m15, sigs, cost_usd=0.65, horizon_bars=hold * 4, partial_tp_at_r=None)
            tr65["year"] = pd.to_datetime(tr65["entry_ts"]).dt.year
            s2 = sigs.copy(); s2["entry_index"] = s2["entry_index"] + 1
            trd = simulate_with_safety(m15, s2, cost_usd=0.30, horizon_bars=hold * 4, partial_tp_at_r=None)

            r30 = tr30["net_r"].values; r65 = tr65["net_r"].values
            isr = tr30[tr30.year <= 2015]["net_r"].values
            oosr = tr30[tr30.year >= 2016]["net_r"].values
            ys = tr30.groupby("year")["net_r"].sum()
            tpd = len(tr30) / (span_years * TRADING_DAYS_PER_YEAR)
            row = dict(direc=direc, reg=reg, sess=sess, lb=lb, hold=hold, ext=ext, sl=sl,
                       vol=vol if vol else 0, n=len(r30), tpd=round(tpd, 2),
                       pf30=round(pf(r30), 3), wr30=round((r30 > 0).mean() * 100, 1),
                       netR30=round(r30.sum(), 0),
                       pf65=round(pf(r65), 3), wr65=round((r65 > 0).mean() * 100, 1),
                       pf_is=round(pf(isr), 3), pf_oos=round(pf(oosr), 3),
                       pf_delay=round(pf(trd["net_r"].values), 3),
                       posY=f"{int((ys>0).sum())}/{len(ys)}")
            # robust: goal (PF>=1.5,WR>40) at 0.30, OOS>=1.4, delay>=1.45, 1-5 tpd
            row["ROBUST"] = int(row["pf30"] >= 1.5 and row["wr30"] > 40 and row["pf_oos"] >= 1.4
                                and row["pf_delay"] >= 1.45 and 1.0 <= tpd <= 5.0 and len(oosr) > 100)
            # softer flag: profitable+OOS-consistent even if not full goal
            row["GOOD"] = int(row["pf30"] >= 1.35 and row["pf_oos"] >= 1.3 and row["pf_delay"] >= 1.3)
            rows.append(row)
            pd.DataFrame([row]).to_csv(CSV, mode="w" if first else "a", header=first, index=False)
            first = False
            if row["ROBUST"] or row["pf30"] >= 1.6:
                log(f"[{i}/{len(grid)}] HIT {direc} {reg} {sess} lb{lb} h{hold} ext{ext} sl{sl} vol{vol} "
                    f"| n={row['n']} tpd={tpd:.1f} PF30={row['pf30']} WR={row['wr30']} "
                    f"OOS={row['pf_oos']} dly={row['pf_delay']} ROBUST={row['ROBUST']}")
        except Exception as e:
            continue
        if i % 200 == 0:
            el = time.time() - t0; log(f"progress {i}/{len(grid)} ({el:.0f}s, {i/el:.1f}/s)")
    log(f"DONE. {len(rows)} configs scored in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
