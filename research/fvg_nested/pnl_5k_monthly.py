"""$5k account, 3% risk, monthly reset, max lots by NAV — for FVG winners."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data
from research.fvg_nested.run_fvg_fast import (
    resample, detect_fvgs, gen_signals_fast, simulate_with_limit
)


START_NAV = 5000.0
RISK_PCT = 0.03
LEVERAGE = 1000
XAU_CONTRACT = 100
MIN_LOT = 0.01
LOT_STEP = 0.01


def monthly_reset_pnl(trades: pd.DataFrame, label: str):
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    monthly = {}
    nav = START_NAV
    curr_month = None
    lots_seen = []
    for r in df.itertuples(index=False):
        if curr_month is None:
            curr_month = r.year_month
        if r.year_month != curr_month:
            monthly[curr_month] = nav - START_NAV
            curr_month = r.year_month
            nav = START_NAV
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
    print(f"\n=== {label}: $5k 3% monthly reset ===")
    print(f"trades={len(df)} months={len(s)} pos={int((s>0).sum())} neg={int((s<0).sum())}")
    print(f"total=${s.sum():+,.2f}  avg/month=${s.mean():+,.2f}  median=${s.median():+,.2f}")
    print(f"avg_lots={np.mean(lots_seen):.3f} max_lots={max(lots_seen) if lots_seen else 0:.2f}")
    print(f"best  {s.idxmax()}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin()}: ${s.min():+,.2f}")
    print(f"per-year ${s.groupby(s.index.str[:4]).sum().round(2).to_dict()}")
    return s


def main():
    print("[load] frames + FVGs...")
    m1, m5, _ = load_data()
    h4_fvgs = detect_fvgs(resample(m1, "4h"))
    m15_fvgs = detect_fvgs(resample(m1, "15min"))
    m5_arr = {"open": m5["open"].values, "high": m5["high"].values,
              "low": m5["low"].values, "close": m5["close"].values,
              "ts": m5["timestamp"].values, "year": m5["year"].values}

    # SHORT winner
    sigs_s = gen_signals_fast(m5, h4_fvgs, m15_fvgs, direction="short",
                              fvg_max_age_h=4, session="all", swing_lookback=20,
                              require_m15_inside_h4=False)
    trades_s = simulate_with_limit(m5_arr, sigs_s, tp_mult=4.0)
    s_short = monthly_reset_pnl(trades_s, "FVG short_age4h_all_sw20_inside0_TP4R")

    # LONG winner
    sigs_l = gen_signals_fast(m5, h4_fvgs, m15_fvgs, direction="long",
                              fvg_max_age_h=4, session="all", swing_lookback=30,
                              require_m15_inside_h4=False)
    trades_l = simulate_with_limit(m5_arr, sigs_l, tp_mult=4.0)
    s_long = monthly_reset_pnl(trades_l, "FVG long_age4h_all_sw30_inside0_TP4R")

    # Combined separate-accounts FVG portfolio
    merged = pd.DataFrame({"short_$": s_short, "long_$": s_long}).fillna(0.0)
    merged["combined_$"] = merged["short_$"] + merged["long_$"]
    print("\n=== FVG combined (separate $5k each) ===")
    print(f"months={len(merged)} pos={int((merged['combined_$']>0).sum())}")
    print(f"total=${merged['combined_$'].sum():+,.2f}  avg/month=${merged['combined_$'].mean():+,.2f}")

    # Now triple stack with TraderzDen + Martin Luke
    print("\n=== Three-strategy portfolio ($5k each, monthly reset) ===")
    td_winner = Path("/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/"
                     "long_trendH4_pbema20_tol0.3_confclose_sesslondon_sw20_TP4.0R_trades.parquet")
    ml_winner = Path("/Users/subash/SUBASH/GoldDigger/research/martin_luke/"
                     "xau_PDH_plus_uptrend_TP=3.0R_trades.parquet")
    td = pd.read_parquet(td_winner)
    ml = pd.read_parquet(ml_winner)
    s_td = monthly_reset_pnl(td, "TraderzDen TOP1")
    s_ml = monthly_reset_pnl(ml, "Martin Luke")
    portfolio = pd.DataFrame({
        "fvg_short_$": s_short, "fvg_long_$": s_long,
        "traderzden_$": s_td, "martin_luke_$": s_ml,
    }).fillna(0.0)
    portfolio["total_$"] = portfolio.sum(axis=1)
    print(f"\nMonths covered: {len(portfolio)}")
    print(f"Total pocketed: ${portfolio['total_$'].sum():+,.2f}")
    print(f"Per month avg : ${portfolio['total_$'].mean():+,.2f}")
    print(f"Per year (yrs={len(portfolio)/12:.1f}): ${portfolio['total_$'].sum()/(len(portfolio)/12):+,.2f}/yr")
    pos = int((portfolio['total_$'] > 0).sum())
    print(f"Positive months: {pos}/{len(portfolio)} = {pos/len(portfolio)*100:.1f}%")
    print(f"Best month  {portfolio['total_$'].idxmax()}: ${portfolio['total_$'].max():+,.2f}")
    print(f"Worst month {portfolio['total_$'].idxmin()}: ${portfolio['total_$'].min():+,.2f}")
    out_path = Path("/Users/subash/SUBASH/GoldDigger/research/fvg_nested/4_strategy_portfolio_monthly.csv")
    portfolio.to_csv(out_path)
    print(f"\nSaved → {out_path}")
    by_year = portfolio.groupby(portfolio.index.str[:4])["total_$"].sum().round(2)
    print("\n[Per-year $ pocketed (sum across 4 separate $5k accounts)]")
    print(by_year.to_string())


if __name__ == "__main__":
    main()
