#!/usr/bin/env python3
"""FULL STATS — A+D + DD-throttle, base 1.0% + cap 10%, funded 5K prop account. EVERYTHING.

Prop-account model: risk = 1% * throttle(dd) * balance; withdraw >5000 monthly (reset to
5000); static floor 4500 (blown if breached). 20yr OANDA XAU M15. close-based (intraday/
floating NOT modeled -> optimistic). Dumps every stat + bootstrap + hostile caveats to a log.
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

SYM="XAUUSD.ecn"; CONTRACT=100.0; START=5000.0; FLOOR=0.90*START; BASE=0.01; CAP=0.10
LOG=open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/FULL_STATS_1pct_cap10_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log","w")
def log(*a):
    s=" ".join(str(x) for x in a); print(s,flush=True); LOG.write(s+"\n"); LOG.flush()

def capture(Cls, frame, hold):
    prov=MemoryBarProvider(frame,symbol=SYM,timeframe="M15"); clk=MemoryClock(prov)
    strat=Cls(symbol=SYM); rows={}
    def _o(tr): rows[tr.trade_id]={"entry_ts":pd.Timestamp(tr.entry_timestamp),"risk":float(tr.risk_units),"side":int(tr.side)}
    def _c(tr,oc):
        if tr.trade_id in rows:
            cr=float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["exit_ts"]=pd.Timestamp(oc.exit_timestamp); rows[tr.trade_id]["net_r"]=oc.bracket_1r_outcome-cr
    deps=EngineDeps(clock=clk,data_provider=prov,strategy=strat,execution=BTExecutionModel(),
                    broker=None,on_trade_open=_o,on_trade_close=_c,max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(),deps=deps,mode="bt")
    return [r for r in rows.values() if "net_r" in r and "exit_ts" in r and r["risk"]>0]

def throttle(dd):
    if dd<=0: return 1.0
    if dd>=CAP: return 0.0
    return max(0.0,1.0-dd/CAP)

def pct(a,p): return float(np.percentile(a,p)) if len(a) else 0.0

if __name__=="__main__":
    log("="*94); log(f"FULL STATS — A+D throttled (base {BASE*100:.0f}% + cap {CAP*100:.0f}%), funded 5K prop  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*94)
    m5=pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    a=capture(functools.partial(FibV2IntradayA,strict_after=True),frame,48)
    d=capture(functools.partial(FibV2IntradayD,strict_after=True),frame,96)
    ad=sorted(a+d,key=lambda t:t["entry_ts"])

    # ---- event stream with full instrumentation ----
    ev=[]
    for i,t in enumerate(ad):
        ev.append((t["entry_ts"],0,i)); ev.append((t["exit_ts"],1,i))
    ev.sort(key=lambda x:(x[0],x[1]))
    bal=START; peak=START; lots={}; mult_at={}
    month=None; day=None; day_peak=START
    monthly={}   # (y,m) -> dict(payout, start=5000, end, maxdd, wins, losses, trades, gross)
    mults=[]; min_bal=START; blow=0; worstday=0.0; maxdd_overall=0.0
    def newmonth(mk):
        monthly[mk]=dict(payout=0.0,end=START,maxdd=0.0,wins=0,losses=0,trades=0)
    for ts,kind,i in ev:
        t=ad[i]; ts=pd.Timestamp(ts); mk=(ts.year,ts.month)
        if month is None: month=mk; newmonth(mk)
        elif mk!=month:
            monthly[month]["end"]=bal; monthly[month]["payout"]=max(bal-START,0.0)
            bal=START; peak=START; day_peak=START; month=mk; newmonth(mk)
        dk=ts.normalize()
        if dk!=day: day=dk; day_peak=bal
        if kind==0:
            m=throttle((peak-bal)/peak if peak>0 else 0.0); mults.append(m); mult_at[i]=m
            lots[i]=(BASE*bal*m)/(CONTRACT*t["risk"]) if t["risk"]>0 else 0.0
        else:
            pnl=lots.get(i,0.0)*CONTRACT*t["risk"]*t["net_r"]; bal+=pnl
            monthly[month]["trades"]+=1
            if pnl>0: monthly[month]["wins"]+=1
            elif pnl<0: monthly[month]["losses"]+=1
            peak=max(peak,bal); day_peak=max(day_peak,bal); min_bal=min(min_bal,bal)
            if peak>0:
                dd=(peak-bal)/peak; maxdd_overall=max(maxdd_overall,dd); monthly[month]["maxdd"]=max(monthly[month]["maxdd"],dd)
            if day_peak>0: worstday=max(worstday,(day_peak-bal)/day_peak)
            if bal<FLOOR: blow+=1; monthly[month]["payout"]=max(bal-START,0.0); bal=START; peak=START; day_peak=START
    monthly[month]["end"]=bal; monthly[month]["payout"]=max(bal-START,0.0)

    mk=sorted(monthly); pay=np.array([monthly[k]["payout"] for k in mk])
    mdd=np.array([monthly[k]["maxdd"]*100 for k in mk]); trd=np.array([monthly[k]["trades"] for k in mk])
    yrs=(pd.Timestamp(ad[-1]["entry_ts"])-pd.Timestamp(ad[0]["entry_ts"])).days/365.25
    mults=np.array(mults)

    log(f"\n### COVERAGE ###")
    log(f"  trades={len(ad):,}  span={yrs:.1f}yr  {ad[0]['entry_ts'].date()}..{ad[-1]['entry_ts'].date()}  months={len(mk)}  trades/mo={len(ad)/len(mk):.0f}")
    log(f"  longs(A)={sum(1 for t in ad if t['side']>0):,}  shorts(D)={sum(1 for t in ad if t['side']<0):,}")

    log(f"\n### MONTHLY PAYOUT ($ per 5K, @100% split) ###")
    log(f"  mean=${pay.mean():,.0f}  median=${np.median(pay):,.0f}  std=${pay.std():,.0f}")
    log(f"  min=${pay.min():,.0f}  max=${pay.max():,.0f}  sum(20yr)=${pay.sum():,.0f}")
    log(f"  percentiles: p5=${pct(pay,5):,.0f} p25=${pct(pay,25):,.0f} p50=${pct(pay,50):,.0f} p75=${pct(pay,75):,.0f} p90=${pct(pay,90):,.0f} p95=${pct(pay,95):,.0f}")
    log(f"  %months >0 = {100*np.mean(pay>0):.0f}%   %months =0 (flat) = {100*np.mean(pay==0):.0f}%")
    log(f"  monthly return% (of 5K): mean={100*pay.mean()/START:.1f}% median={100*np.median(pay)/START:.1f}% max={100*pay.max()/START:.0f}%")
    log(f"  @80% split: mean=${pay.mean()*0.8:,.0f}/mo  @100%: ${pay.mean():,.0f}/mo")

    log(f"\n### PER-YEAR PAYOUT ($/yr @100%) ###")
    yr_pay={}
    for k in mk: yr_pay.setdefault(k[0],0.0); yr_pay[k[0]]+=monthly[k]["payout"]
    ys=sorted(yr_pay)
    for y in ys: log(f"  {y}: ${yr_pay[y]:>9,.0f}")
    yv=np.array([yr_pay[y] for y in ys])
    log(f"  year: mean=${yv.mean():,.0f} median=${np.median(yv):,.0f} best=${yv.max():,.0f}({ys[int(np.argmax(yv))]}) worst=${yv.min():,.0f}({ys[int(np.argmin(yv))]}) pos-years={int((yv>0).sum())}/{len(yv)}")

    log(f"\n### DRAWDOWN ###")
    log(f"  realized MAX drawdown (20yr) = {maxdd_overall*100:.1f}%   (cap target {CAP*100:.0f}%)  -> FITS 10% static: {maxdd_overall*100<10}")
    log(f"  worst single-DAY drawdown = {worstday*100:.1f}%   (GFT daily rule 4%: {'FAILS' if worstday*100>4 else 'ok'}; no-daily firms: n/a)")
    log(f"  monthly maxDD: mean={mdd.mean():.1f}% median={np.median(mdd):.1f}% p95={pct(mdd,95):.1f}% max={mdd.max():.1f}%")
    log(f"  min balance EVER = ${min_bal:,.0f}  (floor ${FLOOR:,.0f}; closest approach {100*(min_bal-FLOOR)/START:.1f}% of start above floor)")
    log(f"  BLOWUPS (account terminations, 20yr) = {blow}")

    log(f"\n### THROTTLE ACTIVITY ###")
    log(f"  entries throttled (mult<1) = {100*np.mean(mults<0.999):.0f}%   fully off (mult=0, DD>=cap) = {100*np.mean(mults<=0.001):.1f}%")
    log(f"  mult: mean={mults.mean():.2f} median={np.median(mults):.2f} p25={pct(mults,25):.2f} min={mults.min():.2f}")

    log(f"\n### STREAKS & CONSISTENCY ###")
    def longest(cond):
        best=cur=0
        for k in mk:
            cur=cur+1 if cond(monthly[k]["payout"]) else 0; best=max(best,cur)
        return best
    log(f"  longest run of FLAT/zero months = {longest(lambda p:p==0)}")
    log(f"  longest run of PROFITABLE months = {longest(lambda p:p>0)}")
    wr_mo=np.array([monthly[k]['wins']/max(monthly[k]['trades'],1) for k in mk])
    log(f"  in-month trade win-rate: mean={100*wr_mo.mean():.0f}%")

    log(f"\n### RISK-ADJUSTED (monthly returns of 5K) ###")
    r=pay/START
    sharpe=(r.mean()/r.std()*np.sqrt(12)) if r.std()>0 else 0
    downside=r[r<r.mean()]; sortino=(r.mean()/downside.std()*np.sqrt(12)) if len(downside)>1 and downside.std()>0 else 0
    log(f"  monthly mean={100*r.mean():.1f}% std={100*r.std():.1f}%  annualized Sharpe={sharpe:.2f}  Sortino={sortino:.2f}")
    log(f"  annualized return (mean*12) = {100*r.mean()*12:.0f}%/yr of a static 5K (no compounding — floor est)")

    log(f"\n### BOOTSTRAP ANNUAL INCOME (10k resamples of 12 monthly payouts) ###")
    rng=np.random.default_rng(7); boot=np.array([rng.choice(pay,12,replace=True).sum() for _ in range(10000)])
    log(f"  annual $ @100%: p5=${pct(boot,5):,.0f} p25=${pct(boot,25):,.0f} median=${np.median(boot):,.0f} p75=${pct(boot,75):,.0f} p95=${pct(boot,95):,.0f}")
    log(f"  P(annual income < $3000) = {100*np.mean(boot<3000):.0f}%   P(< $6000) = {100*np.mean(boot<6000):.0f}%")

    log(f"\n### HOSTILE-AUDIT CAVEATS (why the number is optimistic) ###")
    log("  1. close-based M15 equity — intraday/floating MAE NOT modeled -> blowups=0 is a LOWER bound; real slightly worse.")
    log("  2. monthly withdraw-to-5000 = NO compounding -> this is the per-static-5K FLOOR; prop scaling grows it.")
    log("  3. 20yr AVG includes the strategy's best regimes; forward-realized is lumpier (28% flat months).")
    log("  4. single historical ordering for maxDD/streaks; bootstrap above covers annual variance only.")
    log("  5. leverage (commodities 1:10-1:20) not enforced — at 1% on 5K lots are tiny, non-binding.")
    log("  6. assumes the prop pays out monthly in full + no consistency-rule block (true for no-daily firms).")
    LOG.close()
