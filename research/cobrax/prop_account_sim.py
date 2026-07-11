#!/usr/bin/env python3
"""PROP-ACCOUNT sim for A+D with DD-throttle — the decision sim.

Models a REAL funded 5K prop account (no unbounded compounding):
  - risk per trade = base% * throttle(dd) * current balance
  - throttle(dd): de-risk as drawdown-from-peak grows, taper to 0 at `cap` (edge-preserving:
    same trades/R-sequence, only $ size scales)
  - MONTHLY payout: at month end, withdraw everything above 5000 (banked), reset balance to 5000
    (how a funded account actually works — you don't compound to millions)
  - STATIC max-DD floor 4500 (never below 90% of 5000). If breached at any trade close -> account
    BLOWN (terminated); re-seed a fresh 5000 to keep measuring the long-run rate.
  - daily worst drop tracked (for firms with a daily-DD rule, e.g. GFT 4%).

Reports per (base_risk, cap): avg monthly payout $, %months profitable, worst-day DD%, realized
max-DD%, and BLOW-UP count (accounts lost). This is the honest earnings + survival + fit answer.

close-based (M15) -> intraday/floating not modeled -> optimistic; treat blow-ups as a LOWER bound.
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

SYM="XAUUSD.ecn"; CONTRACT=100.0; START=5000.0; FLOOR=0.90*START  # static 10% max
LOG=open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/PROP_ACCOUNT_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log","w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

def capture(Cls, frame, hold):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov)
    strat=Cls(symbol=SYM); rows={}
    def _o(tr): rows[tr.trade_id]={"entry_ts":pd.Timestamp(tr.entry_timestamp),"risk":float(tr.risk_units)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["exit_ts"]=pd.Timestamp(oc.exit_timestamp); rows[tr.trade_id]["net_r"]=oc.bracket_1r_outcome-cr
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=strat,execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r and "exit_ts" in r and r["risk"]>0]

def throttle(dd, cap):
    if cap is None: return 1.0
    if dd<=0: return 1.0
    if dd>=cap: return 0.0
    return max(0.0, 1.0-dd/cap)

def run_prop(trades, base, cap):
    ev=[]
    for i,t in enumerate(trades):
        ev.append((t["entry_ts"],0,i)); ev.append((t["exit_ts"],1,i))
    ev.sort(key=lambda x:(x[0],x[1]))
    bal=START; peak=START; lots={}; payouts=[]; blow=0
    month=None; month_start=START; day=None; day_peak=START; worstday=0.0; maxdd=0.0
    for ts,kind,i in ev:
        t=trades[i]; ts=pd.Timestamp(ts)
        mk=(ts.year,ts.month)
        if month is None: month=mk; month_start=bal
        elif mk!=month:  # month rollover -> payout excess, reset to START
            if bal>START: payouts.append(bal-START)
            else: payouts.append(0.0)
            bal=START; peak=START; month=mk; month_start=bal
        dk=ts.normalize()
        if dk!=day: day=dk; day_peak=bal
        if kind==0:
            mult=throttle((peak-bal)/peak if peak>0 else 0, cap)
            lots[i]=(base*bal*mult)/(CONTRACT*t["risk"]) if t["risk"]>0 else 0.0
        else:
            bal+=lots.get(i,0.0)*CONTRACT*t["risk"]*t["net_r"]
            peak=max(peak,bal); day_peak=max(day_peak,bal)
            if peak>0: maxdd=max(maxdd,(peak-bal)/peak)
            if day_peak>0: worstday=max(worstday,(day_peak-bal)/day_peak)
            if bal<FLOOR:   # static max-DD breach -> account blown, re-seed
                blow+=1; payouts.append(bal-START); bal=START; peak=START; day_peak=START
    n_mo=max(len(payouts),1)
    return dict(months=len(payouts), avg=np.mean(payouts) if payouts else 0,
                pctpos=100*np.mean([p>0 for p in payouts]) if payouts else 0,
                maxdd=maxdd*100, worstday=worstday*100, blow=blow)

if __name__=="__main__":
    log("="*90); log(f"PROP-ACCOUNT sim — A+D + DD-throttle, funded 5K, monthly payout, static 10% floor  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*90)
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    a=capture(functools.partial(FibV2IntradayA,strict_after=True),frame,48)
    d=capture(functools.partial(FibV2IntradayD,strict_after=True),frame,96)
    ad=sorted(a+d,key=lambda t:t["entry_ts"])
    log(f"A+D trades={len(ad)}  model: risk=base%*throttle(dd)*balance, withdraw>5000 monthly, blow if <4500")
    log(f"\n{'config':<28}{'avg$/mo':>10}{'%mo+':>7}{'maxDD%':>8}{'worstDay%':>10}{'blowups':>9}  fit?")
    for base in (0.005,0.0075,0.01,0.015):
        for cap in (None,0.10,0.08):
            r=run_prop(ad,base,cap)
            capn="flat " if cap is None else f"cap{int(cap*100)}%"
            # fit: GFT needs maxDD<10 & worstDay<4 ; aligned(no-daily) needs maxDD<10 only
            gft = "GFT+any" if (r['maxdd']<10 and r['worstday']<4 and r['blow']==0) else ("aligned" if (r['maxdd']<10 and r['blow']==0) else "NO")
            log(f"  base {base*100:.2f}% {capn:<14}${r['avg']:>7,.0f}{r['pctpos']:>6.0f}%{r['maxdd']:>7.1f}%{r['worstday']:>9.1f}%{r['blow']:>9}  {gft}")
    log(f"\n@100% split the avg$/mo IS your take (80% => x0.8). ~{len(ad)/((pd.Timestamp(ad[-1]['entry_ts'])-pd.Timestamp(ad[0]['entry_ts'])).days/365.25/12):.0f} trades/mo.")
    log("CAVEAT: close-based (no intraday/floating) => blowups are a LOWER bound; real slightly worse.")
    LOG.close()
