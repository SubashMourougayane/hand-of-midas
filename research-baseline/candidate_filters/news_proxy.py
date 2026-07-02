"""News-window proxy filter (post-hoc, causal — date-rule based, no calendar feed).

We have NO economic-calendar data. But recurring high-impact events fire on
KNOWN dates/times, fully knowable in advance (causal):
  - NFP: first Friday of month, US release 13:30 UTC (~08:30 ET)
  - US data window: weekday 13:30 UTC generally (CPI, retail sales etc cluster here)

Test: do entries in/around these windows behave differently? Skip-filter + the
raw bucket edge. All date-derived -> zero look-ahead.
"""
import _causal_lib as L
import numpy as np, pandas as pd

tr = L.load_trades().copy()
ts = tr['entry_timestamp']
tr['dow'] = ts.dt.dayofweek           # 0=Mon .. 4=Fri
tr['dom'] = ts.dt.day
tr['utc_hr'] = ts.dt.hour
tr['utc_min'] = ts.dt.minute
# first Friday = Friday with dom<=7
tr['is_first_fri'] = ((tr.dow==4)&(tr.dom<=7)).astype(int)
# NFP release window: first-Fri 13:00-15:00 UTC
tr['nfp_win'] = ((tr.is_first_fri==1)&(tr.utc_hr.between(13,14))).astype(int)
# broad US-data window: any weekday 13:00-15:00 UTC
tr['us_data_win'] = ((tr.dow<=4)&(tr.utc_hr.between(13,14))).astype(int)
# whole first-Friday (all day)
tr['first_fri_day']=tr['is_first_fri']

def stat(d,label):
    if len(d)==0: return f"{label:<34s} n=0"
    wr=100*(d.net_r>0).mean(); prof=d.loc[d.net_r>0,'net_r'].sum(); loss=-d.loc[d.net_r<=0,'net_r'].sum()
    pf=prof/loss if loss>0 else float('inf'); py,ty=L.yearly_positive(d)
    return f"{label:<34s} n={len(d):>6d} wr={wr:5.1f}% avgR={d.net_r.mean():+.4f} sumR={d.net_r.sum():>+8.1f} PF={pf:5.3f} posY={py}/{ty}"

base=tr.net_r.sum()
print("=== BASELINE ==="); print(stat(tr,'ALL'))
print("\n=== NEWS-WINDOW BUCKETS ===")
print(stat(tr[tr.nfp_win==1],'NFP window (1st-Fri 13-15z)'))
print(stat(tr[tr.first_fri_day==1],'first-Friday (whole day)'))
print(stat(tr[tr.us_data_win==1],'US-data window (wkday 13-15z)'))
print(stat(tr[tr.us_data_win==0],'outside US-data window'))
print("\n=== SKIP-FILTERS (keep=allowed) delta-R ===")
for lab,mask in [('skip NFP window',tr.nfp_win==0),
                 ('skip first-Fri all day',tr.first_fri_day==0),
                 ('skip US-data window',tr.us_data_win==0)]:
    sub=tr[mask]; print(f"  {lab:<26s} keepN={len(sub):>6d} sumR={sub.net_r.sum():+.1f} delta={sub.net_r.sum()-base:+.1f}")

print("\n=== FAIR sizing test: US-data window up, rest down (leverage-neutral) ===")
w_up = tr.us_data_win.values
# equal-budget: size up window, size down rest so avg weight ~1.0
import numpy as np
for up,dn in [(2.0,1.0),(2.0,0.5),(1.5,0.94)]:
    w=np.where(w_up==1,up,dn)
    avg_w=w.mean()
    sr=(tr.net_r.values*w).sum()
    # normalize to equal total leverage vs flat
    sr_norm=sr/avg_w
    g=tr.assign(x=tr.net_r.values*w).groupby('year')['x'].sum(); py=int((g>0).sum())
    print(f"  up{up}/dn{dn}: rawSumR={sr:+.1f} avgLev={avg_w:.3f} leverageNORM={sr_norm:+.1f} vs flat 8279  posY={py}/21")
