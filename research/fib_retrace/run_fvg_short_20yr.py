"""Re-run FVG Nested SHORT (age=4h, all-session, sw20, inside=False, TP=4R)
on OANDA 20.3yr data. Causal port.

Then combine with Fib V2 ensemble and check whether the 3 fib-losing years
(2012, 2017, 2021) get offset.
"""
from __future__ import annotations

import sys
from pathlib import Path
import math
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import headline, print_headline
from research.fvg_nested.run_fvg_fast import (
    resample as fvg_resample, detect_fvgs, gen_signals_fast as fvg_gen,
    simulate_with_limit,
)


def load_oanda():
    m5 = pd.read_parquet("/tmp/oanda_xau_m5.parquet")
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    m5["ny_hr"] = m5["timestamp"].dt.tz_convert("America/New_York").dt.hour
    m5["year"] = m5["timestamp"].dt.year
    return m5


def resample_m1_to_m15(m5):
    """We only have M5, build M15 by resampling M5 (close-enough for FVG detection)."""
    df = m5.set_index("timestamp").resample("15min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    ).dropna().reset_index()
    return df


def resample_m1_to_h4(m5):
    df = m5.set_index("timestamp").resample("4h", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    ).dropna().reset_index()
    return df


def main():
    print("[load] OANDA M5...")
    m5 = load_oanda()
    print(f"  M5: {len(m5):,} bars, range {m5.timestamp.min()} → {m5.timestamp.max()}")

    print("[build] H4 + M15 FVGs...")
    h4 = resample_m1_to_h4(m5)
    m15 = resample_m1_to_m15(m5)
    h4_fvgs = detect_fvgs(h4)
    m15_fvgs = detect_fvgs(m15)
    print(f"  H4 FVGs: {len(h4_fvgs):,}   M15 FVGs: {len(m15_fvgs):,}")

    m5_arr = {"open": m5["open"].values, "high": m5["high"].values,
              "low": m5["low"].values, "close": m5["close"].values,
              "ts": m5["timestamp"].values, "year": m5["year"].values}

    print("\n=== FVG nested SHORT — 20.3yr OANDA ===\n")
    sigs = fvg_gen(m5, h4_fvgs, m15_fvgs, direction="short",
                   fvg_max_age_h=4, session="all", swing_lookback=20,
                   require_m15_inside_h4=False)
    print(f"signals: {len(sigs):,}")
    if len(sigs) == 0:
        print("[empty]"); return

    trades = simulate_with_limit(m5_arr, sigs, tp_mult=4.0)
    if len(trades) == 0:
        print("[no trades]"); return
    h = headline(trades)
    print_headline("BASELINE 20.3yr", h)

    # Audit
    print("\n=== AUDIT ===")
    for d in [1, 5, 10]:
        s = sigs.copy(); s["signal_index"] = s["signal_index"].astype(int) + d
        print_headline(f"+{d} delay", headline(simulate_with_limit(m5_arr, s, tp_mult=4.0)))
    for extra in [0.10, 0.50]:
        print_headline(f"cost+${extra:.2f}",
            headline(simulate_with_limit(m5_arr, sigs, tp_mult=4.0, cost_usd=0.30 + extra)))
    is_mask = sigs["signal_index"].astype(int) < int(0.6 * len(m5))
    print_headline("IS 60%", headline(simulate_with_limit(m5_arr, sigs[is_mask], tp_mult=4.0)))
    print_headline("OOS 40%", headline(simulate_with_limit(m5_arr, sigs[~is_mask], tp_mult=4.0)))
    rng = np.random.default_rng(42)
    nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                      random_state=rng.integers(10**9)).sum() for _ in range(3000)])
    print(f"BOOTSTRAP n=3000: P(net<0)={(nets<0).mean()*100:.2f}% p05={np.percentile(nets,5):+.1f}R")

    # Per year
    by_yr = trades.groupby("year")["net_r"].agg(["sum", "count"]).round(2)
    by_yr.columns = ["net_R", "n"]
    print("\n[Per-year R — FVG short]")
    print(by_yr.to_string())

    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace")
    trades.to_parquet(out_dir / "fvg_short_oanda_20yr_trades.parquet")

    # Combine with Fib ensemble
    print("\n\n" + "="*80)
    print(">>> COMBO: Fib ensemble + FVG short <<<\n")
    fib_ens = pd.read_parquet(out_dir / "fib_v2_oanda_ensemble_trades.parquet")
    combo = pd.concat([fib_ens, trades], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)
    print(f"combined trades: {len(combo):,}  (Fib {len(fib_ens):,} + FVG short {len(trades):,})")
    h = headline(combo)
    print_headline("FIB+FVG 20yr", h)

    # Per year combo
    by_yr_combo = combo.groupby("year")["net_r"].agg(["sum", "count"]).round(2)
    by_yr_combo.columns = ["net_R", "n"]
    print("\n[Per-year R — combo]")
    print(by_yr_combo.to_string())

    # Fib lose-years analysis
    fib_yr = fib_ens.groupby("year")["net_r"].sum()
    fvg_yr = trades.groupby("year")["net_r"].sum()
    print("\n[Lose-year offset analysis]")
    print(f"{'year':<6} {'fib_R':>10} {'fvg_R':>10} {'combo_R':>10}")
    for yr in sorted(set(fib_yr.index) | set(fvg_yr.index)):
        f = fib_yr.get(yr, 0)
        g = fvg_yr.get(yr, 0)
        c = f + g
        flag = " ← FIB LOSE" if f < 0 else ""
        print(f"{yr:<6} {f:>+10.2f} {g:>+10.2f} {c:>+10.2f}{flag}")

    # $5k 3% monthly reset comparison
    print("\n\n" + "="*80)
    print(">>> $5k 3% monthly reset — Fib vs Combo <<<\n")
    for label, df in [("Fib_Ensemble", fib_ens), ("FVG_Short_Only", trades), ("Fib+FVG_Combo", combo)]:
        d = df.copy().sort_values("entry_ts").reset_index(drop=True)
        d["entry_ts"] = pd.to_datetime(d["entry_ts"])
        d["year_month"] = d["entry_ts"].dt.strftime("%Y-%m")
        nav = 5000.0; curr_m = None; monthly = {}
        for r in d.itertuples(index=False):
            if curr_m is None: curr_m = r.year_month; nav = 5000.0
            if r.year_month != curr_m:
                monthly[curr_m] = nav - 5000.0
                curr_m = r.year_month; nav = 5000.0
            risk_units = float(r.risk_units)
            if risk_units <= 0: continue
            risk_d = nav * 0.03
            raw_lots = risk_d / (risk_units * 100)
            max_m_lots = (0.9 * nav * 1000) / (float(r.entry_price) * 100)
            lots = math.floor(min(raw_lots, max_m_lots) / 0.01) * 0.01
            if lots < 0.01: continue
            pnl = float(r.net_r) * lots * 100 * risk_units
            nav += pnl
        if curr_m: monthly[curr_m] = nav - 5000.0
        s = pd.Series(monthly).sort_index()
        pos = int((s > 0).sum())
        print(f"{label:20s}: total=${s.sum():+12,.2f}  avg/mo=${s.mean():+8,.2f}  pos={pos}/{len(s)}={pos/len(s)*100:.0f}%  best ${s.max():+,.0f}  worst ${s.min():+,.0f}")
        by_yr = s.groupby(s.index.str[:4]).sum().round(0).to_dict()
        print(f"  per-yr {by_yr}")


if __name__ == "__main__":
    main()
