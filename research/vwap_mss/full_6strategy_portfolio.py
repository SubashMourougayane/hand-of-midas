"""6-strategy portfolio: Martin Luke + TraderzDen + FVG long + FVG short
+ VWAP-MSS short + VWAP-MSS long. $5k each, 3% risk, monthly reset.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


START_NAV = 5000.0
RISK_PCT = 0.03
LEVERAGE = 1000
XAU_CONTRACT = 100
MIN_LOT = 0.01
LOT_STEP = 0.01


def monthly_reset(trades: pd.DataFrame, label: str) -> pd.Series:
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    monthly = {}
    nav = START_NAV; curr_month = None
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
        dollar_per_r = lots * XAU_CONTRACT * risk_units
        pnl = float(r.net_r) * dollar_per_r
        nav += pnl
    if curr_month: monthly[curr_month] = nav - START_NAV
    s = pd.Series(monthly).sort_index()
    s.name = label
    return s


PATHS = {
    "Martin_Luke": Path("/Users/subash/SUBASH/GoldDigger/research/martin_luke/xau_PDH_plus_uptrend_TP=3.0R_trades.parquet"),
    "TraderzDen": Path("/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/long_trendH4_pbema20_tol0.3_confclose_sesslondon_sw20_TP4.0R_trades.parquet"),
    "FVG_short_age4h": Path("/Users/subash/SUBASH/GoldDigger/research/fvg_nested/short_age4h_sessall_sw20_inside0_TP4.0R_trades.parquet"),
    "FVG_long_age4h": Path("/Users/subash/SUBASH/GoldDigger/research/fvg_nested/long_age4h_sessall_sw30_inside0_TP4.0R_trades.parquet"),
    "VWAP_short_M15": Path("/Users/subash/SUBASH/GoldDigger/research/vwap_mss/short_M15_sw3_sessny_atr1.5_prox0.5_wait5_RR4.0_trades.parquet"),
    "VWAP_long_M5": Path("/Users/subash/SUBASH/GoldDigger/research/vwap_mss/long_M5_sw7_sessny_atr2.0_prox1.0_wait3_RR4.0_trades.parquet"),
}


def main():
    series = {}
    for k, p in PATHS.items():
        if not p.exists():
            print(f"MISSING: {p}")
            continue
        df = pd.read_parquet(p)
        s = monthly_reset(df, k)
        series[k] = s
        print(f"{k:30s} n={len(df):5d}  months={len(s):3d}  total=${s.sum():+10,.2f}  avg=${s.mean():+8,.2f}/mo")

    port = pd.DataFrame(series).fillna(0.0)
    port["total_$"] = port.sum(axis=1)
    yrs = len(port) / 12
    print(f"\n=== 6-STRATEGY PORTFOLIO ===")
    print(f"Months: {len(port)}  Years: {yrs:.2f}  Deployed: ${5000 * len(series):,}")
    print(f"Total pocketed: ${port['total_$'].sum():+,.2f}")
    print(f"Per month avg:  ${port['total_$'].mean():+,.2f}")
    print(f"Per year:       ${port['total_$'].sum()/yrs:+,.2f}/yr")
    pos = int((port["total_$"] > 0).sum())
    print(f"Pos months:     {pos}/{len(port)} = {pos/len(port)*100:.1f}%")
    print(f"Best month  {port['total_$'].idxmax()}: ${port['total_$'].max():+,.2f}")
    print(f"Worst month {port['total_$'].idxmin()}: ${port['total_$'].min():+,.2f}")

    by_year = port.groupby(port.index.str[:4])["total_$"].sum().round(2)
    print(f"\n[Per-year $ across all 6 accounts]")
    print(by_year.to_string())

    # Compute portfolio Sharpe
    monthly_returns = port["total_$"] / (5000 * len(series))
    sharpe = monthly_returns.mean() / monthly_returns.std() * np.sqrt(12)
    print(f"\nMonthly Sharpe (annualised): {sharpe:.2f}")

    # Max drawdown on cumulative
    eq = port["total_$"].cumsum()
    peak = eq.cummax()
    dd = eq - peak
    print(f"Max cumulative DD: ${dd.min():+,.2f}")
    deployed = 5000 * len(series)
    print(f"Max DD as % deployed: {dd.min()/deployed*100:.2f}%")

    out_path = Path("/Users/subash/SUBASH/GoldDigger/research/vwap_mss/6_strategy_portfolio_monthly.csv")
    port.to_csv(out_path)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
