"""Sizing-lever quantification (post-hoc, causal, keeps ALL trades — no filter).

Idea: don't SKIP any trade. Just size UP the high-quality/aligned trades and
size DOWN the low-quality ones. Same trade count, same entries. Only the R
weight per trade changes. This is the ONLY direction showing positive signal.

Two aligned signals (both causal, knowable at entry):
  1. intraday sentiment align: trade direction matches day-so-far move
  2. mid-session window: ny_hr in [11..14] (London/NY overlap)

Baseline = flat 1.0x every trade. Overlay = multiplier by quality bucket.
Report weighted net-R vs flat, PF unchanged (weighting doesn't change per-trade
win/loss sign), pos-years. Key metric: weighted_sumR / flat_sumR uplift.
"""
import _causal_lib as L
import numpy as np, pandas as pd

tr = L.load_trades()
m5 = L.load_m5()

# intraday sentiment (day-open -> last M5 close before entry)
m5s = m5.copy(); m5s['day']=m5s['timestamp'].dt.floor('1D')
day_open = m5s.groupby('day')['open'].first()
mts=(m5s['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)+pd.Timedelta('5min')).to_numpy()
mcl=m5s['close'].to_numpy()
ent=tr['entry_timestamp'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
j=np.searchsorted(mts,ent,side='right')-1
last_close=np.where(j>=0,mcl[np.clip(j,0,len(mcl)-1)],np.nan)
tr=tr.copy()
tr['day_open']=tr['entry_timestamp'].dt.floor('1D').map(lambda d: day_open.get(d,np.nan)).values
tr['intra_ret']=last_close-tr['day_open']
tr['intra_bull']=(tr['intra_ret']>0).astype(int)
tr['long']=(tr.side>0).astype(int)
tr['sent_align']=(((tr.long==1)&(tr.intra_bull==1))|((tr.long==0)&(tr.intra_bull==0))).astype(int)
# ny_hr mid-session
tr['mid']=tr['ny_hr'].between(11,14).astype(int)

def wsum(w): return float((tr.net_r*w).sum())
def wstats(w,label):
    wr=100*(tr.net_r>0).mean()  # unchanged by weight
    sr=wsum(w)
    # pos years weighted
    g=tr.assign(wr=tr.net_r*w).groupby('year')['wr'].sum()
    py=int((g>0).sum()); ty=len(g)
    return f"{label:<40s} sumR(wtd)={sr:>+9.1f}  posY={py}/{ty}"

flat=np.ones(len(tr))
print("=== FLAT baseline (1.0x all) ===")
print(wstats(flat,'flat 1.0x'), f"  (raw sumR={tr.net_r.sum():+.1f})")

print("\n=== SENTIMENT-ALIGN sizing overlays (keep all trades) ===")
for up,dn in [(1.25,0.75),(1.5,0.5),(1.5,1.0),(2.0,0.5)]:
    w=np.where(tr.sent_align==1,up,dn)
    upl=100*(wsum(w)/tr.net_r.sum()-1)
    print(wstats(w,f'align {up}x / counter {dn}x')+f"  uplift={upl:+.1f}% vs flat")

print("\n=== MID-SESSION sizing overlays ===")
for up,dn in [(1.5,1.0),(2.0,1.0),(2.0,0.5)]:
    w=np.where(tr['mid']==1,up,dn)
    upl=100*(wsum(w)/tr.net_r.sum()-1)
    print(wstats(w,f'mid {up}x / off {dn}x')+f"  uplift={upl:+.1f}% vs flat")

print("\n=== COMBINED (align AND mid = full size) ===")
for spec in [((2.0,1.0,0.5)),]:
    hi,mi,lo=spec
    w=np.where((tr.sent_align==1)&(tr['mid']==1),hi,
      np.where((tr.sent_align==1)|(tr['mid']==1),mi,lo))
    upl=100*(wsum(w)/tr.net_r.sum()-1)
    print(wstats(w,f'both={hi}x one={mi}x none={lo}x')+f"  uplift={upl:+.1f}%")

print("\n=== the underlying edge (avg net-R per trade by bucket) ===")
for lab,mask in [('sent_align',tr.sent_align==1),('sent_counter',tr.sent_align==0),
                 ('mid_session',tr['mid']==1),('off_session',tr['mid']==0),
                 ('align&mid',(tr.sent_align==1)&(tr['mid']==1)),
                 ('counter&off',(tr.sent_align==0)&(tr['mid']==0))]:
    d=tr[mask]; print(f"  {lab:<16s} n={len(d):>6d} avgR={d.net_r.mean():+.4f} sumR={d.net_r.sum():+.1f}")
