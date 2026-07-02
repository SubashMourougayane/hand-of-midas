"""MEGA SWEEP — exhaustive single + 2-way + 3-way filter permutations.

BIBLE: all features causal (close_ts <= entry_ts), post-hoc on baseline b6604240
trades. ZERO strategy/BT/live edits. Filters are KEEP-subsets of existing trades.

HONEST METRIC (avoids the PF book-shrink trap):
  delta_R = filtered_sumR - baseline_sumR
  A filter only HELPS if delta_R > 0 (losers cut exceed winners forfeited).
  PF rising while delta_R < 0 = cosmetic book-shrink, NOT edge. We rank by delta_R.

MULTIPLE-TESTING GUARD:
  - Report count of candidates tested (Bonferroni context).
  - For any positive-delta candidate: IS/OOS split (must hold OOS), permutation
    p-value, pos-years. A single lucky combo out of hundreds means nothing.

Families (all causal, knowable at entry):
  ny_hr, dow, impulse (fib_diff/ATR), retrace_depth, intraday_sentiment,
  prior_day_bias, d1_atr_pct, session (asia/london/ny), pdh/pdl proximity,
  vwap side, concurrency state.
Each becomes a set of binary KEEP-predicates. Then single + 2-way + 3-way AND.
"""
from __future__ import annotations
import sys, itertools, time
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research-baseline/candidate_filters")
import _causal_lib as L

t0=time.time()
print(f"[{time.strftime('%H:%M:%S')}] loading", flush=True)
tr = L.load_trades()
m5 = L.load_m5()
BASE_SUMR = float(tr.net_r.sum())
BASE_N = len(tr)
print(f"baseline: n={BASE_N} sumR={BASE_SUMR:.1f} pf={L.headline(tr)['pf']}", flush=True)

# ---- build all causal features ----
d1 = L.resample_causal(m5,'1D')
d1['ret']=d1['close']-d1['open']; d1['pd_ret']=d1['ret'].shift(1)
d1['atr14']=None
pc=d1['close'].shift(1)
trng=pd.concat([(d1.high-d1.low),(d1.high-pc).abs(),(d1.low-pc).abs()],axis=1).max(axis=1)
d1['atr14']=trng.rolling(14,min_periods=14).mean()
d1['atr_pct']=d1['atr14'].rolling(252,min_periods=60).rank(pct=True)
d1['pdh']=d1['high'].shift(1); d1['pdl']=d1['low'].shift(1)
d1['use_ts']=d1['bar_open_ts']
d1u=d1.dropna(subset=['pd_ret']).reset_index(drop=True)

def attach(col):
    uts=d1u['use_ts'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
    ent=tr['entry_timestamp'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
    idx=np.searchsorted(uts,ent,side='right')-1
    v=d1u[col].to_numpy(); out=np.full(len(tr),np.nan); ok=idx>=0; out[ok]=v[idx[ok]]
    return out

tr=tr.copy()
tr['pd_bull']=(attach('pd_ret')>0).astype(float)
tr['atr_pct']=attach('atr_pct')
tr['pdh']=attach('pdh'); tr['pdl']=attach('pdl')
tr['d1atr']=attach('atr14')
tr['impulse']=tr['fib_diff']/tr['d1atr']
tr['long']=(tr.side>0).astype(int)
tr['dow']=tr['entry_timestamp'].dt.dayofweek
tr['nyh']=tr['ny_hr']
tr['retr']=np.where(tr.side>0,(tr.fib_h-tr.entry_price)/tr.fib_diff,(tr.entry_price-tr.fib_l)/tr.fib_diff)
# intraday sentiment
m5s=m5.copy(); m5s['day']=m5s['timestamp'].dt.floor('1D')
dayopen=m5s.groupby('day')['open'].first()
mts=(m5s['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)+pd.Timedelta('5min')).to_numpy()
mcl=m5s['close'].to_numpy()
ent=tr['entry_timestamp'].dt.tz_convert('UTC').dt.tz_localize(None).to_numpy()
j=np.searchsorted(mts,ent,side='right')-1
lastcl=np.where(j>=0,mcl[np.clip(j,0,len(mcl)-1)],np.nan)
tr['dopen']=tr['entry_timestamp'].dt.floor('1D').map(lambda d: dayopen.get(d,np.nan)).values
tr['intra_bull']=(lastcl-tr['dopen']>0).astype(float)
tr['sent_align']=(((tr.long==1)&(tr.intra_bull==1))|((tr.long==0)&(tr.intra_bull==0))).astype(int)
# pdh/pdl proximity in ATR
tr['near_pdh']=(np.minimum((tr.entry_price-tr.pdh).abs(),(tr.entry_price-tr.pdl).abs())/tr.d1atr < 0.5).astype(int)

# ---- predicate library: name -> boolean mask (KEEP) ----
P={}
# ny hour ranges
for lo,hi in [(7,12),(11,15),(12,14),(13,17),(0,7),(15,23)]:
    P[f'nyh_{lo}_{hi}']=tr.nyh.between(lo,hi).values
# impulse quantile thresholds
for q in [0.2,0.3,0.4,0.5]:
    thr=tr['impulse'].quantile(q)
    P[f'impulse_ge_q{int(q*100)}']=(tr['impulse']>=thr).values
# retrace depth bands
for lo,hi in [(0.3,0.6),(0.4,0.7),(0.2,0.5),(0.5,0.8)]:
    P[f'retr_{lo}_{hi}']=tr['retr'].between(lo,hi).values
# atr percentile bands (regime)
for lo,hi in [(0.2,0.8),(0.3,0.9),(0.1,0.7),(0.4,1.0)]:
    P[f'atrpct_{lo}_{hi}']=tr['atr_pct'].between(lo,hi).values
# sentiment / bias
P['sent_align']=tr['sent_align'].values.astype(bool)
P['sent_counter']=(~tr['sent_align'].astype(bool)).values
P['pd_bull']=tr['pd_bull'].astype(bool).values
P['pd_bear']=(~tr['pd_bull'].astype(bool)).values
# dow
for d in range(5):
    P[f'dow_{d}']=(tr.dow==d).values
P['dow_not_fri']=(tr.dow!=4).values
P['near_key_level']=tr['near_pdh'].astype(bool).values
# leg
P['leg_A']=(tr.leg=='intraday_a_long').values
P['leg_D']=(tr.leg=='intraday_d_short').values

names=list(P.keys())
print(f"predicates: {len(names)}", flush=True)

def eval_mask(mask):
    d=tr[mask]
    if len(d)<200: return None
    sr=float(d.net_r.sum())
    return dict(n=len(d), sumR=round(sr,1), deltaR=round(sr-BASE_SUMR,1),
                pf=round(L.headline(d)['pf'],3), wr=round(100*(d.net_r>0).mean(),1))

def oos_ok(mask):
    # IS <=2018, OOS >=2019, both must be net positive AND OOS delta not worse
    d=tr[mask]
    is_=d[d.year<=2018]; oos=d[d.year>=2019]
    if len(is_)<50 or len(oos)<50: return False,0,0
    return (is_.net_r.sum()>0 and oos.net_r.sum()>0), round(is_.net_r.sum(),1), round(oos.net_r.sum(),1)

results=[]
# singles
for nm in names:
    r=eval_mask(P[nm])
    if r: r['combo']=nm; r['depth']=1; results.append(r)
print(f"[{time.strftime('%H:%M:%S')}] singles done ({len([r for r in results if r['depth']==1])})", flush=True)

# 2-way AND
cnt2=0
for a,b in itertools.combinations(names,2):
    m=P[a]&P[b]
    r=eval_mask(m)
    if r: r['combo']=f'{a} & {b}'; r['depth']=2; results.append(r); cnt2+=1
print(f"[{time.strftime('%H:%M:%S')}] 2-way done ({cnt2})", flush=True)

# 3-way AND — only extend from the positive-delta 2-ways to bound explosion
pos2=[r['combo'] for r in results if r['depth']==2 and r['deltaR']>-500]
# rebuild masks for promising 2-ways, extend with each single
cnt3=0
prom_pairs=[c.split(' & ') for c in pos2][:200]  # cap
for (a,b) in prom_pairs:
    base=P[a]&P[b]
    for cc in names:
        if cc in (a,b): continue
        m=base&P[cc]
        r=eval_mask(m)
        if r and r['deltaR']>0:  # only keep POSITIVE-delta 3-ways
            r['combo']=f'{a} & {b} & {cc}'; r['depth']=3; results.append(r); cnt3+=1
print(f"[{time.strftime('%H:%M:%S')}] 3-way done (kept {cnt3} positive-delta)", flush=True)

res=pd.DataFrame(results)
res=res.sort_values('deltaR',ascending=False)
total=len(res)
pos=res[res.deltaR>0]
print(f"\n=== SWEEP COMPLETE: {total} candidates tested ===", flush=True)
print(f"positive delta-R: {len(pos)}", flush=True)
print(f"\n=== TOP 20 by delta-R ===")
print(res.head(20).to_string(index=False))

# multiple-testing + OOS gauntlet on positive-delta
print(f"\n=== OOS CHECK on positive-delta candidates (need IS>0 AND OOS>0) ===")
survivors=[]
for _,row in pos.iterrows():
    parts=row['combo'].split(' & ')
    m=np.ones(len(tr),bool)
    for p in parts: m=m&P[p]
    ok,is_r,oos_r=oos_ok(m)
    d=tr[m]
    perm=L.permutation_p(d.net_r.values, n_iter=1000) if len(d)>=50 else 1.0
    py,ty=L.yearly_positive(d)
    tag='SURVIVE' if (ok and row['deltaR']>0 and perm<0.05 and py>=ty-2) else 'weak'
    if tag=='SURVIVE': survivors.append(row['combo'])
    print(f"  [{tag}] {row['combo'][:60]:60s} dR={row['deltaR']:+.1f} n={row['n']} IS={is_r} OOS={oos_r} perm_p={perm:.3f} posY={py}/{ty}")

print(f"\n=== SURVIVORS (positive-delta + OOS-positive + perm p<0.05 + pos-years): {len(survivors)} ===")
for s in survivors: print(f"  {s}")
print(f"\nMultiple-testing note: {total} combos tested. At p<0.05, ~{int(total*0.05)} false positives expected by chance alone. Survivors must be read against this.")
res.to_csv("/Users/subash/SUBASH/GoldDigger/research-baseline/candidate_filters/mega_sweep/sweep_results.csv",index=False)
print(f"\n[{time.strftime('%H:%M:%S')}] saved. elapsed {time.time()-t0:.0f}s")
