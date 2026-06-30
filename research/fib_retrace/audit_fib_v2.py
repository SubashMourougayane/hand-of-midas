"""9-test audit on Fib V2 top survivors + $5k 3% monthly PnL."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, headline, print_headline
from research.fib_retrace.run_fib import (
    resample, build_h1_features, add_m5_swings_and_atr
)
from research.fib_retrace.run_fib_v2 import (
    build_pivot_events, gen_signals_v2, simulate_fixed_tp
)


TOP = [
    dict(direction="long", pivot_lb=5, max_hold_h=72, session="all",
         ext=1.618, sl_buf=0.02,
         label="TOP1_long_lb5_hold72h_all_ext1.618_sl0.02"),
    dict(direction="long", pivot_lb=5, max_hold_h=48, session="all",
         ext=1.618, sl_buf=0.02,
         label="TOP2_long_lb5_hold48h_all_ext1.618_sl0.02"),
    dict(direction="long", pivot_lb=3, max_hold_h=24, session="overlap",
         ext=1.618, sl_buf=0.02,
         label="TOP3_long_lb3_hold24h_overlap_ext1.618_sl0.02"),
]


START_NAV = 5000.0; RISK_PCT = 0.03; LEVERAGE = 1000
XAU_CONTRACT = 100; MIN_LOT = 0.01; LOT_STEP = 0.01


def monthly_pnl(trades, label):
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    monthly = {}
    nav = START_NAV; curr_month = None
    lots_seen = []
    for r in df.itertuples(index=False):
        if curr_month is None: curr_month = r.year_month
        if r.year_month != curr_month:
            monthly[curr_month] = nav - START_NAV
            curr_month = r.year_month; nav = START_NAV
        risk_dollars = nav * RISK_PCT
        risk_units = float(r.risk_units)
        if risk_units <= 0: continue
        raw_lots = risk_dollars / (risk_units * XAU_CONTRACT)
        max_margin_lots = (0.9 * nav * LEVERAGE) / (float(r.entry_price) * XAU_CONTRACT)
        lots = min(raw_lots, max_margin_lots)
        lots = math.floor(lots / LOT_STEP) * LOT_STEP
        if lots < MIN_LOT: continue
        lots_seen.append(lots)
        dollar_per_r = lots * XAU_CONTRACT * risk_units
        pnl = float(r.net_r) * dollar_per_r
        nav += pnl
    if curr_month: monthly[curr_month] = nav - START_NAV
    s = pd.Series(monthly).sort_index()
    pos = int((s > 0).sum()); neg = int((s < 0).sum())
    print(f"\n=== {label} $5k 3% monthly reset ===")
    print(f"trades={len(df)} months={len(s)} pos={pos} neg={neg}")
    print(f"total=${s.sum():+,.2f}  avg/mo=${s.mean():+,.2f}  median=${s.median():+,.2f}")
    print(f"avg_lots={np.mean(lots_seen):.3f} max_lots={max(lots_seen) if lots_seen else 0:.2f}")
    print(f"best  {s.idxmax() if pos else 'na'}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin() if neg else 'na'}: ${s.min():+,.2f}")
    by_yr = s.groupby(s.index.str[:4]).sum().round(2).to_dict()
    print(f"per-yr {by_yr}")
    return s


def audit(label, m5_f, sigs, max_hold_bars):
    print(f"\n=== AUDIT {label} ===\nsignals: {len(sigs)}")
    h = headline(simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2))
    print_headline("baseline", h)
    for d in [1, 3, 5, 10]:
        s = sigs.copy(); s["entry_index"] = s["entry_index"].astype(int) + d
        h = headline(simulate_fixed_tp(m5_f, s, horizon_bars=max_hold_bars*2))
        print_headline(f"+{d} delay", h)
    for extra in [0.10, 0.20, 0.50]:
        h = headline(simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2,
                                        cost_usd=0.30 + extra))
        print_headline(f"cost+${extra:.2f}", h)
    is_mask = sigs["entry_index"].astype(int) < int(0.6 * len(m5_f))
    h_is = headline(simulate_fixed_tp(m5_f, sigs[is_mask], horizon_bars=max_hold_bars*2))
    h_oos = headline(simulate_fixed_tp(m5_f, sigs[~is_mask], horizon_bars=max_hold_bars*2))
    print_headline("IS 60%", h_is)
    print_headline("OOS 40%", h_oos)
    trades = simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2)
    if len(trades) > 5:
        rng = np.random.default_rng(42)
        nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                          random_state=rng.integers(10**9)).sum() for _ in range(3000)])
        print(f"BOOTSTRAP n=3000: P(net<0)={(nets<0).mean()*100:.2f}% p05={np.percentile(nets,5):+.1f}R")
    if len(trades):
        y = trades.groupby("year")["net_r"].sum().round(2)
        print(f"by year: {y.to_dict()}")
    return trades


def main():
    print("[load] frames...")
    m1, m5, _ = load_data()
    h1 = resample(m1, "1h"); h1 = build_h1_features(h1)
    m5_f = add_m5_swings_and_atr(m5)
    if "ny_hr" not in m5_f.columns:
        m5_f["ny_hr"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.hour
    survivors = {}
    for cfg in TOP:
        pivot_events = build_pivot_events(h1, cfg["pivot_lb"])
        max_hold_bars = cfg["max_hold_h"] * 12
        sigs = gen_signals_v2(m5_f, pivot_events, direction=cfg["direction"],
                              session=cfg["session"], min_diff_atr=0.0,
                              max_hold_bars=max_hold_bars,
                              ext_target_pct=cfg["ext"], sl_buffer_pct=cfg["sl_buf"])
        trades = audit(cfg["label"], m5_f, sigs, max_hold_bars)
        survivors[cfg["label"]] = trades
    print("\n\n" + "=" * 80)
    print("PnL — $5k 3% monthly reset for each survivor\n")
    series = {}
    for label, tr in survivors.items():
        h = headline(tr); pos = int(h["pos_years"].split("/")[0])
        s = monthly_pnl(tr, label)
        series[label] = s

    # Save winner trades for portfolio
    print("\nSaving top variant trades...")
    top1_cfg = TOP[0]
    pivot_events = build_pivot_events(h1, top1_cfg["pivot_lb"])
    max_hold_bars = top1_cfg["max_hold_h"] * 12
    sigs = gen_signals_v2(m5_f, pivot_events, direction=top1_cfg["direction"],
                          session=top1_cfg["session"], min_diff_atr=0.0,
                          max_hold_bars=max_hold_bars,
                          ext_target_pct=top1_cfg["ext"], sl_buffer_pct=top1_cfg["sl_buf"])
    trades = simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2)
    out_parquet = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace/"
                       "fib_v2_long_lb5_hold72h_all_ext1.618_sl0.02_trades.parquet")
    trades.to_parquet(out_parquet)
    print(f"Saved → {out_parquet}")


if __name__ == "__main__":
    main()
