#!/usr/bin/env python3
"""DD-THROTTLE overlay on A+D — cap native max-DD to fit ANY prop firm, WITHOUT touching
signals (edge-preserving: same trades, same R-sequence, only $ size changes with equity DD).

throttle(dd): de-risk as drawdown-from-peak grows; skip NEW entries past the cap band.
Open trades still run, so the cap is soft (not hard) — reported honestly.

Compares FLAT vs THROTTLED at each base risk: final $, max-DD%, worst single-day DD%,
E[monthly return]. Goal: show a config that keeps max-DD <= ~8-10% (fits strict firms:
daily 4-5% / max 10%) at an acceptable return cost. 20yr exact path.
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

SYM="XAUUSD.ecn"; CONTRACT=100.0; START=5000.0
LOG=open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/THROTTLE_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log","w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

def capture(Cls, frame, hold):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov)
    strat=Cls(symbol=SYM); rows={}
    def _o(tr): rows[tr.trade_id]={"entry_ts":pd.Timestamp(tr.entry_timestamp),"risk":float(tr.risk_units)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["exit_ts"]=pd.Timestamp(oc.exit_timestamp)
            rows[tr.trade_id]["net_r"]=oc.bracket_1r_outcome-cr
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=strat,execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r and "exit_ts" in r and r["risk"]>0]

def throttle(dd, cap):
    """Risk multiplier from current drawdown-from-peak. Linear taper to 0 at `cap`."""
    if dd <= 0: return 1.0
    if dd >= cap: return 0.0
    return max(0.0, 1.0 - (dd / cap))

def path(trades, base_risk, cap=None):
    """Event-stream exact path. cap=None -> flat sizing. Returns final$, maxDD%, worstDayDD%."""
    ev=[]
    for i,t in enumerate(trades):
        ev.append((t["entry_ts"],0,i)); ev.append((t["exit_ts"],1,i))
    ev.sort(key=lambda x:(x[0],x[1]))
    eq=START; peak=START; maxdd=0.0; lots={}
    day=None; day_start=START; worstday=0.0
    for ts,kind,i in ev:
        t=trades[i]
        d=pd.Timestamp(ts).normalize()
        if d!=day:
            if day is not None: worstday=max(worstday,(day_start-eq_day_min)/day_start if day_start>0 else 0)
            day=d; day_start=eq; eq_day_min=eq
        if kind==0:  # entry: size from current equity + throttle
            mult=1.0 if cap is None else throttle((peak-eq)/peak if peak>0 else 0, cap)
            risk_dollar=base_risk*eq*mult
            lots[i]=risk_dollar/(CONTRACT*t["risk"]) if t["risk"]>0 else 0.0
        else:  # exit
            pnl=lots.get(i,0.0)*CONTRACT*t["risk"]*t["net_r"]
            eq+=pnl; peak=max(peak,eq)
            if peak>0: maxdd=max(maxdd,(peak-eq)/peak)
            eq_day_min=min(eq_day_min,eq)
    return eq, maxdd*100, worstday*100

if __name__=="__main__":
    log("="*82); log(f"DD-THROTTLE overlay on A+D (edge-preserving sizing)  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*82)
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    a=capture(functools.partial(FibV2IntradayA,strict_after=True),frame,48)
    d=capture(functools.partial(FibV2IntradayD,strict_after=True),frame,96)
    ad=sorted(a+d,key=lambda t:t["entry_ts"])
    yrs=(pd.Timestamp(ad[-1]["entry_ts"])-pd.Timestamp(ad[0]["entry_ts"])).days/365.25
    log(f"A+D trades={len(ad)} span={yrs:.1f}yr  (throttle = same trades, size scaled by equity-DD only)")
    log(f"\n{'config':<26}{'final$':>14}{'maxDD%':>9}{'worstDay%':>10}")
    for br in (0.005, 0.01, 0.015):
        f,md,wd=path(ad,br,cap=None)
        log(f"  FLAT {br*100:.2f}%{'':<13}${f:>11,.0f}{md:>8.1f}%{wd:>9.1f}%")
        for cap in (0.08, 0.10, 0.12):
            f,md,wd=path(ad,br,cap=cap)
            log(f"    throttle cap={cap*100:.0f}%{'':<9}${f:>11,.0f}{md:>8.1f}%{wd:>9.1f}%")
    log("\nNOTE: maxDD is CLOSE-based exact path (one 20yr ordering). Throttle SOFT-caps (open")
    log("trades still run past the band). Intraday/floating not modeled. Edge (R-sequence) UNCHANGED.")
    LOG.close()
