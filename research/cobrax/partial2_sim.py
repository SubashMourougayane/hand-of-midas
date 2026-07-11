#!/usr/bin/env python3
"""SECOND partial-TP tier for A+D — does banking more of the +2R runners help?

Current live: 50% partial at +1R (SL->BE), remainder runs to fib TP 2.618. The bracket's
partial is an ADDITIVE bonus: partial_filled_r = pct*trigger, added to the trade outcome.
So a 2nd tier is EXACT to reconstruct from each trade's MFE (== what the engine's second
_partial_tp_check would compute): two_tier_net = baseline_net + pct2*trigger2 * (mfe_r>=trigger2).

Tests tier configs (extra 25%@2R, 25%@3R, 33%@2R) vs baseline. Reports netR/avgR/PF (WR
unchanged — same trades) + how many of the current BE-survivors (SL_BE) actually reached
the tier and get upgraded. Live engine capture, cost $0.65, no look-ahead.
CAVEAT: uses the CERTIFIED (generous) additive-partial convention — same as the live
baseline, so the COMPARISON is fair; absolute R inherits that convention.
"""
import sys, uuid, functools
from datetime import datetime, timezone
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to

SYM="XAUUSD.ecn"
LOG=open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/PARTIAL2_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log","w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

def capture(Cls, frame, hold):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov); rows={}
    def _o(tr): rows[tr.trade_id]={"side":int(tr.side)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0); r=rows[tr.trade_id]
            r["net_r"]=oc.bracket_1r_outcome-cr; r["mfe"]=float(tr.mfe_r); r["reason"]=oc.reason; r["partial"]=bool(tr.partial_taken)
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=Cls(symbol=SYM),execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r]

def pf(x):
    x=np.asarray(x); w=x[x>0].sum(); l=-x[x<0].sum(); return w/l if l>0 else float('inf')

def summ(name, r):
    r=np.asarray(r); w=r[r>0]
    log(f"    {name:<26} netR={r.sum():>+8.1f} avgR={r.mean():>+.4f} PF={pf(r):.3f} WR={100*len(w)/len(r):.1f}% avgWin={w.mean() if len(w) else 0:+.2f}")

if __name__=="__main__":
    log("="*80); log(f"A+D 2nd partial-TP tier test  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*80)
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    a=capture(functools.partial(FibV2IntradayA,strict_after=True),frame,48)
    d=capture(functools.partial(FibV2IntradayD,strict_after=True),frame,96)
    ad=a+d
    base=np.array([t["net_r"] for t in ad]); mfe=np.array([t["mfe"] for t in ad])
    log(f"\nA+D trades={len(ad)}  MFE reach: >=1R {100*(mfe>=1).mean():.0f}%  >=2R {100*(mfe>=2).mean():.0f}%  >=3R {100*(mfe>=3).mean():.0f}%  >=5R {100*(mfe>=5).mean():.0f}%")
    # of current BE-survivors (SL_BE), how many reached +2R?
    be=[t for t in ad if t["reason"]=="SL_BE"]; be_mfe=np.array([t["mfe"] for t in be])
    log(f"BE-survivors (SL_BE) = {len(be)}; of those reached >=2R = {100*(be_mfe>=2).mean():.0f}%  >=3R = {100*(be_mfe>=3).mean():.0f}%  (these get upgraded by a 2nd tier)")

    log(f"\n### RESULTS (same trades; 2nd tier = +pct2*trig2 R when mfe>=trig2) ###")
    summ("BASELINE (50%@1R only)", base)
    for pct2,trig2,label in [(0.25,2.0,"+25%@2R"),(0.25,3.0,"+25%@3R"),(0.33,2.0,"+33%@2R"),(0.25,2.0,"+25%@2R"),(0.50,2.0,"+50%@2R")]:
        two=base + pct2*trig2*(mfe>=trig2)
        summ(f"2-tier {label}", two)
    log(f"\nNOTE: additive certified-partial convention (same as live baseline) -> comparison fair.")
    log("A 2nd tier NEVER hurts here (it only adds R on trades that reached the tier) — the question is HOW MUCH,")
    log("and whether it's worth the extra live execution (one more CLOSE_PARTIAL + slippage per qualifying trade).")
    LOG.close()


# ---- PHYSICAL model appendix (run separately) ----
def physical_check():
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    def cap2(Cls,hold):
        prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov); rows={}
        def _o(tr): rows[tr.trade_id]={}
        def _c(tr,oc):
            if tr.trade_id in rows:
                r=rows[tr.trade_id]; r["gross"]=oc.bracket_1r_outcome; r["cost"]=float((tr.order.extra or {}).get("cost_r") or 0.0); r["mfe"]=float(tr.mfe_r)
        deps=EngineDeps(clock=clk,data_provider=prov,strategy=Cls(symbol=SYM),execution=BTExecutionModel(),broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
        run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt"); return [r for r in rows.values() if "gross" in r]
    ad=cap2(functools.partial(FibV2IntradayA,strict_after=True),48)+cap2(functools.partial(FibV2IntradayD,strict_after=True),96)
    g=np.array([t["gross"] for t in ad]); c=np.array([t["cost"] for t in ad]); mfe=np.array([t["mfe"] for t in ad])
    p1=0.5*(mfe>=1)                     # additive partial-1 bonus in the certified gross
    base_exit=g-p1                       # raw full-position runner R (remove the bonus)
    def net(x): return x-c
    def rep(name,arr):
        arr=net(arr); w=arr[arr>0]
        log(f"    {name:<34} netR={arr.sum():>+8.1f} avgR={arr.mean():>+.4f} PF={pf(arr):.3f} WR={100*len(w)/len(arr):.1f}%")
    log("\n### PHYSICAL model (fractions actually leave the runner) — THE HONEST TEST ###")
    rep("CERTIFIED baseline (additive)", g)                       # as live/cert books it
    rep("PHYSICAL baseline 50%@1R+50%run", p1 + 0.5*base_exit)
    for p2,tr in [(0.25,2.0),(0.25,3.0),(0.33,2.0)]:
        two = 0.5*(mfe>=1) + p2*tr*(mfe>=tr) + (1-0.5-p2)*base_exit
        rep(f"PHYSICAL 2-tier 50%@1R+{int(p2*100)}%@{int(tr)}R+run", two)
    log("  -> compare PHYSICAL baseline vs PHYSICAL 2-tier. If 2-tier <= baseline, the 2nd partial")
    log("     sacrifices the fat tail (booking small@2R forfeits the runner's +36R) — SAME lesson as 1:2.")

if __name__!="__main__": pass
