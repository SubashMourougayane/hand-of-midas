#!/usr/bin/env python3
"""FRESH, execution-HONEST: no-stop, time-based-exit intraday. Avoids the wick/stop
artifact entirely — enter, hold N bars, exit at the real close, book real ATR-R.
The overnight drift survived this style; does an intraday version?

Entry triggers (causal): session-open, pullback-to-ema, momentum-thrust. In-regime.
Both directions. Exit = fixed N M15 bars (real close return). Risk unit = ATR (so R
is honest, no -1R fantasy). Sweep, score PF/WR/OOS/delay/tpd. Cost applied.
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


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else 9.9


def main():
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = add_m5_features(resample_m5_to_m15(m5)); d1 = add_d1_features(resample_d1(m15))
    m15 = attach_d1_to_m5(m15, d1).reset_index(drop=True)
    ny = pd.to_datetime(m15["timestamp"]).dt.tz_convert("America/New_York")
    hr = ny.dt.hour.values; mn = ny.dt.minute.values; yr = ny.dt.year.values
    O = m15["open"].values; H = m15["high"].values; L = m15["low"].values; C = m15["close"].values
    V = m15["volume"].values; n = len(m15)
    atr = m15["atr14_m5"].values
    ema50d = m15["ema50_lag_d1"].values; ema200d = m15["ema200_lag_d1"].values
    ema20 = pd.Series(C).ewm(span=20, adjust=False).mean().shift(1).values  # intraday ema, lagged
    volavg = pd.Series(V).rolling(20).mean().shift(1).values
    span = (pd.to_datetime(m15["timestamp"].iloc[-1]) - pd.to_datetime(m15["timestamp"].iloc[0])).days / 365.25
    ret1 = np.concatenate([[0], np.diff(C)])  # bar move

    bull = ema50d > ema200d; bear = ema50d < ema200d
    sbull = bull & (C > ema50d); sbear = bear & (C < ema50d)
    REG = {"any": np.ones(n, bool), "bull": bull, "bear": bear, "bull_strong": sbull, "bear_strong": sbear}
    SESS = {"ny": (hr >= 8) & (hr < 17), "london": (hr >= 3) & (hr < 12), "all": np.ones(n, bool)}

    def trig(kind, direc):
        d = 1 if direc == "long" else -1
        if kind == "sess_open":  # first NY bar (08:00) / london (03:00)
            return ((hr == 8) & (mn == 0)) | ((hr == 3) & (mn == 0))
        if kind == "pullback":   # price crossed back to ema20 in trend direction
            if direc == "long": return (C > ema20) & (np.concatenate([[False], C[:-1] <= ema20[:-1]]))
            else: return (C < ema20) & (np.concatenate([[False], C[:-1] >= ema20[:-1]]))
        if kind == "thrust":     # momentum thrust + volume
            return (np.sign(ret1) == d) & (np.abs(ret1) > 1.0 * atr) & (V > 1.5 * volavg)
        return np.zeros(n, bool)

    def bt(direc, kind, reg, sess, hold, cost=COST, delay=0):
        d = 1 if direc == "long" else -1
        sig = trig(kind, direc) & REG[reg] & SESS[sess]
        idx = np.where(sig)[0]
        rows = []
        last_exit = -1
        for i in idx:
            if i <= last_exit or i + 1 + delay >= n or not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            ei = i + 1 + delay; xi = min(n - 1, ei + hold)
            r = d * (C[xi] - O[ei]) / atr[i] - cost / atr[i]
            rows.append((yr[ei], r)); last_exit = xi
        if len(rows) < 200: return None
        df = pd.DataFrame(rows, columns=["year", "net_r"]); rr = df["net_r"].values
        oos = df[df.year >= 2016]["net_r"].values
        return dict(n=len(rr), tpd=len(rr)/(span*252), pf=pf(rr), wr=(rr > 0).mean()*100,
                    net=rr.sum(), oos=pf(oos), posY=int((df.groupby("year")["net_r"].sum() > 0).sum()),
                    tot=df["year"].nunique(), rr=rr)

    print("=== NO-STOP TIME-EXIT intraday (honest execution) ===")
    print(f"{'cfg':<42}{'n':>5}{'tpd':>5}{'PF':>6}{'WR':>5}{'net':>7}{'OOS':>6}{'dly':>6}{'posY':>6}")
    hits = 0
    for direc in ("long", "short"):
        for kind in ("sess_open", "pullback", "thrust"):
            for reg in ("any", "bull", "bear", "bull_strong", "bear_strong"):
                for sess in ("ny", "london", "all"):
                    for hold in (4, 12, 24, 48):
                        m = bt(direc, kind, reg, sess, hold)
                        if m is None or not (0.5 <= m["tpd"] <= 6): continue
                        if m["pf"] < 1.25: continue
                        md = bt(direc, kind, reg, sess, hold, delay=1)
                        dlypf = md["pf"] if md else 0
                        cfg = f"{direc[:1]}_{kind}_{reg}_{sess}_h{hold}"
                        rob = m["pf"] >= 1.3 and m["oos"] >= 1.25 and dlypf >= 1.25
                        star = "  ROBUST" if rob else ""
                        print(f"{cfg:<42}{m['n']:>5}{m['tpd']:>5.1f}{m['pf']:>6.2f}{m['wr']:>5.0f}"
                              f"{m['net']:>+7.0f}{m['oos']:>6.2f}{dlypf:>6.2f}{m['posY']:>3}/{m['tot']:<2}{star}")
                        hits += rob
    print(f"\nrobust no-stop configs: {hits}")


if __name__ == "__main__":
    main()
