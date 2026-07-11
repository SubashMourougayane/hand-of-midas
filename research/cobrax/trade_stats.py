#!/usr/bin/env python3
"""TRADE-LEVEL stats — current live A+D (strict production), 21yr XAUUSD. ALL numbers.

Runs FibV2IntradayA + FibV2IntradayD (the live strategy, BT mode = certified 0-delta to
live) over 20.3yr OANDA XAU M15. Dumps every trade statistic by leg + exit reason.
Trade-level only (R-space) — sizing/$ is separate. avgR/PF are per-trade net R (incl cost + PTP).
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
LOG=open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/TRADE_STATS_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log","w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

def capture(Cls, frame, hold, leg):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov)
    strat=Cls(symbol=SYM); rows={}
    def _o(tr): rows[tr.trade_id]={"entry_ts":pd.Timestamp(tr.entry_timestamp),"side":int(tr.side)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0)
            r=rows[tr.trade_id]
            r["net_r"]=oc.bracket_1r_outcome-cr; r["gross_r"]=oc.bracket_1r_outcome
            r["reason"]=oc.reason; r["bars"]=tr.bars_held; r["partial"]=bool(tr.partial_taken)
            r["mfe"]=float(tr.mfe_r); r["mae"]=float(tr.mae_r); r["exit_ts"]=pd.Timestamp(oc.exit_timestamp); r["leg"]=leg
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=strat,execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r]

def pf(x):
    x=np.asarray(x); w=x[x>0].sum(); l=-x[x<0].sum(); return w/l if l>0 else float('inf')

def block(name, tr):
    if not tr: log(f"  {name}: 0 trades"); return
    r=np.array([t["net_r"] for t in tr]); wins=r[r>0]; loss=r[r<0]; scr=r[r==0]
    reasons={}
    for t in tr: reasons[t["reason"]]=reasons.get(t["reason"],0)+1
    part=sum(1 for t in tr if t["partial"])
    yrs=(pd.Timestamp(max(t["entry_ts"] for t in tr))-pd.Timestamp(min(t["entry_ts"] for t in tr))).days/365.25
    log(f"\n  ===== {name} =====")
    log(f"    trades={len(r)}  wins={len(wins)}  losses={len(loss)}  scratch(0R)={len(scr)}  WR={100*len(wins)/len(r):.1f}%")
    log(f"    netR={r.sum():+.1f}  avgR={r.mean():+.4f}  PF={pf(r):.3f}  expectancy={r.mean():+.4f}R")
    log(f"    avgWin={wins.mean() if len(wins) else 0:+.3f}R  avgLoss={loss.mean() if len(loss) else 0:+.3f}R  "
        f"payoff={abs(wins.mean()/loss.mean()) if len(loss) and loss.mean()!=0 else 0:.2f}")
    log(f"    bestR={r.max():+.2f}  worstR={r.min():+.2f}  medianR={np.median(r):+.3f}")
    log(f"    partial-TP taken={part} ({100*part/len(r):.0f}%)  avg bars held={np.mean([t['bars'] for t in tr]):.1f}")
    log(f"    exit reasons: {reasons}")
    log(f"    trades/yr={len(r)/yrs:.0f}  trades/mo={len(r)/yrs/12:.0f}")
    # streaks
    seq=(r>0).astype(int); mw=mc=cw=cc=0
    for x in seq:
        if x: cw+=1; cc=0
        else: cc+=1; cw=0
        mw=max(mw,cw); mc=max(mc,cc)
    log(f"    longest win streak={mw}  longest loss streak={mc}")

if __name__=="__main__":
    log("="*80); log(f"TRADE STATS — live A+D strict, 21yr XAUUSD (OANDA M5->M15)  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*80)
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    log(f"DATA: {len(frame):,} M15 bars  {frame.timestamp.iloc[0]} .. {frame.timestamp.iloc[-1]}")
    a=capture(functools.partial(FibV2IntradayA,strict_after=True),frame,48,"A")
    d=capture(functools.partial(FibV2IntradayD,strict_after=True),frame,96,"D")
    ad=a+d
    block("A+D COMBINED", ad)
    block("A LEG (LONG only)", a)
    block("D LEG (SHORT only)", d)
    # explicit long/short win split
    aw=sum(1 for t in a if t["net_r"]>0); dw=sum(1 for t in d if t["net_r"]>0)
    log(f"\n  ===== WIN SPLIT =====")
    log(f"    LONG wins (A)  = {aw} / {len(a)}  ({100*aw/len(a):.1f}%)")
    log(f"    SHORT wins (D) = {dw} / {len(d)}  ({100*dw/len(d):.1f}%)")
    log(f"    total wins = {aw+dw} / {len(ad)}  ({100*(aw+dw)/len(ad):.1f}%)  | long-share of wins={100*aw/(aw+dw):.0f}%")
    LOG.close()
