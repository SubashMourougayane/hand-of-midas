"""Audit top VWAP MSS variants + PnL + 5-strategy portfolio."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, headline, print_headline
from research.vwap_mss.run_vwap_mss import (
    resample, build_features, gen_signals, simulate_rr
)


TOP = [
    dict(tf="M15", direction="short", session="ny", swing=3,
         atr_mult=1.5, retest_prox=0.5, wait=5, rr=4.0,
         label="short_M15_ny_sw3_atr1.5_prox0.5_wait5_RR4"),
    dict(tf="M5", direction="long", session="ny", swing=7,
         atr_mult=2.0, retest_prox=1.0, wait=3, rr=4.0,
         label="long_M5_ny_sw7_atr2.0_prox1.0_wait3_RR4"),
    dict(tf="M15", direction="long", session="london_ny", swing=10,
         atr_mult=0.8, retest_prox=1.0, wait=8, rr=4.0,
         label="long_M15_london_ny_sw10_atr0.8_prox1.0_wait8_RR4"),
    dict(tf="M5", direction="long", session="overlap", swing=7,
         atr_mult=2.0, retest_prox=1.0, wait=3, rr=4.0,
         label="long_M5_overlap_sw7_atr2.0_prox1.0_wait3_RR4"),
]


def audit_one(label, feat, sigs, rr_base, horizon):
    if len(sigs) == 0:
        print(f"\n=== {label}: NO SIGNALS"); return None
    print(f"\n=== AUDIT {label} ===\nsignals: {len(sigs)}")
    h0 = headline(simulate_rr(feat, sigs, rr=rr_base, horizon_bars=horizon))
    print_headline("baseline", h0)
    for d in [1, 3, 5, 10]:
        s = sigs.copy(); s["entry_index"] = s["entry_index"].astype(int) + d
        h = headline(simulate_rr(feat, s, rr=rr_base, horizon_bars=horizon))
        print_headline(f"+{d} bar delay", h)
    flip = sigs.copy(); flip["side"] = -flip["side"].astype(int)
    h = headline(simulate_rr(feat, flip, rr=rr_base, horizon_bars=horizon))
    print_headline("FLIP", h)
    for extra in [0.10, 0.20, 0.50]:
        h = headline(simulate_rr(feat, sigs, rr=rr_base, horizon_bars=horizon, cost_usd=0.30 + extra))
        print_headline(f"cost+${extra:.2f}", h)
    is_mask = sigs["entry_index"].values < int(0.6 * len(feat))
    h_is = headline(simulate_rr(feat, sigs[is_mask], rr=rr_base, horizon_bars=horizon))
    h_oos = headline(simulate_rr(feat, sigs[~is_mask], rr=rr_base, horizon_bars=horizon))
    print_headline("IS first 60%", h_is)
    print_headline("OOS last 40%", h_oos)
    trades = simulate_rr(feat, sigs, rr=rr_base, horizon_bars=horizon)
    if len(trades) > 5:
        rng = np.random.default_rng(42)
        nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                          random_state=rng.integers(10**9)).sum() for _ in range(3000)])
        print(f"BOOTSTRAP n=3000: P(net<0)={(nets<0).mean()*100:.2f}%  p05={np.percentile(nets,5):+.1f}R")
    if len(trades):
        y = trades.groupby("year")["net_r"].sum().round(2)
        print(f"by year: {y.to_dict()}")
    return trades


def monthly_reset_pnl(trades, label, *, start_nav=5000.0, risk_pct=0.03,
                     leverage=1000, xau_contract=100, min_lot=0.01, lot_step=0.01):
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    monthly = {}
    nav = start_nav; curr_month = None
    lots_seen = []
    for r in df.itertuples(index=False):
        if curr_month is None: curr_month = r.year_month
        if r.year_month != curr_month:
            monthly[curr_month] = nav - start_nav
            curr_month = r.year_month
            nav = start_nav
        risk_dollars = nav * risk_pct
        risk_units = float(r.risk_units)
        if risk_units <= 0: continue
        raw_lots = risk_dollars / (risk_units * xau_contract)
        max_margin_lots = (0.9 * nav * leverage) / (float(r.entry_price) * xau_contract)
        lots = min(raw_lots, max_margin_lots)
        lots = math.floor(lots / lot_step) * lot_step
        if lots < min_lot: continue
        lots_seen.append(lots)
        dollar_per_r = lots * xau_contract * risk_units
        pnl = float(r.net_r) * dollar_per_r
        nav += pnl
    if curr_month: monthly[curr_month] = nav - start_nav
    s = pd.Series(monthly).sort_index()
    pos = int((s > 0).sum()); neg = int((s < 0).sum())
    print(f"\n=== {label}: $5k 3% monthly reset ===")
    print(f"trades={len(df)} months={len(s)} pos={pos} neg={neg}")
    print(f"total=${s.sum():+,.2f}  avg/mo=${s.mean():+,.2f}  median=${s.median():+,.2f}")
    print(f"avg_lots={np.mean(lots_seen):.3f} max_lots={max(lots_seen) if lots_seen else 0:.2f}")
    print(f"best  {s.idxmax() if pos else 'na'}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin() if neg else 'na'}: ${s.min():+,.2f}")
    by_yr = s.groupby(s.index.str[:4]).sum().round(2).to_dict()
    print(f"per-yr {by_yr}")
    return s


def main():
    print("[load] frames...")
    m1, m5, _ = load_data()
    tf_frames = {"M5": m5, "M15": resample(m1, "15min")}
    for k, df in tf_frames.items():
        if "ny_hr" not in df.columns:
            df["ny_hr"] = df["timestamp"].dt.tz_convert("America/New_York").dt.hour
            df["year"] = df["timestamp"].dt.year

    survivors = {}
    for cfg in TOP:
        feat = build_features(tf_frames[cfg["tf"]], swing_lookback=cfg["swing"])
        horizon = 288 if cfg["tf"] == "M5" else 96
        sigs = gen_signals(feat, direction=cfg["direction"], session=cfg["session"],
                           retest_prox=cfg["retest_prox"], atr_mult=cfg["atr_mult"],
                           wait_window=cfg["wait"])
        trades = audit_one(cfg["label"], feat, sigs, cfg["rr"], horizon)
        if trades is not None and len(trades) > 0:
            survivors[cfg["label"]] = trades

    print("\n\n" + "=" * 80)
    print("PnL — top 2 survivors\n")
    pnl_series = {}
    # Pick the top 2 with PF >= 1.3 AND pos >= 7
    keep = []
    for label, tr in survivors.items():
        h = headline(tr)
        pos = int(h["pos_years"].split("/")[0])
        if h["pf"] >= 1.3 and pos >= 7:
            keep.append((label, tr))
    for label, tr in keep:
        pnl_series[label] = monthly_reset_pnl(tr, label)

    if not pnl_series:
        print("[no survivors clear PF>=1.3 + 7/8 yrs]")
        return

    print("\n=== Stack with existing 4 winners ===\n")
    paths = {
        "Martin_Luke": Path("/Users/subash/SUBASH/GoldDigger/research/martin_luke/xau_PDH_plus_uptrend_TP=3.0R_trades.parquet"),
        "TraderzDen":  Path("/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/long_trendH4_pbema20_tol0.3_confclose_sesslondon_sw20_TP4.0R_trades.parquet"),
    }
    extras = {}
    for k, p in paths.items():
        df = pd.read_parquet(p)
        extras[k] = monthly_reset_pnl(df, k)

    # FVG winners (regenerate quickly via cached trades parquet if available, else skip)
    fvg_dir = Path("/Users/subash/SUBASH/GoldDigger/research/fvg_nested")
    for fn in fvg_dir.glob("*_trades.parquet"):
        name = fn.stem
        if "short_age4h_all_sw20_inside0_TP4.0R" in name or "long_age4h_all_sw30_inside0_TP4.0R" in name:
            df = pd.read_parquet(fn)
            extras[f"FVG_{name}"] = monthly_reset_pnl(df, f"FVG_{name}")

    # Build full portfolio
    all_series = {**pnl_series, **extras}
    port = pd.DataFrame(all_series).fillna(0.0)
    port["total_$"] = port.sum(axis=1)
    print(f"\n=== PORTFOLIO ({len(all_series)} strategies x $5k each) ===")
    print(f"Strategies: {list(all_series.keys())}")
    print(f"Months covered: {len(port)}")
    print(f"Total deployed:  ${5000 * len(all_series):,}")
    print(f"Total pocketed:  ${port['total_$'].sum():+,.2f}")
    print(f"$/month avg:     ${port['total_$'].mean():+,.2f}")
    yrs = len(port) / 12
    print(f"$/year (yrs={yrs:.1f}): ${port['total_$'].sum()/yrs:+,.2f}/yr")
    pos = int((port["total_$"] > 0).sum())
    print(f"Pos months: {pos}/{len(port)} = {pos/len(port)*100:.1f}%")
    print(f"Best month  {port['total_$'].idxmax()}: ${port['total_$'].max():+,.2f}")
    print(f"Worst month {port['total_$'].idxmin()}: ${port['total_$'].min():+,.2f}")
    out_path = Path("/Users/subash/SUBASH/GoldDigger/research/vwap_mss/full_portfolio_monthly.csv")
    port.to_csv(out_path)
    print(f"\nSaved → {out_path}")
    by_year = port.groupby(port.index.str[:4])["total_$"].sum().round(2)
    print("\n[Per-year $ pocketed (sum across all strategies)]")
    print(by_year.to_string())


if __name__ == "__main__":
    main()
