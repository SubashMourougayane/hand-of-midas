#!/usr/bin/env python3
"""VERIFY FVG-nested across ALL 288 configs under BOTH execution models:
  - CLOSE-based (original: exit when CLOSE crosses stop/TP, books -1R/+TP) -- the artifact
  - HONEST intrabar (stop fills on the WICK at -1R; TP fills on touch; same-bar => stop first)
Flags which configs survive HONEST execution vs which were close-based mirages.
"""
from __future__ import annotations
import sys
from itertools import product
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, COST_USD
from research.fvg_nested.run_fvg_fast import resample, detect_fvgs, gen_signals_fast


def sim(m5_arr, sigs, tp_mult, mode, cost=COST_USD, horizon=288, max_wait=96):
    op=m5_arr["open"];hi=m5_arr["high"];lo=m5_arr["low"];cl=m5_arr["close"];ts=m5_arr["ts"];yr=m5_arr["year"]
    n=len(op); outs=[]
    for sg in sigs.itertuples(index=False):
        i0=int(sg.signal_index); side=int(sg.side); limit=float(sg.limit_price); stop=float(sg.stop_price)
        end_w=min(n-1,i0+1+max_wait); fill=-1
        for k in range(i0+1,end_w):
            if side>0 and lo[k]<=limit: fill=k;break
            if side<0 and hi[k]>=limit: fill=k;break
        if fill<0: continue
        entry=limit if ((side>0 and op[fill]>=limit) or (side<0 and op[fill]<=limit)) else op[fill]
        risk=(entry-stop) if side>0 else (stop-entry)
        if risk<=0 or not np.isfinite(risk) or risk>0.01*entry: continue
        tp=entry+tp_mult*risk*side
        end=min(n-1,fill+horizon); out=None; xi=end
        for j in range(fill,end+1):
            if mode=="close":
                c=cl[j]
                if side>0:
                    if c<=stop: out=-1.0;xi=j;break
                    if c>=tp: out=tp_mult;xi=j;break
                else:
                    if c>=stop: out=-1.0;xi=j;break
                    if c<=tp: out=tp_mult;xi=j;break
            else:  # honest intrabar: stop on wick first (conservative), tp on touch
                if side>0:
                    if lo[j]<=stop: out=-1.0;xi=j;break
                    if hi[j]>=tp: out=tp_mult;xi=j;break
                else:
                    if hi[j]>=stop: out=-1.0;xi=j;break
                    if lo[j]<=tp: out=tp_mult;xi=j;break
        if out is None:
            out=max(-1.0,min(tp_mult, side*(cl[xi]-entry)/risk))
        outs.append((yr[fill], out-cost/risk))
    return pd.DataFrame(outs,columns=["year","net_r"])


def pf(x): x=np.asarray(x,float); gl=-x[x<0].sum(); return x[x>0].sum()/gl if gl>0 else 9.9
def stats(d):
    if len(d)<15: return None
    r=d["net_r"].values; ys=d.groupby("year")["net_r"].sum()
    return dict(n=len(r),pf=pf(r),wr=(r>0).mean()*100,net=r.sum(),
                posY=int((ys>0).sum()),tot=d["year"].nunique(),
                oos=pf(d[d.year>=2023]["net_r"].values) if (d.year>=2023).sum()>10 else 0)


def main():
    m1,m5,_=load_data()
    h4=detect_fvgs(resample(m1,"4h")); m15=detect_fvgs(resample(m1,"15min"))
    arr={k:m5[k].values for k in ["open","high","low","close"]}; arr["ts"]=m5["timestamp"].values; arr["year"]=m5["year"].values
    print(f"data {m5['timestamp'].min()}..{m5['timestamp'].max()}  H4fvg {len(h4)} M15fvg {len(m15)}")
    grid=list(product(["long","short"],[4.0,12.0],["all","london","ny","overlap"],[10,20,30],[False,True],[2.0,3.0,4.0]))
    print(f"configs: {len(grid)}\n")
    rows=[]
    for direc,age,sess,sw,inside,tp in grid:
        sigs=gen_signals_fast(m5,h4,m15,direction=direc,fvg_max_age_h=age,session=sess,swing_lookback=sw,require_m15_inside_h4=inside)
        if len(sigs)<15: continue
        c=stats(sim(arr,sigs,tp,"close")); h=stats(sim(arr,sigs,tp,"honest"))
        if c is None or h is None: continue
        rows.append(dict(cfg=f"{direc[:1]}_a{int(age)}_{sess}_sw{sw}_in{int(inside)}_tp{tp}",n=c["n"],
                         pf_close=round(c["pf"],2),pf_honest=round(h["pf"],2),
                         net_close=round(c["net"],0),net_honest=round(h["net"],0),
                         wr_honest=round(h["wr"],0),posY_h=f"{h['posY']}/{h['tot']}",oos_h=round(h["oos"],2)))
    R=pd.DataFrame(rows); R.to_csv(Path(__file__).parent/"verify_honest_matrix.csv",index=False)
    print(f"scored {len(R)} configs")
    surv=R[(R.pf_honest>=1.3)&(R.n>=25)&(R.oos_h>=1.1)].sort_values("pf_honest",ascending=False)
    print(f"\n=== HONEST survivors (PF>=1.3, n>=25, OOS>=1.1): {len(surv)} ===")
    print(surv.head(25).to_string(index=False))
    print(f"\n=== close-based MIRAGES (close PF>=1.5 but honest PF<1.1): ===")
    mir=R[(R.pf_close>=1.5)&(R.pf_honest<1.1)]
    print(f"  {len(mir)} of {len(R)} configs. avg close PF={mir.pf_close.mean():.2f} -> honest PF={mir.pf_honest.mean():.2f}")


if __name__=="__main__":
    main()
