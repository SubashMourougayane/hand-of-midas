"""Concurrency/overlap filter research (post-hoc, causal).

At each trade's entry_ts T, reconstruct what positions were OPEN:
  opened before T (entry_ts_j < T) AND still open at T (exit_ts_j > T).
This is knowable at live-time T (you observe open positions). No look-ahead —
uses only the fact of concurrency, not any future outcome.

Buckets each trade by concurrency state at its own entry, then tests filters:
  - already same-direction open (stacking)
  - already opposite-direction open (hedge)
  - flat (no open position)
Compute PF/WR/net-R/pos-years per bucket + candidate skip-filters.
"""
import _causal_lib as L
import numpy as np, pandas as pd

tr = L.load_trades().sort_values('entry_timestamp').reset_index(drop=True)
ent = tr['entry_timestamp'].values
ext = tr['exit_timestamp'].values
side = tr['side'].values
n = len(tr)

# For each trade i, look at trades j that opened before i and are still open at ent[i]
same_open = np.zeros(n, int)
opp_open  = np.zeros(n, int)
for i in range(n):
    Ti = ent[i]
    # j opened strictly before Ti, and exit strictly after Ti (still open at Ti)
    mask = (ent < Ti) & (ext > Ti)
    if mask.any():
        sd = side[mask]
        same_open[i] = int((sd == side[i]).sum())
        opp_open[i]  = int((sd == -side[i]).sum())
tr['same_open'] = same_open
tr['opp_open']  = opp_open
tr['any_open']  = ((same_open+opp_open) > 0).astype(int)
tr['state'] = np.where((same_open>0)&(opp_open>0),'both',
              np.where(same_open>0,'same_only',
              np.where(opp_open>0,'opp_only','flat')))

def stat(d,label):
    if len(d)==0: return f"{label:<28s} n=0"
    wr=100*(d.net_r>0).mean()
    prof=d.loc[d.net_r>0,'net_r'].sum(); loss=-d.loc[d.net_r<=0,'net_r'].sum()
    pf=prof/loss if loss>0 else float('inf')
    py,ty=L.yearly_positive(d)
    return f"{label:<28s} n={len(d):>6d} wr={wr:5.1f}% sumR={d.net_r.sum():>+8.1f} PF={pf:5.3f} posY={py}/{ty}"

print("=== BASELINE ==="); print(stat(tr,'ALL'))
print("\n=== BY CONCURRENCY STATE AT ENTRY ===")
for s in ['flat','opp_only','same_only','both']:
    print(stat(tr[tr.state==s], s))
print("\n=== SKIP-FILTERS (keep = trade allowed) ===")
print(stat(tr[tr.any_open==0], 'skip if ANY open (flat only)'))
print(stat(tr[tr.opp_open==0], 'skip if OPPOSITE open'))
print(stat(tr[tr.same_open==0],'skip if SAME-dir open'))
# delta-R vs baseline for each keep-filter
base=tr.net_r.sum()
for lab,sub in [('flat_only',tr[tr.any_open==0]),('no_opp',tr[tr.opp_open==0]),('no_same',tr[tr.same_open==0])]:
    print(f"  delta-R {lab:<12s}: {sub.net_r.sum()-base:>+8.1f} (dropped {n-len(sub)} trades)")

# split by leg too
print("\n=== opp_only state BY LEG ===")
for leg in ['intraday_a_long','intraday_d_short']:
    print(stat(tr[(tr.state=='opp_only')&(tr.leg==leg)], leg))
