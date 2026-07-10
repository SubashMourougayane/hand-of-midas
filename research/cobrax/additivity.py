#!/usr/bin/env python3
"""COBRAX additivity vs Fib V2 A+D — the kill-or-keep gate.

Both on the SAME 20yr OANDA XAU (Fib V2 on M15, COBRAX on M5). Monthly-R correlation +
combined-portfolio smoothness decide whether COBRAX is a diversifying second sleeve or a
redundant re-run of our OTE edge.
  low corr (<0.4)  + combined Sharpe up      -> ADDITIVE (worth a second sleeve)
  high corr (>0.7) or combined Sharpe flat   -> REDUNDANT (park it)
"""
import sys, uuid
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine/scripts")
import cobrax as CB
from bt_engine.data.memory_provider import resample_m5_to
from parity_21yr_bt_vs_live import run_path

M5 = CB.XAU_M5

def fibv2_stream(frame_m15):
    """Fib V2 A+D closed trades on M15 → DataFrame(ts, net_r)."""
    closed, _ = run_path("bt", frame_m15, "fib_v2_intraday_a_plus_d", 24*4*2)
    rows = [{"ts": pd.Timestamp(t[0]), "net_r": float(t[3])} for t in closed]
    return pd.DataFrame(rows)

def cobrax_stream(df_m5, tp_mode="rr", tp_r=3.0, cost=0.2):
    base = dict(CB.HEADLINE); base["exec_tf"] = 5; base["fvg_min"] = 0.3
    base["tp_mode"] = tp_mode; base["tp_r"] = tp_r
    tr = CB.run(df_m5, direction="both", cost=cost, **base)
    return pd.DataFrame([{"ts": t["fill_ts"], "net_r": t["net_r"]} for t in tr])

def monthly(df):
    if df.empty: return pd.Series(dtype=float)
    s = df.copy(); s["m"] = pd.to_datetime(s["ts"]).dt.tz_localize(None).dt.to_period("M")
    return s.groupby("m")["net_r"].sum()

def stats(sr):
    if len(sr) < 2: return dict(n=0)
    cum = sr.cumsum(); dd = (cum - cum.cummax()).min()
    return dict(months=len(sr), totalR=sr.sum(), mean=sr.mean(), std=sr.std(),
                sharpe=sr.mean()/sr.std()*np.sqrt(12) if sr.std() else 0,
                maxDD_R=dd, posM=int((sr>0).sum()))

def line(lbl, s):
    if not s or s.get("n")==0: print(f"  {lbl:<22} —"); return
    print(f"  {lbl:<22} months={s['months']:<4} totalR={s['totalR']:>7.0f} "
          f"mean={s['mean']:+.2f} std={s['std']:.2f} Sharpe={s['sharpe']:+.2f} "
          f"maxDD_R={s['maxDD_R']:>6.0f} posM={s['posM']}/{s['months']}")

if __name__ == "__main__":
    tp_r = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    print(f"loading M5 -> M15 ...", flush=True)
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15")
    df_m5 = CB.load(M5)

    print("Fib V2 A+D stream ...", flush=True); fib = fibv2_stream(frame)
    print(f"COBRAX stream (rr{tp_r}) ...", flush=True); cob = cobrax_stream(df_m5, tp_r=tp_r)
    print(f"  fib trades={len(fib)}  cobrax trades={len(cob)}")

    mf, mc = monthly(fib), monthly(cob)
    idx = mf.index.union(mc.index)
    mf = mf.reindex(idx, fill_value=0.0); mc = mc.reindex(idx, fill_value=0.0)
    comb = mf + mc

    corr = mf.corr(mc)
    print(f"\n=== MONTHLY-R CORRELATION: {corr:+.3f} ===")
    print(f"    (<0.4 diversifying · 0.4-0.7 partial · >0.7 redundant)")
    print("\n--- portfolio monthly-R stats ---")
    line("Fib V2 A+D", stats(mf)); line(f"COBRAX rr{tp_r}", stats(mc))
    line("COMBINED (equal-R)", stats(comb))
    sf, sco = stats(mf), stats(comb)
    if sf.get("sharpe") and sco.get("sharpe"):
        print(f"\n  Sharpe: Fib {sf['sharpe']:+.2f} -> Combined {sco['sharpe']:+.2f} "
              f"({'UP' if sco['sharpe']>sf['sharpe'] else 'DOWN'} {sco['sharpe']-sf['sharpe']:+.2f})")
        print(f"  maxDD_R: Fib {sf['maxDD_R']:.0f} -> Combined {sco['maxDD_R']:.0f}")
    # verdict
    add = (corr < 0.4) and sco.get("sharpe",0) >= sf.get("sharpe",0)
    print(f"\n  VERDICT: {'ADDITIVE — worth a 2nd sleeve' if add else 'check — corr/Sharpe not clearly additive'}")
