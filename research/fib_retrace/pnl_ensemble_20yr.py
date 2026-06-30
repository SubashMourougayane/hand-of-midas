"""$5k 3% monthly reset PnL on Fib V2 regime-ensemble over 20.3yr OANDA data."""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

START_NAV = 5000.0; RISK_PCT = 0.03; LEVERAGE = 1000
XAU_CONTRACT = 100; MIN_LOT = 0.01; LOT_STEP = 0.01


def monthly_reset(trades: pd.DataFrame, label: str) -> tuple[pd.Series, pd.DataFrame]:
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    monthly = {}
    nav = START_NAV; curr_month = None
    lots_seen = []; trade_journal = []
    counter = 0
    for r in df.itertuples(index=False):
        counter += 1
        if curr_month is None: curr_month = r.year_month; reset=True; nav=START_NAV
        elif r.year_month != curr_month:
            monthly[curr_month] = nav - START_NAV
            curr_month = r.year_month; nav = START_NAV; reset=True
        else: reset=False
        nav_before = nav
        risk_dollars = nav * RISK_PCT
        risk_units = float(r.risk_units)
        if risk_units <= 0:
            trade_journal.append({"trade_id": counter, "skipped": True}); continue
        raw_lots = risk_dollars / (risk_units * XAU_CONTRACT)
        max_margin_lots = (0.9 * nav * LEVERAGE) / (float(r.entry_price) * XAU_CONTRACT)
        lots = min(raw_lots, max_margin_lots)
        lots = math.floor(lots / LOT_STEP) * LOT_STEP
        if lots < MIN_LOT:
            trade_journal.append({"trade_id": counter, "skipped": True}); continue
        lots_seen.append(lots)
        dollar_per_r = lots * XAU_CONTRACT * risk_units
        pnl = float(r.net_r) * dollar_per_r
        nav += pnl
        trade_journal.append({
            "trade_id": counter, "entry_ts": r.entry_ts, "side": r.side,
            "entry_price": r.entry_price, "stop_price": r.stop_price,
            "tp_price": r.tp_price, "risk_units": risk_units, "net_r": r.net_r,
            "year_month": r.year_month, "year": r.entry_ts.year,
            "account_reset_flag": reset, "nav_before_trade": nav_before,
            "risk_dollars": risk_dollars, "lots": lots, "dollar_per_R": dollar_per_r,
            "pnl_dollars": pnl, "nav_after_trade": nav, "skipped": False,
        })
    if curr_month: monthly[curr_month] = nav - START_NAV
    s = pd.Series(monthly).sort_index(); s.name = label
    jr = pd.DataFrame(trade_journal)
    print(f"\n=== {label} 20.3yr $5k 3% monthly reset ===")
    print(f"trades={len(df)} executed={int((~jr.skipped).sum())} months={len(s)} pos={int((s>0).sum())} neg={int((s<0).sum())}")
    print(f"total=${s.sum():+,.2f}  avg/mo=${s.mean():+,.2f}  median=${s.median():+,.2f}")
    if lots_seen:
        print(f"avg_lots={np.mean(lots_seen):.3f}  max_lots={max(lots_seen):.2f}")
    print(f"best  {s.idxmax()}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin()}: ${s.min():+,.2f}")
    by_yr = s.groupby(s.index.str[:4]).sum().round(2)
    print(f"per-yr ${by_yr.to_dict()}")
    return s, jr


def main():
    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace")
    ens = pd.read_parquet(out_dir / "fib_v2_oanda_ensemble_trades.parquet")
    s_ens, jr_ens = monthly_reset(ens, "ENSEMBLE_20yr")
    long_only = pd.read_parquet(out_dir / "fib_v2_oanda_long_bull_strong_trades.parquet")
    s_long, jr_long = monthly_reset(long_only, "LONG_BULL_STRONG_20yr")
    short_only = pd.read_parquet(out_dir / "fib_v2_oanda_short_bear_strong_trades.parquet")
    s_short, jr_short = monthly_reset(short_only, "SHORT_BEAR_STRONG_20yr")

    # Compound version
    print("\n=== Compound growth (1% risk reinvest, no monthly reset) ===")
    for label, df in [("ENSEMBLE", ens), ("LONG_BULL_STRONG", long_only)]:
        eq = 5000.0; peak = 5000.0; max_dd = 0.0
        df = df.sort_values("entry_ts").reset_index(drop=True)
        for r in df.itertuples(index=False):
            risk_units = float(r.risk_units)
            if risk_units <= 0: continue
            risk_d = eq * 0.01
            lots = math.floor(risk_d / (risk_units * XAU_CONTRACT) / LOT_STEP) * LOT_STEP
            if lots < MIN_LOT: continue
            dollar_per_r = lots * XAU_CONTRACT * risk_units
            eq += float(r.net_r) * dollar_per_r
            peak = max(peak, eq)
            dd = (eq - peak) / peak
            if dd < max_dd: max_dd = dd
        yrs = 20.28
        cagr = (eq / 5000) ** (1/yrs) - 1
        print(f"  {label:20s}: $5k → ${eq:>15,.2f}  CAGR {cagr*100:+.2f}%  MaxDD% {max_dd*100:+.2f}%  ×{eq/5000:.2f}")

    # Write Excel
    out_xlsx = Path("/Users/subash/SUBASH/GoldDigger/research/results/FIB_V2_ENSEMBLE_20YR_JOURNAL.xlsx")
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n[write] {out_xlsx}")
    monthly_df = pd.DataFrame({
        "ENSEMBLE_$": s_ens,
        "LONG_BULL_STRONG_$": s_long,
        "SHORT_BEAR_STRONG_$": s_short,
    }).fillna(0.0)
    monthly_df["LONG+SHORT_combined_$"] = monthly_df["LONG_BULL_STRONG_$"] + monthly_df["SHORT_BEAR_STRONG_$"]
    monthly_df = monthly_df.sort_index()
    yearly_df = monthly_df.copy()
    yearly_df["year"] = yearly_df.index.str[:4]
    yearly_df = yearly_df.groupby("year").sum(numeric_only=True)
    summary = pd.DataFrame([{
        "ensemble_n": len(ens),
        "ensemble_total_$": s_ens.sum(),
        "ensemble_per_year_$": s_ens.sum() / (len(s_ens)/12),
        "ensemble_pos_months_pct": (s_ens>0).mean()*100,
        "ensemble_best_month_$": s_ens.max(),
        "ensemble_worst_month_$": s_ens.min(),
        "long_total_$": s_long.sum(),
        "short_total_$": s_short.sum(),
    }])
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="00_Summary", index=False)
        yearly_df.to_excel(xw, sheet_name="01_PerYear")
        monthly_df.to_excel(xw, sheet_name="02_Monthly")
        jr_ens.to_excel(xw, sheet_name="03_Trades_Ensemble", index=False)
        jr_long.to_excel(xw, sheet_name="04_Trades_Long_Bull", index=False)
        jr_short.to_excel(xw, sheet_name="05_Trades_Short_Bear", index=False)
    print(f"saved → {out_xlsx}")


if __name__ == "__main__":
    main()
