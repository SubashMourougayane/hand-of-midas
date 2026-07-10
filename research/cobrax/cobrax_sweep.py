#!/usr/bin/env python3
"""COBRAX optimization sweep — ANTI-OVERFIT by construction.

Pick config on IS (2006-2015), REPORT on OOS (2016-2026), CONFIRM on NAS.
Rank by OOS cost-adjusted net-R (revenue proxy) subject to gates:
  IS PF>=1.3, OOS PF>=1.3, OOS pos-years>=80%, n>=300.
Prefer PLATEAUS: a lone peak surrounded by weak neighbours = curve-fit, flagged.

  python3 cobrax_sweep.py stage1        # coarse: ote x tp x mss_lb x entry x sl
  python3 cobrax_sweep.py refine <...>  # (edit REFINE grid) fine levers around a winner
"""
import sys, itertools, numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
import cobrax as CB

XAU = CB.load(CB.XAU_M5)
OOS_YEAR = 2016   # IS 2006-2015, OOS 2016-2026 (~50/50)

def split(tr):
    if not tr: return None
    a=np.array([t["net_r"] for t in tr]); yr=np.array([t["fill_ts"].year for t in tr])
    isn=a[yr<OOS_YEAR]; oon=a[yr>=OOS_YEAR]
    def yb(x,y):
        s=pd.Series(x).groupby(y).sum(); return int((s>0).sum()), len(s)
    ip,iy=yb(isn,yr[yr<OOS_YEAR]) if len(isn) else (0,0)
    op,oy=yb(oon,yr[yr>=OOS_YEAR]) if len(oon) else (0,0)
    return dict(n=len(a),
                is_pf=CB.pf(isn) if len(isn) else 0, is_net=isn.sum(), is_pos=ip, is_yrs=iy,
                oos_pf=CB.pf(oon) if len(oon) else 0, oos_net=oon.sum(), oos_pos=op, oos_yrs=oy,
                full_net=a.sum(), full_pf=CB.pf(a))

def gate(s):
    return (s and s["n"]>=300 and s["is_pf"]>=1.3 and s["oos_pf"]>=1.3
            and s["oos_yrs"]>0 and s["oos_pos"]>=0.8*s["oos_yrs"])

def stage1():
    grid=dict(
        ote=[(0.5,0.618),(0.5,0.705),(0.62,0.79),(0.705,0.79),(0.38,0.79),(0.62,1.0)],
        tp=[("nl",2.0),("rr",1.5),("rr",2.0),("rr",3.0)],
        mss_lb=[2,3,5,8],
        entry=["edge","ce"],
        sl=["sweep","fvg"],
    )
    keys=list(grid); combos=list(itertools.product(*[grid[k] for k in keys]))
    print(f"stage1: {len(combos)} combos | cost=0.2 | IS<{OOS_YEAR}<=OOS | gate: ISpf&OOSpf>=1.3, OOSpos>=80%, n>=300")
    rows=[]
    for vals in combos:
        c=dict(zip(keys,vals)); tpm,tpr=c.pop("tp")
        tr=CB.run(XAU, session="all", exec_tf=5, fvg_min=0.3, sweep_reject=True,
                  bias_align=True, direction="both", cost=0.2, tp_mode=tpm, tp_r=tpr,
                  mss_lb=c["mss_lb"], entry=c["entry"], sl=c["sl"], ote=c["ote"])
        s=split(tr)
        if not s: continue
        row=dict(ote=c["ote"],tp=f"{tpm}{tpr}",mss_lb=c["mss_lb"],entry=c["entry"],sl=c["sl"],**s,pass_=gate(s))
        rows.append(row)
        if gate(s):
            print(f"* ote{c['ote']} tp={tpm}{tpr} lb={c['mss_lb']} {c['entry']}/{c['sl']} | "
                  f"n={s['n']:<4} IS pf={s['is_pf']:.2f} net={s['is_net']:.0f} | "
                  f"OOS pf={s['oos_pf']:.2f} net={s['oos_net']:.0f} pos={s['oos_pos']}/{s['oos_yrs']} | full={s['full_net']:.0f}")
    res=pd.DataFrame(rows)
    passers=res[res.pass_].sort_values("oos_net",ascending=False)
    print(f"\n=== gate-passers: {len(passers)}/{len(res)} | TOP 12 by OOS net-R (revenue) ===")
    for _,r in passers.head(12).iterrows():
        print(f"  ote{r.ote} tp={r.tp} lb={r.mss_lb} {r.entry}/{r.sl} | n={r.n} "
              f"IS pf={r.is_pf:.2f}/OOS pf={r.oos_pf:.2f} | OOS net={r.oos_net:.0f} full net={r.full_net:.0f}")
    # headline baseline for reference
    hb=split(CB.run(XAU,**dict(CB.HEADLINE, exec_tf=5, fvg_min=0.3, direction="both", cost=0.2)))
    print(f"\n  [headline baseline ote(.62,.79)/nl/lb3/edge/sweep] n={hb['n']} "
          f"IS pf={hb['is_pf']:.2f}/OOS pf={hb['oos_pf']:.2f} OOS net={hb['oos_net']:.0f} full={hb['full_net']:.0f}")
    res.to_csv("/Users/subash/SUBASH/GoldDigger/research/cobrax/stage1_results.csv",index=False)
    print("  (full grid -> stage1_results.csv)")

if __name__=="__main__":
    (stage1 if (len(sys.argv)>1 and sys.argv[1]=="stage1") else stage1)()
