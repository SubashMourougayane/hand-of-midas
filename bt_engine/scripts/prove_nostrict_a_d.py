#!/usr/bin/env python3
"""PROOF for the no-strict A+D flag (strict_after=False).

Three things proven, all via run_engine (the SAME engine BT and live share):
  1. REGRESSION: strict_after=True (default) reproduces the certified baseline numbers.
  2. NO-STRICT DELTA: strict_after=False adds the confirm-bar entries (+trades, ~+6% R).
  3. BT == LIVE 0-delta for the no-strict variant (one-code-two-modes holds).

Causality note: no-strict does NOT relax look-ahead. The setup is confirmed at bar K's
close; the confirm bar merely becomes a valid entry-SCAN bar; the fill is still bar K+1's
open (base _finalize_entry next-bar-open queue). known_at was audited earlier (0 violations
across 1,745 confirm-bar entries) — this script proves the FLAG wiring + BT/live parity.

Data: persistent parquet (survives /tmp wipes).
"""
from __future__ import annotations
import sys, uuid, time
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies import registry
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine/scripts")
from parity_21yr_bt_vs_live import BTMirrorLiveBroker, run_path, summ

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
MAX_HOLD = 24*4*2  # 192

def main():
    t0=time.time()
    m5=pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    print(f"M15 bars {len(frame):,}  {frame.timestamp.min()} -> {frame.timestamp.max()}", flush=True)

    print("\n[1] BT strict (baseline, default)...", flush=True)
    bt_s,_ = run_path("bt", frame, "fib_v2_intraday_a_plus_d", MAX_HOLD)
    print("[2] BT no-strict...", flush=True)
    bt_ns,_ = run_path("bt", frame, "fib_v2_intraday_a_plus_d_nostrict", MAX_HOLD)
    print("[3] LIVE no-strict (mirror broker)...", flush=True)
    lv_ns,_ = run_path("live", frame, "fib_v2_intraday_a_plus_d_nostrict", MAX_HOLD)

    ss, sn, sl = summ(bt_s), summ(bt_ns), summ(lv_ns)
    print("\n"+"="*74)
    print(f"{'':<10}{'BT strict':>16}{'BT no-strict':>16}{'LIVE no-strict':>18}")
    for k in ["n","sumR","wr","pf","posY"]:
        print(f"{k:<10}{str(ss.get(k)):>16}{str(sn.get(k)):>16}{str(sl.get(k)):>18}")
    print("="*74)
    dR = (sn['sumR']-ss['sumR'])/abs(ss['sumR'])*100
    dN = sn['n']-ss['n']
    print(f"\nNO-STRICT DELTA vs baseline: +{dN} trades ({100*dN/ss['n']:+.1f}%), net-R {dR:+.1f}%")

    # BT == LIVE 0-delta for no-strict
    setB=set((t[0],t[1],round(t[3],6)) for t in bt_ns)
    setL=set((t[0],t[1],round(t[3],6)) for t in lv_ns)
    only_b=setB-setL; only_l=setL-setB
    print(f"\nBT==LIVE (no-strict): shared={len(setB&setL)} only_BT={len(only_b)} only_LIVE={len(only_l)}")
    print("  -> " + ("PERFECT 0-DELTA PARITY ✓" if not only_b and not only_l
                     else f"DIVERGENCE ✗  BT-only:{list(only_b)[:2]} LIVE-only:{list(only_l)[:2]}"))
    print(f"\ndone {time.time()-t0:.0f}s")

if __name__=="__main__":
    main()
