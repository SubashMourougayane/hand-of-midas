"""PnL numbers for TraderzDen TOP1 winner across lot/account sizes.

R = net_r (after cost). $/trade = net_r * risk_per_trade_$.
risk_per_trade_$ = account * risk_pct.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


WINNER = Path(
    "/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/"
    "long_trendH4_pbema20_tol0.3_confclose_sesslondon_sw20_TP4.0R_trades.parquet"
)


def equity_curve(net_r: pd.Series) -> pd.Series:
    return net_r.cumsum()


def stats_block(net_r: pd.Series, label: str):
    eq = equity_curve(net_r)
    peak = eq.cummax()
    dd = eq - peak
    print(f"  {label:<22s} sum={net_r.sum():+.2f}R  best={net_r.max():+.2f}R  "
          f"worst={net_r.min():+.2f}R  maxDD={dd.min():+.2f}R")


def main():
    df = pd.read_parquet(WINNER)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year"] = df["entry_ts"].dt.year
    n = len(df)
    net_total = df["net_r"].sum()
    yrs_span = (df["entry_ts"].max() - df["entry_ts"].min()).total_seconds() / (365.25 * 86400)
    print(f"\n=== TraderzDen TOP1 — PnL ===")
    print(f"trades={n}   years={yrs_span:.2f}   net={net_total:+.2f}R   "
          f"avgR/trade={net_total/n:+.3f}R\n")

    print("[Per-year R breakdown]")
    yr = df.groupby("year")["net_r"].agg(["sum", "count", "mean"]).round(2)
    yr.columns = ["net_R", "trades", "avg_R"]
    print(yr.to_string())

    print("\n[Best / worst single trades]")
    print(df.nlargest(5, "net_r")[["entry_ts", "side", "risk_units", "bracket_r", "net_r"]].to_string(index=False))
    print()
    print(df.nsmallest(5, "net_r")[["entry_ts", "side", "risk_units", "bracket_r", "net_r"]].to_string(index=False))

    # Dollarize across account sizes and risk %
    print("\n=== $-PnL scenarios (full 6.7yr period) ===\n")
    print(f"{'Account ($)':>14s} {'Risk %':>7s} {'$/R':>8s}  {'Net $':>11s}  "
          f"{'Net/yr $':>11s}  {'MaxDD $':>11s}  {'avg/trade $':>13s}")
    print("-" * 96)
    eq_R = equity_curve(df["net_r"])
    dd_R = (eq_R - eq_R.cummax()).min()
    for acct in [1_000, 5_000, 10_000, 25_000, 100_000]:
        for risk_pct in [0.005, 0.01, 0.02]:
            dollar_per_R = acct * risk_pct
            net_usd = net_total * dollar_per_R
            net_per_yr = net_usd / yrs_span
            dd_usd = dd_R * dollar_per_R
            avg = (net_total / n) * dollar_per_R
            print(f"{acct:>14,d} {risk_pct*100:>6.1f}% {dollar_per_R:>8.2f}  "
                  f"{net_usd:>+11,.0f}  {net_per_yr:>+11,.0f}  {dd_usd:>+11,.0f}  {avg:>+13,.2f}")

    # Compound growth (fixed-fractional reinvestment, 1% risk each trade)
    print("\n=== Compound growth (1% risk fractional reinvest) ===\n")
    for acct in [1_000, 5_000, 10_000, 25_000, 100_000]:
        eq = acct
        peak = acct
        max_dd_pct = 0.0
        for r in df["net_r"].values:
            risk_usd = eq * 0.01
            eq += r * risk_usd
            peak = max(peak, eq)
            dd_pct = (eq - peak) / peak
            if dd_pct < max_dd_pct:
                max_dd_pct = dd_pct
        cagr = (eq / acct) ** (1 / yrs_span) - 1
        print(f"  start ${acct:>8,d} → end ${eq:>14,.2f}   "
              f"CAGR {cagr*100:>+6.2f}%   maxDD% {max_dd_pct*100:>+6.2f}%   "
              f"× {eq/acct:>5.2f}")

    # Mix-in scenario: Martin Luke baseline (255.5R / 6.4yr / dd -14.1R) + TraderzDen
    print("\n=== Portfolio (Martin Luke + TraderzDen, equal $/R weight, no signal de-dup) ===\n")
    ml_net = 255.5; ml_yrs = 6.4; ml_dd = -14.1
    td_net = net_total; td_yrs = yrs_span; td_dd = dd_R
    for acct in [10_000, 25_000, 100_000]:
        for risk_pct in [0.005, 0.01]:
            d = acct * risk_pct
            ml_usd = ml_net * d
            td_usd = td_net * d
            combined = ml_usd + td_usd
            combined_yr = combined / max(ml_yrs, td_yrs)
            combined_dd = (ml_dd + td_dd) * d  # upper bound (correlated DD)
            print(f"  acct ${acct:>7,d} risk {risk_pct*100:.1f}%  ML ${ml_usd:>+8,.0f}  "
                  f"TD ${td_usd:>+8,.0f}  total ${combined:>+9,.0f} "
                  f"(${combined_yr:>+7,.0f}/yr, worst DD ${combined_dd:>+7,.0f})")


if __name__ == "__main__":
    main()
