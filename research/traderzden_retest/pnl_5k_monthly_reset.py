"""$5k monthly-reset PnL — 3% risk per trade, lots scaled to live NAV.

Rules:
  - Start each calendar month with $5,000.
  - Per trade: risk_$ = current NAV * 0.03.
  - Lots = floor( risk_$ / (risk_units_usd * 100) )   [XAU: 1 lot = 100 oz, $1/oz price move = $100/lot]
  - Margin check: required_margin = entry_price * lots * 100 / leverage (1:1000).
    If margin > free NAV → reduce lots until fits.
  - $/trade = lots * 100 * net_r * risk_units
  - At first trade of a NEW month, reset NAV to $5,000.
  - End-of-month profit = current NAV - $5,000 (or loss).
  - Sum across months = total $ pocketed (assuming monthly withdrawal).

Output:
  - Per-month $ profit + lot stats
  - Total $ profit
  - Best / worst months
  - vs Martin Luke same scheme
"""
from __future__ import annotations

from pathlib import Path
import math
import numpy as np
import pandas as pd


WINNER = Path(
    "/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/"
    "long_trendH4_pbema20_tol0.3_confclose_sesslondon_sw20_TP4.0R_trades.parquet"
)
MARTIN_LUKE = Path(
    "/Users/subash/SUBASH/GoldDigger/research/martin_luke/"
    "xau_PDH_plus_uptrend_TP=3.0R_trades.parquet"
)

START_NAV = 5000.0
RISK_PCT = 0.03
LEVERAGE = 1000
XAU_CONTRACT = 100  # 1 lot = 100 oz, $1 price move = $100/lot
MIN_LOT = 0.01
LOT_STEP = 0.01


def simulate_monthly_reset(trades_df: pd.DataFrame, *, label: str):
    df = trades_df.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")

    rows = []
    monthly_summary = {}
    nav = START_NAV
    current_month = None
    intra_month_peak = START_NAV
    intra_month_trough = START_NAV
    skipped_margin = 0
    skipped_lot = 0
    lots_seen = []

    for r in df.itertuples(index=False):
        # Month rollover → reset
        if current_month is None:
            current_month = r.year_month
        if r.year_month != current_month:
            # close out previous month
            monthly_summary[current_month] = {
                "end_nav": nav,
                "profit": nav - START_NAV,
                "peak": intra_month_peak,
                "trough": intra_month_trough,
                "intra_dd": intra_month_trough - intra_month_peak,
            }
            current_month = r.year_month
            nav = START_NAV
            intra_month_peak = START_NAV
            intra_month_trough = START_NAV

        # Sizing
        risk_dollars = nav * RISK_PCT
        risk_units = float(r.risk_units)
        if risk_units <= 0:
            continue
        # Raw target lots
        raw_lots = risk_dollars / (risk_units * XAU_CONTRACT)
        # Margin cap: entry_price * lots * 100 / leverage <= 0.9 * nav (leave 10% buffer)
        entry_price = float(r.entry_price)
        max_margin_lots = (0.9 * nav * LEVERAGE) / (entry_price * XAU_CONTRACT)
        lots = min(raw_lots, max_margin_lots)
        # Round to step
        lots = math.floor(lots / LOT_STEP) * LOT_STEP
        if lots < MIN_LOT:
            skipped_lot += 1
            continue
        if max_margin_lots < MIN_LOT:
            skipped_margin += 1
            continue
        lots_seen.append(lots)

        # $/trade: net_r is in R-multiples after cost; $ per R = lots * 100 * risk_units
        dollar_per_r = lots * XAU_CONTRACT * risk_units
        pnl = float(r.net_r) * dollar_per_r
        nav += pnl
        intra_month_peak = max(intra_month_peak, nav)
        intra_month_trough = min(intra_month_trough, nav)

        rows.append({
            "month": r.year_month, "entry_ts": r.entry_ts, "lots": lots,
            "risk_$": risk_dollars, "risk_units": risk_units,
            "$/R": dollar_per_r, "net_r": float(r.net_r), "pnl_$": pnl,
            "nav_after": nav,
        })

    # Close last month
    if current_month is not None:
        monthly_summary[current_month] = {
            "end_nav": nav,
            "profit": nav - START_NAV,
            "peak": intra_month_peak,
            "trough": intra_month_trough,
            "intra_dd": intra_month_trough - intra_month_peak,
        }

    out = pd.DataFrame(rows)
    summary = pd.DataFrame(monthly_summary).T.reset_index().rename(columns={"index": "month"})
    summary = summary.sort_values("month").reset_index(drop=True)

    print(f"\n=== {label}: $5k account, monthly reset, 3% risk ===\n")
    print(f"trades_executed={len(out)}  skipped_lot_too_small={skipped_lot}  "
          f"skipped_margin={skipped_margin}")
    print(f"avg_lots={np.mean(lots_seen):.3f}  median_lots={np.median(lots_seen):.3f}  "
          f"max_lots={max(lots_seen) if lots_seen else 0:.2f}  min_lots={min(lots_seen) if lots_seen else 0:.2f}")

    months_total = len(summary)
    months_pos = int((summary["profit"] > 0).sum())
    months_neg = int((summary["profit"] < 0).sum())
    months_flat = int((summary["profit"] == 0).sum())
    total_profit = float(summary["profit"].sum())
    avg_month = float(summary["profit"].mean())
    median_month = float(summary["profit"].median())
    best_month = summary.loc[summary["profit"].idxmax()]
    worst_month = summary.loc[summary["profit"].idxmin()]

    print(f"\nmonths={months_total}  pos={months_pos}  neg={months_neg}  flat={months_flat}")
    print(f"total_pocketed=${total_profit:+,.2f}   avg/month=${avg_month:+,.2f}   median/month=${median_month:+,.2f}")
    print(f"best  {best_month['month']}: end ${best_month['end_nav']:,.0f}  profit ${best_month['profit']:+,.0f}")
    print(f"worst {worst_month['month']}: end ${worst_month['end_nav']:,.0f}  profit ${worst_month['profit']:+,.0f}")

    # Per-year totals
    summary["year"] = summary["month"].str.slice(0, 4)
    by_year = summary.groupby("year")["profit"].agg(["sum", "count"]).round(2)
    by_year.columns = ["$_total", "months"]
    by_year["$/month"] = (by_year["$_total"] / by_year["months"]).round(2)
    print("\n[Per-year $ pocketed]")
    print(by_year.to_string())

    # Worst 5 / best 5 months
    print("\n[Top 5 months]")
    print(summary.nlargest(5, "profit")[["month", "end_nav", "profit", "intra_dd"]].to_string(index=False))
    print("\n[Bottom 5 months]")
    print(summary.nsmallest(5, "profit")[["month", "end_nav", "profit", "intra_dd"]].to_string(index=False))

    return summary, out


def main():
    print("=" * 80)
    td = pd.read_parquet(WINNER)
    s_td, _ = simulate_monthly_reset(td, label="TraderzDen TOP1")

    print("\n" + "=" * 80)
    ml = pd.read_parquet(MARTIN_LUKE)
    # Martin Luke parquet uses different cols — check & adapt
    if "entry_ts" not in ml.columns:
        # Probably entry_timestamp
        if "entry_timestamp" in ml.columns:
            ml = ml.rename(columns={"entry_timestamp": "entry_ts"})
    if "risk_units" not in ml.columns:
        ml["risk_units"] = ml["entry_price"] - ml["stop_price"] if "stop_price" in ml.columns else 1.0
    s_ml, _ = simulate_monthly_reset(ml, label="Martin Luke")

    # Portfolio: trade both (independent $5k accounts since each gets reset)
    print("\n" + "=" * 80)
    print("\n=== Portfolio (separate $5k each: TraderzDen + Martin Luke) ===\n")
    merged = pd.merge(
        s_td[["month", "profit"]].rename(columns={"profit": "td_$"}),
        s_ml[["month", "profit"]].rename(columns={"profit": "ml_$"}),
        on="month", how="outer", indicator=False,
    ).fillna(0.0)
    merged["combined_$"] = merged["td_$"] + merged["ml_$"]
    merged = merged.sort_values("month").reset_index(drop=True)
    print(f"total_combined=${merged['combined_$'].sum():+,.2f}  "
          f"avg/month=${merged['combined_$'].mean():+,.2f}  "
          f"months={len(merged)}")
    pos = int((merged['combined_$'] > 0).sum())
    print(f"combined pos months={pos}/{len(merged)} ({pos/len(merged)*100:.1f}%)")
    print("\n[Combined top/bottom 5 months]")
    print(merged.nlargest(5, "combined_$").to_string(index=False))
    print()
    print(merged.nsmallest(5, "combined_$").to_string(index=False))


if __name__ == "__main__":
    main()
