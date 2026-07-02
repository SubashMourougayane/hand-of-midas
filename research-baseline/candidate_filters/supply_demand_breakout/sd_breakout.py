"""Supply/Demand ZONE BREAKOUT — fresh strategy candidate (NOT a Fib V2 filter).

BIBLE (non-negotiable):
  1. NO LOOK-AHEAD. Zone defined ONLY from bars fully closed before the breakout
     bar. Breakout confirmed on a CLOSED M15 bar. Entry at NEXT M5 grid open after
     the confirming bar closes. Exit walk uses close-based bracket (no intrabar peek).
  2. TIME-AWARE CANDLE CLOSE. Base/zone consolidation window must be fully closed;
     the departure ("leg out") bar must be closed; the breakout candle must close
     beyond the zone before we act.
  3. NO CAUSALITY BUG. Everything indexed by close timestamp. Entry strictly AFTER
     confirmation. 1-bar delay variant tested (memory: prior S/D died at +1 delay).

MEMORY WARNING (ob-microstructure-artifact, sleeve1-orb-leak): prior supply/demand
variants leaked via ORB look-ahead and died at +1 bar delay AND on BRENT. So this
harness bakes in: strict close-based confirm, explicit +1-bar delay test, and a
1R bracket identical to research convention. Cost 0.30/risk.

DEFINITION (classic S/D breakout):
  - Base zone: a tight consolidation of `base_len` M15 bars where range <=
    zone_atr_mult * ATR (a "base" / accumulation).
  - Breakout: the bar AFTER the base closes beyond the base range by
    breakout_buffer * ATR (demand=up break, supply=down break).
  - Entry: momentum continuation in the breakout direction, at next M5 open.
  - Stop: opposite side of the base zone. TP: R multiple.
  - This is a BREAKOUT/momentum strategy (opposite of Fib V2 mean-reversion) —
    the 9,120-BT study said breakout has NEGATIVE avg OOS Sharpe, so we expect
    this to struggle; the test is whether a strict-causal version has ANY edge.
"""
from __future__ import annotations
import sys, itertools
import numpy as np, pandas as pd

M5_PATH = "/tmp/oanda_xau_m5.parquet"
COST_R = 0.30


def load_m15():
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    m15 = (m5.set_index("timestamp").resample("15min", label="left", closed="left")
           .agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
           .dropna().reset_index())
    return m5, m15


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([(df.high-df.low),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def run(base_len, zone_atr_mult, breakout_buf, tp_r, sl_buf_atr, delay_bars, max_hold, m5, m15):
    """Generate breakout trades. Fully causal.

    For each i (breakout candidate = the bar that breaks out), the base is bars
    [i-base_len .. i-1] (all CLOSED before bar i). ATR at i uses closes <= i-1.
    Confirm on bar i's CLOSE. Entry at bar (i+delay_bars) OPEN (next bars).
    """
    m15 = m15.copy()
    m15["atr"] = atr(m15)
    o=m15.open.values; h=m15.high.values; l=m15.low.values; c=m15.close.values
    a=m15["atr"].values; ts=m15.timestamp.values
    N=len(m15)
    trades=[]
    i=base_len+14
    while i < N - (delay_bars+max_hold+1):
        atr_i = a[i-1]  # ATR from bars up to i-1 (causal)
        if not np.isfinite(atr_i) or atr_i<=0:
            i+=1; continue
        base_hi = h[i-base_len:i].max()   # base built from CLOSED bars before i
        base_lo = l[i-base_len:i].min()
        base_range = base_hi-base_lo
        # base must be TIGHT consolidation
        if base_range > zone_atr_mult*atr_i:
            i+=1; continue
        # breakout on bar i's CLOSE beyond base by buffer
        up_break = c[i] > base_hi + breakout_buf*atr_i
        dn_break = c[i] < base_lo - breakout_buf*atr_i
        if not (up_break or dn_break):
            i+=1; continue
        side = 1 if up_break else -1
        ei = i+delay_bars  # entry bar index (delay: +0 = next bar open already causal since i closed)
        if ei>=N: break
        entry = o[ei]      # entry at OPEN of entry bar (all prior bars closed)
        if side>0:
            stop = base_lo - sl_buf_atr*atr_i
        else:
            stop = base_hi + sl_buf_atr*atr_i
        risk = abs(entry-stop)
        if risk<=0: i+=1; continue
        tp = entry + side*tp_r*risk
        # close-based bracket walk from ei .. ei+max_hold
        outcome=None; exit_r=0.0
        for k in range(ei, min(ei+max_hold, N)):
            cl=c[k]
            hit_sl = (side>0 and cl<=stop) or (side<0 and cl>=stop)
            hit_tp = (side>0 and cl>=tp) or (side<0 and cl<=tp)
            if hit_sl: exit_r=-1.0; outcome="SL"; break
            if hit_tp: exit_r=tp_r; outcome="TP"; break
        if outcome is None:
            cl=c[min(ei+max_hold, N-1)]
            exit_r=(cl-entry)*side/risk; outcome="TIME"
        trades.append((ts[i], side, exit_r-COST_R, outcome))
        # advance past this trade's entry to avoid overlap stacking on same base
        i = ei+1
    return pd.DataFrame(trades, columns=["ts","side","net_r","outcome"])


def summ(df):
    if len(df)==0: return dict(n=0)
    r=df.net_r.values
    wr=100*(r>0).mean()
    prof=r[r>0].sum(); loss=-r[r<=0].sum()
    pf=prof/loss if loss>0 else float("inf")
    yrs=pd.to_datetime(df.ts).dt.year
    g=df.assign(y=yrs).groupby("y").net_r.sum()
    py=int((g>0).sum()); ty=len(g)
    return dict(n=len(df), wr=round(wr,1), sum_r=round(r.sum(),1), pf=round(pf,3),
                avg_r=round(r.mean(),4), pos_yrs=f"{py}/{ty}", per_yr=round(r.sum()/max(ty,1),1))

def main():
    print("[load]", flush=True)
    m5,m15=load_m15()
    print(f"M15 bars {len(m15):,}  {m15.timestamp.min()} -> {m15.timestamp.max()}", flush=True)
    # Param sweep — small, disciplined
    grid=list(itertools.product(
        [6,10,16],        # base_len (bars of consolidation = 1.5h/2.5h/4h)
        [0.8,1.2],        # zone_atr_mult (tightness)
        [0.1,0.25],       # breakout_buf (ATR beyond base)
        [1.5,2.5],        # tp_r
        [0.25],           # sl_buf_atr
        [1],              # delay_bars (1 = enter bar after breakout close = strict causal)
        [96],             # max_hold (24h)
    ))
    print(f"[sweep] {len(grid)} configs\n", flush=True)
    rows=[]
    for (bl,zm,bb,tp,sb,dl,mh) in grid:
        df=run(bl,zm,bb,tp,sb,dl,mh,m5,m15)
        s=summ(df)
        s.update(dict(base_len=bl,zone_atr=zm,brk_buf=bb,tp_r=tp,delay=dl))
        rows.append(s)
        print(f"bl={bl:2d} zm={zm} bb={bb} tp={tp} | n={s.get('n',0):5d} wr={s.get('wr','-')} "
              f"pf={s.get('pf','-')} sumR={s.get('sum_r','-')} avgR={s.get('avg_r','-')} "
              f"posY={s.get('pos_yrs','-')} /yr={s.get('per_yr','-')}", flush=True)
    res=pd.DataFrame(rows).sort_values("sum_r",ascending=False)
    print("\n=== TOP 5 by sumR ===")
    print(res.head(5).to_string(index=False))
    # delay robustness on best config: re-run with delay 2 and 3
    best=res.iloc[0]
    print(f"\n=== DELAY ROBUSTNESS on best (bl={int(best.base_len)} zm={best.zone_atr} bb={best.brk_buf} tp={best.tp_r}) ===")
    for dl in [1,2,3]:
        df=run(int(best.base_len),best.zone_atr,best.brk_buf,best.tp_r,0.25,dl,96,m5,m15)
        s=summ(df); print(f"  delay={dl}: n={s['n']} pf={s['pf']} sumR={s['sum_r']} avgR={s['avg_r']} posY={s['pos_yrs']}")
    res.to_csv("sd_breakout_sweep.csv",index=False)
    print("\nsaved sd_breakout_sweep.csv")

if __name__=="__main__":
    main()
