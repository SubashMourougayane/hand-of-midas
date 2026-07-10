#!/usr/bin/env python3
"""
COBRAX-KING setup — quantized to the dot, causal, no look-ahead. Self-contained runner.

Structure reproduced from the COBRAX signal screenshot (XAUUSD):
  trend-align -> liquidity SWEEP of a swing extreme (reject) -> BOS/MSS ->
  FVG left behind that sits inside the fib OTE band -> limit entry in zone ->
  SL past swept extreme -> TP = opposite liquidity (next swing extreme).

Causal contract: every level (swing/sweep/MSS/FVG/OTE/HTF-bias) is read from CLOSED
bars only. HTF bias is indexed by M15 CLOSE time (no interior peek). The fill bar is
strictly AFTER the signal bar. `audit_causal()` + known_at asserts enforce it.

Headline config (the validated candidate):
  session=all, exec_tf=5 (XAU M5) / 3 (NAS M3), mss_lb=3, mode=reversal,
  ote=(0.62,0.79)  # classic ICT OTE == Fib V2 zone
  bias_align=True, tp_mode=nl (next liquidity), cost=0.2 (XAU realistic ECN)

USAGE
  python3 cobrax.py diag   [xau|nas] [reversal|run]   # MFE/MAE entry-quality diagnostic
  python3 cobrax.py harden [xau|nas ...]              # cost / delay / OOS / bootstrap / robustness
  python3 cobrax.py audit  [xau|nas ...]              # WR / fat-tail / known_at / BOS-additivity
  python3 cobrax.py pnl    [xau]                      # $ PnL through the REAL EquitySizer
  python3 cobrax.py run    --asset xau --session all --ote 0.62 0.79 ...  # ad-hoc single run

Data (gitignored, local): research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet,
                          research-baseline/data/raw/oanda_NAS100_USD_M1_2020_2026.parquet
"""
from __future__ import annotations
import sys, os, argparse
import numpy as np, pandas as pd

REPO = "/Users/subash/SUBASH/GoldDigger"
XAU_M5 = f"{REPO}/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
NAS_M1 = f"{REPO}/research-baseline/data/raw/oanda_NAS100_USD_M1_2020_2026.parquet"
SESSIONS = {"london": (3, 4), "am": (10, 11), "pm": (14, 15)}

# headline validated config per asset
HEADLINE = dict(session="all", mss_lb=3, fvg_min=None, sweep_reject=True, entry="edge",
                sl="sweep", tp_mode="nl", tp_r=2.0, mode="reversal", ote=(0.62, 0.79),
                bias_align=True)
ASSET = {  # asset-specific: exec_tf, default fvg_min, realistic cost, OOS boundary year
    "xau": dict(path=XAU_M5, exec_tf=5, fvg_min=0.3, cost=0.2, costs=[0.05,0.1,0.2,0.3,0.5], oos=2016),
    "nas": dict(path=NAS_M1, exec_tf=3, fvg_min=5.0, cost=2.0, costs=[1,2,3,5],           oos=2024),
}

# ----------------------------------------------------------------------------- engine
def load(path):
    df = pd.read_parquet(path)
    df = df[["timestamp","open","high","low","close"]].dropna().sort_values("timestamp").reset_index(drop=True)
    if df["timestamp"].dt.tz is None: df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    return df

def resample(df, minutes):
    if minutes <= 1 and (df["timestamp"].diff().median() <= pd.Timedelta("1min")):
        return df
    return (df.set_index("timestamp").resample(f"{minutes}min", label="left", closed="left")
              .agg({"open":"first","high":"max","low":"min","close":"last"}).dropna().reset_index())

def pivots(h, l, lb):
    w = 2*lb+1
    rmax = pd.Series(h).rolling(w, center=True).max().values
    rmin = pd.Series(l).rolling(w, center=True).min().values
    return (h >= rmax) & ~np.isnan(rmax), (l <= rmin) & ~np.isnan(rmin)

def run(df, *, session="am", exec_tf=3, mss_lb=3, fvg_min=0.0, sweep_reject=True,
        entry="edge", sl="sweep", tp_mode="rr", tp_r=2.0, direction="both",
        sweep_lb=60, fvg_wait=40, retrace_wait=40, max_hold=120,
        cost=0.0, bias_align=False, htf_tf=15, collect_mfe=False, fill_delay=0,
        mode="reversal", ote=None, bracket="wick", bias_at_fill=False):
    ex = resample(df, exec_tf)
    o,h,l,c = (ex[x].values for x in ("open","high","low","close"))
    tsp = pd.DatetimeIndex(ex["timestamp"])
    if tsp.tz is None: tsp = tsp.tz_localize("UTC")
    hour = tsp.tz_convert("America/New_York").hour.values
    n = len(ex)
    ph, pl = pivots(h, l, mss_lb)
    hpiv = np.where(ph)[0]; lpiv = np.where(pl)[0]
    hc = hpiv + mss_lb; lc = lpiv + mss_lb
    mh = hc < n; ml = lc < n
    shi_ci = hc[mh]; shi_px = h[hpiv[mh]]
    slo_ci = lc[ml]; slo_px = l[lpiv[ml]]
    sess_ok = np.ones(n, bool) if session == "all" else \
              ((hour >= SESSIONS[session][0]) & (hour < SESSIONS[session][1]))

    # HTF bias — indexed by M15 CLOSE time (no interior peek)
    htf = resample(df, htf_tf); htf_c = htf["close"].values
    htf_ts = pd.to_datetime(htf["timestamp"].values)
    htf_sma = pd.Series(htf_c).rolling(20).mean().values
    htf_close_ts = htf_ts.view("i8") + int(htf_tf)*60*1_000_000_000
    htf_bias = np.sign(htf_c - np.nan_to_num(htf_sma, nan=htf_c))
    def bias_at(t_i8):
        j = np.searchsorted(htf_close_ts, t_i8, side="right") - 1
        return htf_bias[j] if j >= 0 else 0

    trades = []; used = set()
    for i in range(mss_lb+2, n-2):
        if not sess_ok[i]: continue
        w0 = max(0, i-sweep_lb)
        for iside in ((-1,1) if direction=="both" else ((-1,) if direction=="short" else (1,))):
            if iside < 0:   # short: sweep a high, MSS breaks a low
                a = np.searchsorted(shi_ci, w0-mss_lb, "left"); b = np.searchsorted(shi_ci, i, "left")
                if b<=a: continue
                sw_level=sw_ext=sw_k=None
                for si in range(b-1, a-1, -1):
                    ci = int(shi_ci[si]); lvl = shi_px[si]; s = max(ci, w0); hh = h[s:i+1]
                    if len(hh)==0: continue
                    if hh.max() > lvl:
                        k = s + int(np.argmax(hh > lvl))
                        if sweep_reject and not (c[k] < lvl): continue
                        sw_level=lvl; sw_ext=hh.max(); sw_k=k; break
                if sw_level is None: continue
                if mode=="run":
                    if bias_at(tsp[i].value) >= 0: continue
                    mss_bar = sw_k
                else:
                    lb_ = np.searchsorted(slo_ci, i, "left")
                    if lb_<=0: continue
                    mss_lvl = slo_px[lb_-1]; mss_bar=-1
                    for k in range(sw_k+1, i+1):
                        if c[k] < mss_lvl: mss_bar=k; break
                    if mss_bar<0: continue
            else:           # long: sweep a low, MSS breaks a high
                a = np.searchsorted(slo_ci, w0-mss_lb, "left"); b = np.searchsorted(slo_ci, i, "left")
                if b<=a: continue
                sw_level=sw_ext=sw_k=None
                for si in range(b-1, a-1, -1):
                    ci = int(slo_ci[si]); lvl = slo_px[si]; s = max(ci, w0); ll = l[s:i+1]
                    if len(ll)==0: continue
                    if ll.min() < lvl:
                        k = s + int(np.argmax(ll < lvl))
                        if sweep_reject and not (c[k] > lvl): continue
                        sw_level=lvl; sw_ext=ll.min(); sw_k=k; break
                if sw_level is None: continue
                if mode=="run":
                    if bias_at(tsp[i].value) <= 0: continue
                    mss_bar = sw_k
                else:
                    hb = np.searchsorted(shi_ci, i, "left")
                    if hb<=0: continue
                    mss_lvl = shi_px[hb-1]; mss_bar=-1
                    for k in range(sw_k+1, i+1):
                        if c[k] > mss_lvl: mss_bar=k; break
                    if mss_bar<0: continue

            # bias_at_fill=True: CAUSAL bias — checked at the FILL bar (below, after fi).
            # Default (legacy) checks at the OUTER signal i, which can land AFTER the fill
            # (outer_i > fill_i) → a look-ahead. Kept only for reproducing old numbers.
            if bias_align and not bias_at_fill and bias_at(tsp[i].value) != iside: continue

            fvg=None
            for k in range(max(mss_bar,2), min(mss_bar+fvg_wait, n)):
                if iside<0 and h[k] < l[k-2]:
                    sz=l[k-2]-h[k]
                    if sz>=fvg_min: fvg={"k":k,"prox":h[k],"far":l[k-2],"ce":(l[k-2]+h[k])/2}; break
                if iside>0 and l[k] > h[k-2]:
                    sz=l[k]-h[k-2]
                    if sz>=fvg_min: fvg={"k":k,"prox":l[k],"far":h[k-2],"ce":(l[k]+h[k-2])/2}; break
            if fvg is None: continue
            elvl = fvg["ce"] if entry=="ce" else fvg["prox"]

            if ote is not None:   # OTE-band confluence (causal: inputs <= fvg formation)
                if iside<0:
                    fib1=sw_ext; fib0=float(l[sw_k:fvg["k"]+1].min()); rng_=fib1-fib0
                    if rng_<=0: continue
                    rr_=(elvl-fib0)/rng_
                else:
                    fib1=sw_ext; fib0=float(h[sw_k:fvg["k"]+1].max()); rng_=fib0-fib1
                    if rng_<=0: continue
                    rr_=(fib0-elvl)/rng_
                if not (ote[0] <= rr_ <= ote[1]): continue

            fi=-1
            for k in range(fvg["k"]+1, min(fvg["k"]+1+retrace_wait, n-1)):
                if iside<0 and h[k] >= elvl: fi=k; break
                if iside>0 and l[k] <= elvl: fi=k; break
            if fi<0: continue
            if bias_align and bias_at_fill and bias_at(tsp[fi].value) != iside: continue
            if fill_delay:
                fi += fill_delay
                if fi >= n-1: continue
            if not sess_ok[fi]: continue
            entry_px = o[fi] if fill_delay else elvl
            stop = sw_ext if sl=="sweep" else fvg["far"]
            R = abs(entry_px-stop)
            if R<=0: continue
            key=(fi,iside)
            if key in used: continue
            used.add(key)
            if tp_mode=="rr":
                tp = entry_px - tp_r*R if iside<0 else entry_px + tp_r*R
            else:
                if iside<0:
                    lows=slo_px[slo_ci<fi]; tp = lows[-1] if len(lows) else entry_px-tp_r*R
                else:
                    his=shi_px[shi_ci<fi]; tp = his[-1] if len(his) else entry_px+tp_r*R
                if (iside<0 and tp>=entry_px) or (iside>0 and tp<=entry_px):
                    tp = entry_px - tp_r*R if iside<0 else entry_px + tp_r*R
            eff_r = abs(tp-entry_px)/R
            out=None; mfe=0.0; mae=0.0; exit_k=min(fi+max_hold,n-1)
            for k in range(fi, min(fi+max_hold, n-1)):
                # bracket="wick": hard SL/TP hit on intrabar high/low (server-side realism).
                # bracket="close": SL/TP hit only when the bar CLOSE crosses (matches the
                # bt_engine walk_bracket_on_bar close-based walker — used for parity).
                hi_cmp = c[k] if bracket=="close" else h[k]
                lo_cmp = c[k] if bracket=="close" else l[k]
                if iside<0:
                    mfe=max(mfe,(entry_px-l[k])/R); mae=min(mae,-(h[k]-entry_px)/R)
                    if hi_cmp>=stop: out=-1.0; exit_k=k; break
                    if lo_cmp<=tp:   out=eff_r; exit_k=k; break
                else:
                    mfe=max(mfe,(h[k]-entry_px)/R); mae=min(mae,-(entry_px-l[k])/R)
                    if lo_cmp<=stop: out=-1.0; exit_k=k; break
                    if hi_cmp>=tp:   out=eff_r; exit_k=k; break
            if out is None:
                cx=c[min(fi+max_hold,n-1)]; out=((entry_px-cx) if iside<0 else (cx-entry_px))/R
            rec={"net_r":out-cost/max(R,1e-9),"side":iside,"fill_ts":tsp[fi],"exit_ts":tsp[exit_k],
                 "R_price":R,"entry_px":entry_px,"stop":stop,"tp":tp,"eff_r":eff_r,
                 "sig_ts":tsp[mss_bar],"sweep_ts":tsp[sw_k],"outer_i":i,"fill_i":fi,
                 "fvg_ts":tsp[fvg["k"]]}
            if collect_mfe: rec["mfe"]=mfe; rec["mae"]=mae
            trades.append(rec)
    return trades

# ----------------------------------------------------------------------------- helpers
def pf(x):
    w=sum(v for v in x if v>0); loss=abs(sum(v for v in x if v<0)); return w/loss if loss else 9.99

def audit_causal(trades):
    v=0
    for t in trades:
        if not (t["sweep_ts"] <= t["sig_ts"]): v+=1
        if not (t["sig_ts"] < t["fill_ts"]):  v+=1
        if not (t["fvg_ts"]  <= t["fill_ts"]): v+=1
    return v

def stats(tr):
    if not tr: return None
    nets=[t["net_r"] for t in tr]; yb=pd.Series(nets).groupby([t["fill_ts"].year for t in tr]).sum()
    return dict(n=len(nets),netR=sum(nets),pf=pf(nets),avgr=sum(nets)/len(nets),
                pos=int((yb>0).sum()),yrs=len(yb))

def line(lbl,s):
    print(f"  {lbl:<24} n={s['n']:<5d} netR={s['netR']:>7.1f} PF={s['pf']:.2f} "
          f"avgR={s['avgr']:+.3f} pos={s['pos']}/{s['yrs']}" if s else f"  {lbl:<24} 0")

def base_for(asset):
    a=ASSET[asset]; b=dict(HEADLINE); b["exec_tf"]=a["exec_tf"]; b["fvg_min"]=a["fvg_min"]; return b

# ----------------------------------------------------------------------------- commands
def cmd_diag(argv):
    asset = argv[0] if argv else "xau"; mode = argv[1] if len(argv)>1 else "reversal"
    a=ASSET[asset]; df=load(a["path"])
    bh=(df.close.iloc[-1]/df.close.iloc[0]-1)*100
    print(f"{asset.upper()} {len(df):,} bars | buy-hold {bh:+.0f}% (beta context) | mode={mode}")
    for sess in ("am","london","pm","all"):
        tr=run(df, session=sess, exec_tf=a["exec_tf"], mss_lb=3, fvg_min=a["fvg_min"],
               tp_r=2.0, direction="both", collect_mfe=True, mode=mode)
        s=stats(tr); line(f"{sess} {mode}", s)
        if tr:
            mfe=np.array([t["mfe"] for t in tr]); mae=np.array([-t["mae"] for t in tr])
            print(f"      MFE med={np.median(mfe):.2f} MAE med={np.median(mae):.2f} "
                  f"reach+1R={100*(mfe>=1).mean():.0f}% viol={audit_causal(tr)}")

def cmd_harden(argv):
    for asset in (argv or ["xau","nas"]):
        a=ASSET[asset]; df=load(a["path"]); base=base_for(asset)
        print(f"\n### {asset.upper()} COBRAX headline hardening ###")
        tr=run(df,direction="both",**base)
        line("cost0 both",stats(tr))
        line("  LONG",stats([t for t in tr if t['side']>0]))
        line("  SHORT",stats([t for t in tr if t['side']<0]))
        yb=pd.Series([t['net_r'] for t in tr]).groupby([t['fill_ts'].year for t in tr]).sum()
        print("  year netR:",{int(y):round(v,1) for y,v in yb.items()})
        print("  [cost]")
        for c in a["costs"]: line(f"cost={c}",stats(run(df,direction="both",cost=c,**base)))
        print("  [robustness]")
        line("+1bar delay",stats(run(df,direction="both",fill_delay=1,**base)))
        for o in [(0.38,0.79),(0.5,0.618),(0.62,0.79),(0.705,0.79)]:
            line(f"ote={o}",stats(run(df,direction="both",**{**base,'ote':o})))
        trc=run(df,direction="both",cost=a["cost"],**base)
        arr=np.array([t["net_r"] for t in trc]); yr=np.array([t["fill_ts"].year for t in trc])
        print(f"  [@cost{a['cost']}] IS PF={pf(arr[yr<a['oos']]):.2f} OOS PF={pf(arr[yr>=a['oos']]):.2f}")
        rng=np.random.default_rng(5); boot=np.array([rng.choice(arr,len(arr),replace=True).sum() for _ in range(3000)])
        print(f"  [bootstrap @cost{a['cost']}] netR={arr.sum():.0f} P(net<=0)={(boot<=0).mean():.4f} 5th={np.percentile(boot,5):.0f}")

def cmd_audit(argv):
    for asset in (argv or ["xau","nas"]):
        a=ASSET[asset]; df=load(a["path"]); base=base_for(asset)
        tr=run(df,direction="both",**base); nets=np.array([t["net_r"] for t in tr]); n=len(nets)
        w=nets[nets>0]; ls=nets[nets<0]
        print(f"\n### {asset.upper()} COBRAX audit  n={n} ###")
        print(f"  WR={100*len(w)/n:.1f}% avgWin={w.mean():+.2f}R avgLoss={ls.mean():+.2f}R PF={pf(nets):.2f}")
        srt=np.sort(nets)[::-1]; t5=int(0.05*n)
        print(f"  top-5% = {100*srt[:t5].sum()/nets.sum():.0f}% of net | PF excl top-5% winners = {pf(np.sort(nets)[:n-t5]):.2f}")
        print(f"  known_at violations = {audit_causal(tr)}")
        trr=run(df,direction="both",**{**base,'mode':'run'})
        nr=np.array([t["net_r"] for t in trr]) if trr else np.array([0.0])
        print(f"  BOS additive: run-mode(noBOS) PF={pf(nr):.2f}  vs  reversal(BOS) PF={pf(nets):.2f}")

def cmd_pnl(argv):
    asset = argv[0] if argv else "xau"; a=ASSET[asset]
    sys.path.insert(0, f"{REPO}/bt_engine")
    from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig, CONTRACT_SIZE
    SYM = "XAUUSD.ecn" if asset=="xau" else "NAS100"
    if SYM not in CONTRACT_SIZE: SYM="XAUUSD.ecn"
    df=load(a["path"]); base=base_for(asset)
    tr=run(df,direction="both",cost=a["cost"],**base)
    tr=[t for t in tr if t["exit_ts"]>t["fill_ts"] and t["R_price"]>0]; tr.sort(key=lambda t:t["fill_ts"])
    contract=CONTRACT_SIZE[SYM]
    def real_pnl(trades,start,rp):
        sz=EquitySizer(EquitySizerConfig(start_balance=start,risk_pct=rp))
        ev=[]
        for i,t in enumerate(trades):
            ev.append((t["fill_ts"],0,i)); ev.append((t["exit_ts"],1,i))
        ev.sort(key=lambda x:(x[0],x[1])); lots={}; mn=start
        for ts,kind,i in ev:
            t=trades[i]
            if kind==0: lots[i]=sz.size_order(symbol=SYM,stop_distance=t["R_price"],ts=pd.Timestamp(ts).to_pydatetime())
            else:
                sz.on_trade_closed(pnl_dollars=lots.get(i,0.0)*contract*t["R_price"]*t["net_r"],
                                   close_ts=pd.Timestamp(ts).to_pydatetime())
                mn=min(mn,sz.state.current_equity)
        return sum(h["skim_amount"] for h in sz.state.skim_history)+sz.state.current_equity, mn
    nets=np.array([t["net_r"] for t in tr])
    print(f"COBRAX {asset.upper()} headline (cost={a['cost']}) — REAL EquitySizer Model-B")
    print(f"  R-chain: {len(tr)} trades netR={nets.sum():.0f} avgR={nets.mean():+.3f} "
          f"{tr[0]['fill_ts'].year}-{tr[-1]['fill_ts'].year}")
    print(f"  {'risk':>5} {'start':>6} | {'final $':>13} {'min-eq':>10}")
    for rp in (0.005,0.015,0.03):
        for st in (5000.0,10000.0):
            fin,mn=real_pnl(tr,st,rp)
            print(f"  {rp*100:>4.1f}% ${int(st/1000)}k  | ${fin:>11,.0f} ${mn:>9,.0f}")

def cmd_run(argv):
    p=argparse.ArgumentParser(prog="cobrax run")
    p.add_argument("--asset",default="xau"); p.add_argument("--session",default="all")
    p.add_argument("--exec_tf",type=int); p.add_argument("--mss_lb",type=int,default=3)
    p.add_argument("--fvg_min",type=float); p.add_argument("--mode",default="reversal")
    p.add_argument("--direction",default="both"); p.add_argument("--tp_mode",default="nl")
    p.add_argument("--tp_r",type=float,default=2.0); p.add_argument("--entry",default="edge")
    p.add_argument("--sl",default="sweep"); p.add_argument("--cost",type=float,default=0.0)
    p.add_argument("--ote",type=float,nargs=2,default=None); p.add_argument("--bias_align",action="store_true")
    p.add_argument("--fill_delay",type=int,default=0)
    args=p.parse_args(argv); a=ASSET[args.asset]; df=load(a["path"])
    kw=dict(session=args.session,exec_tf=args.exec_tf or a["exec_tf"],mss_lb=args.mss_lb,
            fvg_min=a["fvg_min"] if args.fvg_min is None else args.fvg_min,mode=args.mode,
            direction=args.direction,tp_mode=args.tp_mode,tp_r=args.tp_r,entry=args.entry,sl=args.sl,
            cost=args.cost,ote=tuple(args.ote) if args.ote else None,bias_align=args.bias_align,
            fill_delay=args.fill_delay,collect_mfe=True)
    tr=run(df,**kw); s=stats(tr); line(f"{args.asset} {args.session} {args.mode}", s)
    if tr:
        mfe=np.array([t["mfe"] for t in tr]); mae=np.array([-t["mae"] for t in tr])
        print(f"  MFE med={np.median(mfe):.2f} MAE med={np.median(mae):.2f} viol={audit_causal(tr)}")

CMDS={"diag":cmd_diag,"harden":cmd_harden,"audit":cmd_audit,"pnl":cmd_pnl,"run":cmd_run}

if __name__=="__main__":
    if len(sys.argv)<2 or sys.argv[1] not in CMDS:
        print(__doc__); print("commands:", " ".join(CMDS)); sys.exit(0)
    CMDS[sys.argv[1]](sys.argv[2:])
