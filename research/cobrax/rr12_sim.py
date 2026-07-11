#!/usr/bin/env python3
"""A+D with FIXED R:R 1:2 (TP = +2R) — live engine, no fake fill / no look-ahead.

Override ONLY the TP: new_tp = stop + side*3*risk_units == entry(+2R). Everything else is
the live code (real next-bar-open fills, real close-based bracket, real cost $0.65). TP is a
deterministic fn of entry+risk (both known at entry) -> causal.

Variants:
  A) PURE 1:2  — 2R TP, NO partial (clean fixed 1:2).
  B) CODE+2R   — 2R TP, KEEP production PTP+1R (partial at +1R then remainder to +2R).
Reports trade stats (by leg) + REAL EquitySizer P&L risk table for each. vs baseline (fib TP).
"""
import sys, uuid, functools
from dataclasses import replace as dreplace
from datetime import datetime, timezone
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD
from bt_engine.strategies.fib_v2_intraday.config import make_intraday_a_config, make_intraday_d_config
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig, CONTRACT_SIZE

SYM="XAUUSD.ecn"; CONTRACT=CONTRACT_SIZE[SYM]
LOG=open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/RR12_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log","w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

def mk_rr12(Base):
    class _RR12(Base):
        def _finalize_entry(self, bar, leg, setup):
            order, ev = super()._finalize_entry(bar, leg, setup)
            if order is not None:
                new_tp = order.stop_price + order.side*3.0*order.risk_units  # entry + 2R
                order = dreplace(order, take_profit=float(new_tp))
            return order, ev
    return _RR12

A_RR12 = mk_rr12(FibV2IntradayA); D_RR12 = mk_rr12(FibV2IntradayD)

def cfg_no_ptp(mk):
    c=mk(); return dreplace(c, base=dreplace(c.base, partial_tp_at_r=None))

def capture(strat, frame, hold):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov); rows={}
    def _o(tr): rows[tr.trade_id]={"entry_ts":pd.Timestamp(tr.entry_timestamp),"side":int(tr.side),"risk":float(tr.risk_units)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0); r=rows[tr.trade_id]
            r["net_r"]=oc.bracket_1r_outcome-cr; r["reason"]=oc.reason; r["exit_ts"]=pd.Timestamp(oc.exit_timestamp)
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=strat,execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r and "exit_ts" in r and r["risk"]>0]

def pf(x):
    x=np.asarray(x); w=x[x>0].sum(); l=-x[x<0].sum(); return w/l if l>0 else float('inf')

def stat_line(name, tr):
    r=np.array([t["net_r"] for t in tr]); w=r[r>0]; reasons={}
    for t in tr: reasons[t["reason"]]=reasons.get(t["reason"],0)+1
    log(f"    {name:<10} n={len(r):>6} wins={len(w):>6} WR={100*len(w)/len(r):>5.1f}% netR={r.sum():>+8.1f} "
        f"avgR={r.mean():>+.4f} PF={pf(r):.3f} avgWin={w.mean() if len(w) else 0:+.2f} avgLoss={r[r<0].mean() if len(r[r<0]) else 0:+.2f} best={r.max():+.1f}")
    log(f"               exits: {reasons}")

def hist(trades, start, rp):
    sz=EquitySizer(EquitySizerConfig(start_balance=start,risk_pct=rp)); ev=[]
    for i,t in enumerate(trades): ev.append((t["entry_ts"],0,i)); ev.append((t["exit_ts"],1,i))
    ev.sort(key=lambda x:(x[0],x[1])); lots={}; peak=start; mdd=0.0; mn=start
    for ts,k,i in ev:
        t=trades[i]
        if k==0: lots[i]=sz.size_order(symbol=SYM,stop_distance=t["risk"],ts=pd.Timestamp(ts).to_pydatetime())
        else:
            sz.on_trade_closed(pnl_dollars=lots.get(i,0.0)*CONTRACT*t["risk"]*t["net_r"],close_ts=pd.Timestamp(ts).to_pydatetime())
            eq=sz.state.current_equity; peak=max(peak,eq); mn=min(mn,eq)
            if peak>0: mdd=max(mdd,(peak-eq)/peak)
    return sum(h["skim_amount"] for h in sz.state.skim_history)+sz.state.current_equity, mn, mdd*100

if __name__=="__main__":
    log("="*88); log(f"A+D FIXED R:R 1:2 (TP=+2R) — live engine, cost \$0.65  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*88)
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    log(f"DATA {len(frame):,} M15 bars  {frame.timestamp.iloc[0]}..{frame.timestamp.iloc[-1]}  (TP override = stop+side*3*risk = +2R)")

    variants=[
      ("PURE 1:2 (no partial)", A_RR12(intraday_config=cfg_no_ptp(make_intraday_a_config)), D_RR12(intraday_config=cfg_no_ptp(make_intraday_d_config))),
      ("CODE+2R (keep PTP+1R)", A_RR12(), D_RR12()),
      ("BASELINE (fib TP=2.618)", FibV2IntradayA(), FibV2IntradayD()),
    ]
    results={}
    for name,sa,sd in variants:
        log(f"\n### {name} ###")
        a=capture(sa,frame,48); d=capture(sd,frame,96); ad=sorted(a+d,key=lambda t:t["entry_ts"])
        stat_line("A+D",ad); stat_line("A long",a); stat_line("D short",d)
        results[name]=ad
        log(f"    P&L (real EquitySizer, \$5k start, min-eq / maxDD%):")
        for rp in (0.01,0.015,0.02,0.03):
            f,mn,dd=hist(ad,5000.0,rp)
            log(f"      {rp*100:>4.1f}% -> \${f:>13,.0f}   min-eq \${mn:>8,.0f}   maxDD {dd:.1f}%")
    log("\nCAVEAT: real next-bar-open fills + close-based bracket + cost \$0.65 (live). No look-ahead.")
    log("R:R 1:2 caps winners at +2R -> loses the fib fat tail (+36R); watch if netR/PF drop vs baseline.")
    LOG.close()
