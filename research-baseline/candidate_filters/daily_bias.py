"""Daily-bias + intraday-sentiment filter (post-hoc, causal).

BIAS features (all knowable at entry_ts, no look-ahead):
 A) prior-day bias: sign of prior COMPLETED day's return (close-open) and
    close position within prior-day range (close-low)/(high-low). Known at
    current day's open -> usable for any entry that day.
 B) intraday sentiment: current day's move from day-open to the LAST M5 bar
    CLOSED before entry_ts (day-so-far return). Strictly causal.

Test: does aligning trade direction WITH bias help, or AGAINST (mean-reversion)?
Fib V2 is mean-reversion -> counter-bias may be the winner.
"""
import _causal_lib as L
import numpy as np, pandas as pd

tr = L.load_trades()
m5 = L.load_m5()
d1 = L.resample_causal(m5, '1D')  # bar_open_ts, close_ts=open+1D
# prior-day return sign + close-in-range, shifted so it's the PRIOR completed day
d1 = d1.sort_values('bar_open_ts').reset_index(drop=True)
d1['ret'] = d1['close'] - d1['open']
d1['clr'] = (d1['close'] - d1['low']) / (d1['high'] - d1['low']).replace(0,np.nan)
d1['pd_ret'] = d1['ret'].shift(1)      # prior day's return
d1['pd_clr'] = d1['clr'].shift(1)      # prior day's close-in-range
# usable from current day's OPEN -> close_ts_for_use = bar_open_ts
d1['use_ts'] = d1['bar_open_ts']
d1u = d1.dropna(subset=['pd_ret']).reset_index(drop=True)

# attach prior-day bias causally: last day-open <= entry
uts = d1u['use_ts'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
ent = tr['entry_timestamp'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
idx = np.searchsorted(uts, ent, side='right') - 1
tr = tr.copy()
for col in ['pd_ret','pd_clr']:
    v = d1u[col].to_numpy(); out=np.full(len(tr),np.nan)
    ok = idx>=0; out[ok]=v[idx[ok]]; tr[col]=out
tr['pd_bull'] = (tr['pd_ret']>0).astype(int)

# intraday sentiment: day-open to last CLOSED M5 before entry
m5s = m5.copy()
m5s['day'] = m5s['timestamp'].dt.floor('1D')
day_open = m5s.groupby('day')['open'].first()
mts = (m5s['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None) + pd.Timedelta('5min')).to_numpy()  # close time
mcl = m5s['close'].to_numpy()
mday = m5s['day'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
j = np.searchsorted(mts, ent, side='right') - 1  # last M5 closed before entry
last_close = np.where(j>=0, mcl[np.clip(j,0,len(mcl)-1)], np.nan)
# day open for the entry's day
entry_day = tr['entry_timestamp'].dt.floor('1D')
tr['day_open'] = entry_day.map(lambda d: day_open.get(d, np.nan)).values
tr['intraday_ret'] = last_close - tr['day_open']
tr['intraday_bull'] = (tr['intraday_ret']>0).astype(int)

def stat(d,label):
    if len(d)==0: return f"{label:<34s} n=0"
    wr=100*(d.net_r>0).mean(); prof=d.loc[d.net_r>0,'net_r'].sum(); loss=-d.loc[d.net_r<=0,'net_r'].sum()
    pf=prof/loss if loss>0 else float('inf'); py,ty=L.yearly_positive(d)
    return f"{label:<34s} n={len(d):>6d} wr={wr:5.1f}% sumR={d.net_r.sum():>+8.1f} PF={pf:5.3f} posY={py}/{ty}"

base=tr.net_r.sum()
tr['long']=(tr.side>0).astype(int)
print("=== BASELINE ==="); print(stat(tr,'ALL'))

print("\n=== PRIOR-DAY BIAS ===")
print(stat(tr[tr.pd_bull==1],'prior-day BULL (any dir)'))
print(stat(tr[tr.pd_bull==0],'prior-day BEAR (any dir)'))
# align: long on bull day, short on bear day
align = tr[((tr.long==1)&(tr.pd_bull==1))|((tr.long==0)&(tr.pd_bull==0))]
counter = tr[((tr.long==1)&(tr.pd_bull==0))|((tr.long==0)&(tr.pd_bull==1))]
print(stat(align,'ALIGN w/ prior-day bias'))
print(stat(counter,'COUNTER prior-day bias'))
print(f"  delta-R align:   {align.net_r.sum()-base:>+8.1f}")
print(f"  delta-R counter: {counter.net_r.sum()-base:>+8.1f}")

print("\n=== INTRADAY SENTIMENT (day-so-far, causal) ===")
va=tr.dropna(subset=['intraday_ret'])
ial = va[((va.long==1)&(va.intraday_bull==1))|((va.long==0)&(va.intraday_bull==0))]
ico = va[((va.long==1)&(va.intraday_bull==0))|((va.long==0)&(va.intraday_bull==1))]
print(stat(ial,'ALIGN w/ intraday sentiment'))
print(stat(ico,'COUNTER intraday sentiment'))
print(f"  delta-R align:   {ial.net_r.sum()-base:>+8.1f} (dropped {len(tr)-len(ial)})")
print(f"  delta-R counter: {ico.net_r.sum()-base:>+8.1f} (dropped {len(tr)-len(ico)})")

print("\n=== prior-day close-in-range quintiles (pd_clr) ===")
for r in L.quintile_table(tr,'pd_clr'):
    print(f"  {r['label']} n={r['n']:>6d} wr={r['wr']:.1f}% sumR={r['sum_r']:>+8.1f} PF={r['pf']:.3f} rng={r['range']}")
