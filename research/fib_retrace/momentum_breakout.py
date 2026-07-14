#!/usr/bin/env python3
"""FRESH mechanism (not fib): volume-confirmed momentum breakout, regime-aware,
both directions, intraday. ORB/breakout was buried BEFORE — but without the levers
that made fib work (volume surge + regime + big R-target + no tight stop). Retry
with fresh mind. Causal: break of prior N-bar high/low on the CLOSE of bar i (known),
enter next bar open, ATR stop, ext-R target, intraday hold cap.

Sweep: brk_lookback, regime, session, direction, ext, atr_stop_mult, vol_filter.
Scored cost 0.30 & 0.65, IS/OOS, delay+1, trades/day. Flag robust + uncorrelated-vs-fib.
"""
from __future__ import annotations
import sys
from itertools import product
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import resample_d1, add_d1_features, attach_d1_to_m5
from research.fib_retrace.intraday_phase1_sweep import resample_m5_to_m15

COST = 0.30
NY = (8, 17); LON = (3, 12)


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else 9.9


def main():
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = add_m5_features(resample_m5_to_m15(m5)); d1 = add_d1_features(resample_d1(m15))
    m15 = attach_d1_to_m5(m15, d1).reset_index(drop=True)
    ny = pd.to_datetime(m15["timestamp"]).dt.tz_convert("America/New_York")
    hr = ny.dt.hour.values; yr = ny.dt.year.values
    O = m15["open"].values; H = m15["high"].values; L = m15["low"].values; C = m15["close"].values
    V = m15["volume"].values
    n = len(m15)
    volavg = pd.Series(V).rolling(20).mean().shift(1).values
    atr = m15["atr14_m5"].values if "atr14_m5" in m15 else pd.Series(H - L).rolling(14).mean().values
    ema50 = m15["ema50_lag_d1"].values; ema200 = m15["ema200_lag_d1"].values
    close_d1 = m15["close"].values  # proxy; regime via d1 emas
    span = (pd.to_datetime(m15["timestamp"].iloc[-1]) - pd.to_datetime(m15["timestamp"].iloc[0])).days / 365.25

    # regime (causal, d1 emas already lagged)
    bull = (ema50 > ema200); bear = (ema50 < ema200)
    strong_bull = bull & (C > ema50); strong_bear = bear & (C < ema50)
    REG = {"any": np.ones(n, bool), "bull": bull, "bear": bear,
           "bull_strong": strong_bull, "bear_strong": strong_bear}
    SESS = {"ny": (hr >= 8) & (hr < 17), "london": (hr >= 3) & (hr < 12),
            "all": np.ones(n, bool)}

    def backtest(direc, brk, reg, sess, ext, atr_mult, vol, delay=0, cost=COST):
        rollhi = pd.Series(H).rolling(brk).max().shift(1).values
        rolllo = pd.Series(L).rolling(brk).min().shift(1).values
        rmask = REG[reg]; smask = SESS[sess]
        rows = []
        i = brk + 1
        while i < n - 1:
            if not (smask[i] and rmask[i]) or not np.isfinite(atr[i]) or atr[i] <= 0:
                i += 1; continue
            if vol and not (V[i] > 1.5 * volavg[i]):
                i += 1; continue
            sig = 0
            if direc == "long" and C[i] > rollhi[i]:
                sig = 1
            elif direc == "short" and C[i] < rolllo[i]:
                sig = -1
            if sig == 0:
                i += 1; continue
            ei = i + 1 + delay
            if ei >= n: break
            ent = O[ei]; risk = atr_mult * atr[i]
            stop = ent - sig * risk; tp = ent + sig * ext * risk
            out = None; hold = 0
            for j in range(ei, min(n, ei + 48)):  # 12h cap
                hold += 1
                if sig > 0:
                    if L[j] <= stop: out = -1.0; break
                    if H[j] >= tp: out = ext; break
                else:
                    if H[j] >= stop: out = -1.0; break
                    if L[j] <= tp: out = ext; break
            if out is None:
                out = sig * (C[min(n-1, ei+48)] - ent) / risk
            rows.append((yr[ei], out - cost / risk))
            i = ei + hold  # no overlap (skip past the trade)
        return pd.DataFrame(rows, columns=["year", "net_r"])

    print("=== FRESH: volume-confirmed momentum breakout (both dirs) ===")
    print(f"{'cfg':<40}{'n':>5}{'tpd':>5}{'PF30':>6}{'WR':>6}{'PF65':>6}{'OOS':>6}{'dly':>6}{'posY':>6}")
    hits = []
    for direc in ("long", "short"):
        for brk in (10, 20, 40):
            for reg in ("any", "bull", "bear", "bull_strong", "bear_strong"):
                for sess in ("ny", "london", "all"):
                    for ext in (1.5, 2.5, 4.0):
                        for atr_mult in (1.0, 1.5):
                            for vol in (True, False):
                                d = backtest(direc, brk, reg, sess, ext, atr_mult, vol)
                                if len(d) < 200: continue
                                r = d["net_r"].values; tpd = len(d)/(span*252)
                                if not (0.5 <= tpd <= 6): continue
                                oos = d[d.year>=2016]["net_r"].values
                                if pf(r) < 1.35 or len(oos) < 100: continue
                                dd = backtest(direc, brk, reg, sess, ext, atr_mult, vol, delay=1)
                                r65 = backtest(direc, brk, reg, sess, ext, atr_mult, vol, cost=0.65)["net_r"].values
                                ys = d.groupby("year")["net_r"].sum()
                                cfg=f"{direc[:1]}_brk{brk}_{reg}_{sess}_ext{ext}_atr{atr_mult}_v{int(vol)}"
                                pf30=pf(r); oospf=pf(oos); dlypf=pf(dd["net_r"].values)
                                robust = pf30>=1.5 and (r>0).mean()>0.4 and oospf>=1.4 and dlypf>=1.45
                                star="  ROBUST" if robust else ""
                                if pf30>=1.45 and oospf>=1.35:
                                    print(f"{cfg:<40}{len(r):>5}{tpd:>5.1f}{pf30:>6.2f}{(r>0).mean()*100:>6.1f}{pf(r65):>6.2f}{oospf:>6.2f}{dlypf:>6.2f}{int((ys>0).sum())}/{len(ys):<2}{star}")
                                    if robust: hits.append(cfg)
    print(f"\nrobust breakout configs: {len(hits)}")


if __name__ == "__main__":
    main()
