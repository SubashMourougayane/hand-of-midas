"""US-data-window SIZING gauntlet — the one unrefuted lead.

Hypothesis: entries in the 13-15 UTC window (London/NY overlap + US data releases)
have a genuinely higher per-trade R-edge. Size those UP, rest normal. This is a
SIZING overlay (not a filter — keeps ALL trades), leverage-neutral tested.

BIBLE: window = ny_hr-based, knowable at entry_ts (pure time). No look-ahead.
All post-hoc on baseline b6604240. Zero strategy/BT/live edits.

3-PHASE GAUNTLET:
  Phase 1 CAUSALITY — window flag is pure entry-time, trivially causal. Confirm.
  Phase 2 STRESS    — is the avg-R edge real? bootstrap, permutation, IS/OOS,
                      per-era, sample size, leverage-neutral uplift.
  Phase 3 ADVERSARIAL — 3 lenses: (a) is it just NY-hour data-mining? test
                      neighboring windows; (b) post-2020 regime survival;
                      (c) leverage-neutral (does uplift survive equal-risk-budget?).
"""
import sys
sys.path.insert(0,"/Users/subash/SUBASH/GoldDigger/research-baseline/candidate_filters")
import _causal_lib as L
import numpy as np, pandas as pd

tr=L.load_trades()
tr['nyh']=tr['ny_hr']
BASE=float(tr.net_r.sum())
r_all=tr.net_r.values

def edge(mask,label):
    d=tr[mask]; o=tr[~mask]
    print(f"  {label:<24s} IN: n={len(d):>6d} avgR={d.net_r.mean():+.4f} sumR={d.net_r.sum():+8.1f} | OUT avgR={o.net_r.mean():+.4f}")
    return d.net_r.mean(), o.net_r.mean()

print("=== PHASE 1: CAUSALITY ===")
print("  Window = ny_hr in [13,14] (13:00-15:00 UTC-equiv NY session). Pure entry-time flag.")
print("  Knowable at entry_ts: YES (ny_hr derived from bar.timestamp). No look-ahead. PASS.\n")

print("=== PHASE 2: STRESS ===")
win=tr['nyh'].between(13,14).values
ain,aout=edge(win,'ny_hr 13-14')
# bootstrap on window trades
dwin=tr[win]
p_neg=L.bootstrap_p_neg(dwin.net_r.values,5000)
p_perm=L.permutation_p(dwin.net_r.values,1000)
py,ty=L.yearly_positive(dwin)
print(f"  window bootstrap P(net<0)={p_neg:.4f} permutation_p={p_perm:.4f} posYears={py}/{ty}")
# IS/OOS
is_=dwin[dwin.year<=2018]; oos=dwin[dwin.year>=2019]
print(f"  IS(<=2018) avgR={is_.net_r.mean():+.4f} n={len(is_)} | OOS(>=2019) avgR={oos.net_r.mean():+.4f} n={len(oos)}")
# random-subsample: is window avgR beyond drawing len(win) random trades?
rng=np.random.default_rng(42); n=len(dwin); draws=np.array([r_all[rng.integers(0,len(r_all),n)].mean() for _ in range(2000)])
z=(dwin.net_r.mean()-draws.mean())/draws.std()
print(f"  window avgR {dwin.net_r.mean():+.4f} vs random-subsample mean {draws.mean():+.4f} (z={z:+.2f} sigma)")

print("\n=== PHASE 3: ADVERSARIAL ===")
# Lens A: neighboring windows (data-mining check)
print("  [Lens A] neighboring NY-hour windows (is 13-14 cherry-picked?):")
for lo,hi in [(11,12),(12,13),(13,14),(14,15),(15,16),(12,14),(11,14)]:
    m=tr['nyh'].between(lo,hi).values; d=tr[m]
    print(f"    ny_hr {lo}-{hi}: n={len(d):>6d} avgR={d.net_r.mean():+.4f}")
# Lens B: per-era
print("  [Lens B] per-era window edge (post-2020 survival):")
for lo,hi,lab in [(2006,2012,'A'),(2013,2019,'B'),(2020,2026,'C')]:
    e=tr[(tr.year>=lo)&(tr.year<=hi)]; ew=e[e['nyh'].between(13,14)]; eo=e[~e['nyh'].between(13,14)]
    lift=ew.net_r.mean()-eo.net_r.mean() if len(ew)>0 else 0
    print(f"    era {lab} {lo}-{hi}: win avgR={ew.net_r.mean():+.4f} (n={len(ew)}) vs off {eo.net_r.mean():+.4f} | lift={lift:+.4f}")
# Lens C: leverage-neutral uplift
print("  [Lens C] leverage-neutral sizing uplift (equal total risk budget):")
for up,dn in [(2.0,1.0),(1.5,1.0),(2.0,0.9),(1.5,0.95)]:
    w=np.where(win,up,dn); avg=w.mean(); sr=(r_all*w).sum(); norm=sr/avg
    upl=100*(norm/BASE-1)
    g=pd.Series(r_all*w).groupby(tr.year.values).sum(); pyw=int((g>0).sum())
    print(f"    up{up}/dn{dn}: leverageNORM sumR={norm:+.1f} uplift={upl:+.2f}% posY={pyw}/21")

print("\n=== VERDICT ===")
# window must: real edge (z>2), post-2020 survives (era C lift>0), leverage-neutral uplift>0
eC=tr[(tr.year>=2020)]; eCw=eC[eC['nyh'].between(13,14)]; eCo=eC[~eC['nyh'].between(13,14)]
c_lift=eCw.net_r.mean()-eCo.net_r.mean()
w15=np.where(win,1.5,0.95); norm15=(r_all*w15).sum()/w15.mean(); upl15=100*(norm15/BASE-1)
print(f"  edge z-score: {z:+.2f} (need >2)")
print(f"  post-2020 lift: {c_lift:+.4f} (need >0)")
print(f"  leverage-neutral uplift @1.5x/0.95: {upl15:+.2f}% (need >0)")
verdict = 'SHIP-CANDIDATE' if (z>2 and c_lift>0 and upl15>0) else 'WEAK/REJECT'
print(f"  >>> {verdict}")
