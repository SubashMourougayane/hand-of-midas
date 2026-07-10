#!/usr/bin/env python3
"""BASELINE A+D risk-cliff — is LIVE 3% over-betting? (live-money relevant)

Two views on the SAME A+D trade stream (production strict, 20yr OANDA XAU):
  1. HISTORICAL (real EquitySizer, exact path): final $, min-equity, max drawdown %.
  2. MONTE-CARLO (fixed-fractional, shuffled sequences): optimal-f (growth-max risk),
     risk-of-ruin at each risk, terminal-wealth distribution.
The one historical ordering can hide/expose luck; the MC gives the risk structure.
"""
import sys, uuid
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
from combined_pnl import capture_leg, SYM, CONTRACT
from bt_engine.data.memory_provider import resample_m5_to
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig

def hist_path(trades, start, risk_pct):
    """Real EquitySizer, exact event-stream path. Returns final$, min_eq, maxDD%."""
    sz = EquitySizer(EquitySizerConfig(start_balance=start, risk_pct=risk_pct))
    ev = []
    for i, t in enumerate(trades):
        ev.append((pd.Timestamp(t["entry_ts"]), 0, i)); ev.append((pd.Timestamp(t["exit_ts"]), 1, i))
    ev.sort(key=lambda x: (x[0], x[1]))
    lots = {}; peak = start; maxdd = 0.0; min_eq = start
    for ts, kind, i in ev:
        t = trades[i]
        if kind == 0:
            lots[i] = sz.size_order(symbol=SYM, stop_distance=t["risk"], ts=ts.to_pydatetime())
        else:
            sz.on_trade_closed(pnl_dollars=lots.get(i, 0.0) * CONTRACT * t["risk"] * t["net_r"],
                               close_ts=ts.to_pydatetime())
            eq = sz.state.current_equity
            peak = max(peak, eq); min_eq = min(min_eq, eq)
            if peak > 0: maxdd = max(maxdd, (peak - eq) / peak)
    banked = sum(h["skim_amount"] for h in sz.state.skim_history)
    return banked + sz.state.current_equity, min_eq, maxdd * 100

def mc_ruin(nets, risk_pct, n=4000, ruin_frac=0.20, seed=0):
    """Fixed-fractional sequential bet on shuffled trade order. equity*=(1+f*net_r).
    Ruin = equity ever <= ruin_frac of start. Returns P(ruin), median terminal x, worstDD%."""
    rng = np.random.default_rng(seed); arr = np.asarray(nets)
    ruins = 0; terms = []; dds = []
    for _ in range(n):
        seq = rng.permutation(arr); eq = 1.0; peak = 1.0; ruined = False; dd = 0.0
        for r in seq:
            eq *= (1.0 + risk_pct * r)
            if eq <= ruin_frac:
                ruined = True; eq = max(eq, 1e-9)
            peak = max(peak, eq); dd = max(dd, (peak - eq) / peak)
        ruins += ruined; terms.append(eq); dds.append(dd)
    return 100 * ruins / n, float(np.median(terms)), 100 * float(np.median(dds))

if __name__ == "__main__":
    print("loading M5 -> M15 ...", flush=True)
    m5 = pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15")
    print("A ...", flush=True); a = capture_leg(FibV2IntradayA, frame, 48)
    print("D ...", flush=True); d = capture_leg(FibV2IntradayD, frame, 96)
    ad = sorted(a + d, key=lambda t: pd.Timestamp(t["entry_ts"]))
    nets = [t["net_r"] for t in ad]
    print(f"  A+D trades={len(ad)}  netR={sum(nets):.0f}  avgR={np.mean(nets):+.3f}\n")

    print("=== HISTORICAL (real sizer, $5k) ===")
    print(f"  {'risk':>5} | {'final $':>12} {'min-eq':>9} {'maxDD%':>7}")
    for rp in (0.015, 0.02, 0.025, 0.03, 0.035, 0.04):
        f5, m5e, dd = hist_path(ad, 5000.0, rp)
        print(f"  {rp*100:>4.1f}% | ${f5:>10,.0f} ${m5e:>7,.0f} {dd:>6.1f}%")

    print("\n=== MONTE-CARLO (4000 shuffles, ruin=20% of start) ===")
    print(f"  {'risk':>5} | {'P(ruin)':>8} {'medianTerminal':>15} {'medianDD%':>10}")
    for rp in (0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05):
        pr, med, mdd = mc_ruin(nets, rp)
        print(f"  {rp*100:>4.1f}% | {pr:>6.1f}% {med:>14.1f}x {mdd:>9.1f}%")
    # growth-optimal f (max median terminal)
    grid = np.arange(0.005, 0.06, 0.0025)
    meds = [(f, mc_ruin(nets, f, n=2500, seed=1)[1]) for f in grid]
    fopt, mopt = max(meds, key=lambda x: x[1])
    print(f"\n  growth-optimal f ~ {fopt*100:.2f}%  (median terminal {mopt:.1f}x)")
    print(f"  LIVE is 3.0% — compare to optimal above.")
