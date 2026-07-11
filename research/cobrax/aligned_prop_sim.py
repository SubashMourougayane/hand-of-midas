#!/usr/bin/env python3
"""ALIGNED prop profile for A+D — NO daily DD, 10% STATIC max only (FundedNext Stellar/
Express, FXIFY, The5ers). Tests whether dropping the daily-DD gate (A+D's tightest
killer in the GFT sim) lets A+D run higher risk => bigger funded $.

Gates: max DD 10% STATIC (equity never < 90% of start). NO daily DD. NO floating rule.
Targets: P1 +8%, P2 +5% (FXIFY/FundedNext standard). >=3 valid days.
Close-based => UPPER bound. Same 20yr A+D strict stream + MC as gft_sim.
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

SYM = "XAUUSD.ecn"
LOG = open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/ALIGNED_PROP_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log", "w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

START=5000.0; MAXDD_FLOOR=0.90*START; VALID=0.005*START; MINDAYS=3; WINDOW=1500

def capture(Cls, frame, hold):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov)
    strat=Cls(symbol=SYM); rows={}
    def _o(tr): rows[tr.trade_id]={"entry_ts":pd.Timestamp(tr.entry_timestamp)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["net_r"]=oc.bracket_1r_outcome-cr
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=strat,execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r]

def attempt(r, days, start_i, R, target):
    eq=START; day=days[start_i]; day_pnl=0.0; valid=0; n=0
    for j in range(start_i, min(start_i+WINDOW,len(r))):
        if days[j]!=day:
            if day_pnl>=VALID: valid+=1
            day=days[j]; day_pnl=0.0
        pnl=R*eq*r[j]; eq+=pnl; day_pnl+=pnl; n+=1
        if eq<MAXDD_FLOOR: return (False,n,"MAXDD")   # NO daily-DD gate
        if eq>=target and (valid+(1 if day_pnl>=VALID else 0))>=MINDAYS: return (True,n,"PASS")
    return (False,n,"TIMEOUT")

def mc(trades,R,target,n_att=3000,seed=0):
    rng=np.random.default_rng(seed)
    r=np.array([t["net_r"] for t in trades])
    days=np.array([pd.Timestamp(t["entry_ts"]).normalize().value for t in trades])
    st=rng.integers(0,len(trades)-WINDOW,size=n_att)
    p=0; ntr=[]; rs={}
    for s in st:
        ok,nt,why=attempt(r,days,int(s),R,target); p+=ok; rs[why]=rs.get(why,0)+1
        if ok: ntr.append(nt)
    return p/n_att,(np.median(ntr) if ntr else None),rs

if __name__=="__main__":
    log("="*78); log(f"ALIGNED PROP (no-daily, 10% static) — A+D strict 5K  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*78)
    log("Firms: FundedNext Stellar/Express, FXIFY, The5ers. NO daily DD, 10% STATIC max, no floating rule.")
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    a=capture(functools.partial(FibV2IntradayA,strict_after=True),frame,48)
    d=capture(functools.partial(FibV2IntradayD,strict_after=True),frame,96)
    ad=sorted(a+d,key=lambda t:t["entry_ts"]); r=np.array([t["net_r"] for t in ad])
    yrs=(pd.Timestamp(ad[-1]["entry_ts"])-pd.Timestamp(ad[0]["entry_ts"])).days/365.25
    tr_mo=len(ad)/yrs/12
    log(f"A+D trades={len(ad)} avgR={r.mean():+.4f} tr/mo={tr_mo:.0f}")
    log("\n=== P1 (+8%) / P2 (+5%) PASS — NO daily DD, 10% static only ===")
    log(f"  {'risk':>5} | {'P1':>7} {'P2':>7} {'P1*P2':>7} | P1 fails")
    for R in (0.005,0.0075,0.01,0.0125,0.015,0.02):
        p1,_,rs1=mc(ad,R,1.08*START); p2,_,_=mc(ad,R,1.05*START)
        log(f"  {R*100:>4.2f}% | {p1*100:>5.1f}% {p2*100:>5.1f}% {p1*p2*100:>5.1f}% | {rs1}")
    log("\n=== FUNDED $ (per 5K/mo, arithmetic expectancy — same DD-truncation caveat as GFT) ===")
    for R in (0.01,0.015,0.02):
        mret=tr_mo*r.mean()*R; g=START*mret
        log(f"  R={R*100:.2f}%: E[mo]~{mret*100:+.1f}%  gross~${g:+,.0f}/mo  @80%=${g*0.8:+,.0f}  @100%=${g:+,.0f}")
    log("CAVEAT: funded acct has SAME 10% static gate -> losing tail truncated to acct death; realized < arithmetic.")
    LOG.close()
