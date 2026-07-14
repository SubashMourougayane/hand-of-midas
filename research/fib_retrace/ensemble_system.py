#!/usr/bin/env python3
"""Combined LONG+SHORT ensemble — push trades/day up + measure real money.
Union several robust configs (diversify across session/lb/hold), dedupe
near-simultaneous same-direction entries, report combined trades/day, PF, netR,
per-year, and HONEST money (flat-risk + modest compound, no fantasy).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5
from research.fib_retrace.safety_net_sweep import simulate_with_safety
from research.fib_retrace.intraday_phase1_sweep import resample_m5_to_m15, build_m15_pivot_events


def pf(x):
    x = np.asarray(x, float); gl = -x[x < 0].sum()
    return x[x > 0].sum() / gl if gl > 0 else 9.9


def main():
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"), Path("/tmp/oanda_xau_m5.parquet"))
    m15 = add_m5_features(resample_m5_to_m15(m5)); d1 = add_d1_features(resample_d1(m15))
    m15 = attach_d1_to_m5(m15, d1)
    V = m15["volume"].values; volavg = pd.Series(V).rolling(20).mean().shift(1).values; vmask = V > 1.5 * volavg
    piv = {lb: build_m15_pivot_events(m15, lb) for lb in (3, 5, 8)}
    span = (pd.to_datetime(m15["timestamp"].iloc[-1]) - pd.to_datetime(m15["timestamp"].iloc[0])).days / 365.25

    # config list: (name, direc, reg, sess, lb, hold, ext, vol)
    LONGS = [
        ("L_any_ny", "long", "any", "ny", 5, 24, 3.618, False),
        ("L_any_lonny", "long", "any", "london_ny", 5, 24, 3.618, False),
        ("L_bull_ny", "long", "bull", "ny", 3, 24, 3.618, False),
    ]
    SHORTS = [
        ("S_ct_bull_ny", "short", "bull", "ny", 3, 8, 3.618, True),
        ("S_ct_bullstr_ny", "short", "bull_strong", "ny", 3, 8, 3.618, True),
    ]

    def build(cfg):
        _, direc, reg, sess, lb, hold, ext, vol = cfg
        s = gen_signals_with_regime(m15, piv[lb], direction=direc, session=sess,
                                    max_hold_bars=hold * 4, ext_target_pct=ext,
                                    sl_buffer_pct=0.02, regime=reg)
        if vol:
            s = s[vmask[s["entry_index"].values]]
        tr = simulate_with_safety(m15, s, cost_usd=0.30, horizon_bars=hold * 4, partial_tp_at_r=None)
        tr65 = simulate_with_safety(m15, s, cost_usd=0.65, horizon_bars=hold * 4, partial_tp_at_r=None)
        tr["cfg"] = cfg[0]; tr["net_r65"] = tr65["net_r"].values
        return tr

    def combine(cfgs, label):
        parts = [build(c) for c in cfgs]
        allt = pd.concat(parts, ignore_index=True)
        allt["entry_ts"] = pd.to_datetime(allt["entry_ts"])
        allt = allt.sort_values("entry_ts").reset_index(drop=True)
        # dedupe: same direction within 1h -> keep first (avoid stacking identical setups)
        allt["side"] = np.sign(allt["net_r"] * 0 + allt.get("side", 1))  # side col exists
        keep = []
        last = {}
        for idx, row in allt.iterrows():
            k = row["cfg"][:1] + str(int(row.get("side", 1)))
            t = row["entry_ts"]
            if k in last and (t - last[k]).total_seconds() < 3600:
                continue
            last[k] = t; keep.append(idx)
        d = allt.loc[keep].copy()
        d["year"] = d["entry_ts"].dt.year
        r = d["net_r"].values; r65 = d["net_r65"].values
        tpd = len(d) / (span * 252)
        ys = d.groupby("year")["net_r"].sum()
        oos = d[d.year >= 2016]["net_r"].values
        print(f"\n=== {label} ===")
        print(f"  trades {len(d)}  trades/day {tpd:.2f}  span {span:.1f}yr")
        print(f"  cost0.30: PF={pf(r):.3f} WR={(r>0).mean()*100:.1f}% netR={r.sum():+.0f} OOS={pf(oos):.2f} posY={int((ys>0).sum())}/{len(ys)}")
        print(f"  cost0.65: PF={pf(r65):.3f} netR={r65.sum():+.0f}")
        # honest money: flat risk (no compound fantasy)
        for risk in (0.005, 0.01):
            for start in (5000, 100000):
                flat = start + start * risk * r.sum()
                # modest yearly-compounded (compound per year, not per trade)
                eq = start
                for y, v in ys.items():
                    eq *= (1 + risk * v)
                print(f"    risk {risk*100:.1f}% ${start:>7,}: flat ${flat:>12,.0f} | yr-compounded ${eq:>14,.0f}")
        return d

    combine(LONGS, "LONG ENSEMBLE (3 configs)")
    combine(SHORTS, "SHORT ENSEMBLE (2 counter-trend)")
    combine(LONGS + SHORTS, "FULL LONG+SHORT SYSTEM")


if __name__ == "__main__":
    main()
