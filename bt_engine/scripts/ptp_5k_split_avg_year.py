"""Single $5k account split across XAU + EUR (PTP+1R and PTP+2R variants).

Both legs run on the SAME account. Risk allocated per-symbol via fixed pct.
Compute average-year PNL, WR, PF, R:R, return%.

Account model:
  - Single $5,000 account, monthly reset (each month: equity → $5,000).
  - Each trade risks max_risk_pct of CURRENT equity (split between XAU + EUR).
  - net_r = R-multiple result per trade (matches bt_engine outcome).
  - dollar_pnl_per_trade = net_r * risk_dollar_per_trade.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PTP_DIR = Path("/Users/subash/SUBASH/GoldDigger/bt_engine/evidence/fib_v2_ptp_anatomy")
ACCOUNT_START = 5000.0
TOTAL_RISK_PCT = 0.03  # 3% of equity per "round" — split across both symbols equally
XAU_RISK_PCT = TOTAL_RISK_PCT / 2  # 1.5% XAU
EUR_RISK_PCT = TOTAL_RISK_PCT / 2  # 1.5% EUR
RESET_MONTHLY = True


def load_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["year"] = df["entry_ts"].dt.year
    df["month"] = df["entry_ts"].dt.to_period("M").astype(str)
    return df.sort_values("entry_ts").reset_index(drop=True)


def headline(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0}
    wins = int((df["net_r"] > 0).sum())
    losses = int((df["net_r"] <= 0).sum())
    wr = wins / n * 100
    gross_win = float(df.loc[df["net_r"] > 0, "net_r"].sum())
    gross_loss = -float(df.loc[df["net_r"] < 0, "net_r"].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    avg_win = float(df.loc[df["net_r"] > 0, "net_r"].mean()) if wins > 0 else 0.0
    avg_loss = -float(df.loc[df["net_r"] < 0, "net_r"].mean()) if losses > 0 else 0.0
    rr = avg_win / avg_loss if avg_loss > 0 else float("inf")
    net_r = float(df["net_r"].sum())
    return {
        "n": n, "WR%": round(wr, 2), "PF": round(pf, 3),
        "avg_win_R": round(avg_win, 3), "avg_loss_R": round(avg_loss, 3),
        "R:R": round(rr, 3), "net_R": round(net_r, 1),
    }


def simulate_dual_account(xau: pd.DataFrame, eur: pd.DataFrame,
                          *, xau_risk_pct: float, eur_risk_pct: float,
                          start: float = ACCOUNT_START,
                          monthly_reset: bool = True) -> pd.DataFrame:
    """Single shared $start account. Both XAU + EUR trade on it.

    On each trade entry (chronological order across both feeds):
      risk_dollar = current_equity * symbol_risk_pct
      pnl = net_r * risk_dollar
      equity += pnl

    Monthly reset: on first trade of new month, equity → start.
    Year aggregation: $ pnl summed within each calendar year.
    """
    xau = xau.copy(); xau["symbol_tag"] = "XAU"; xau["risk_pct"] = xau_risk_pct
    eur = eur.copy(); eur["symbol_tag"] = "EUR"; eur["risk_pct"] = eur_risk_pct
    all_trades = pd.concat([xau, eur], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)

    equity = start
    last_month = None
    rows = []
    for r in all_trades.itertuples(index=False):
        m = str(r.month)
        if monthly_reset and m != last_month:
            equity = start
            last_month = m
        risk_dollar = equity * r.risk_pct
        dollar_pnl = r.net_r * risk_dollar
        equity += dollar_pnl
        rows.append({
            "year": r.year, "month": m, "symbol": r.symbol_tag,
            "entry_ts": r.entry_ts, "net_r": r.net_r,
            "risk_dollar": risk_dollar, "dollar_pnl": dollar_pnl,
            "equity_after": equity,
        })
    return pd.DataFrame(rows)


def yearly_pnl(sim: pd.DataFrame) -> pd.DataFrame:
    g = sim.groupby("year").agg(
        n_trades=("dollar_pnl", "count"),
        dollar_pnl=("dollar_pnl", "sum"),
        wins=("dollar_pnl", lambda s: int((s > 0).sum())),
    ).reset_index()
    g["WR%"] = (g["wins"] / g["n_trades"] * 100).round(2)
    return g


def avg_year_stats(xau: pd.DataFrame, eur: pd.DataFrame, *, label: str,
                   xau_risk_pct: float, eur_risk_pct: float) -> dict:
    sim = simulate_dual_account(xau, eur, xau_risk_pct=xau_risk_pct,
                                  eur_risk_pct=eur_risk_pct,
                                  start=ACCOUNT_START, monthly_reset=RESET_MONTHLY)
    by_year = yearly_pnl(sim)
    # Drop partial-coverage years (first + last if <80% trade count of median).
    if len(by_year) >= 3:
        median_n = by_year["n_trades"].median()
        full_years = by_year[by_year["n_trades"] >= 0.7 * median_n]
    else:
        full_years = by_year

    combined_trades = pd.concat([xau, eur], ignore_index=True)
    combined_head = headline(combined_trades)
    xau_head = headline(xau)
    eur_head = headline(eur)

    avg_year_pnl = float(full_years["dollar_pnl"].mean()) if len(full_years) else 0.0
    avg_year_pct = avg_year_pnl / ACCOUNT_START * 100
    avg_year_trades = float(full_years["n_trades"].mean()) if len(full_years) else 0.0
    pos_years = int((full_years["dollar_pnl"] > 0).sum())

    return {
        "label": label,
        "covered_years": len(full_years),
        "pos_years": f"{pos_years}/{len(full_years)}",
        "avg_year_trades": round(avg_year_trades, 0),
        "combined_WR%": combined_head["WR%"],
        "combined_PF": combined_head["PF"],
        "combined_R:R": combined_head["R:R"],
        "XAU_WR%": xau_head["WR%"],
        "XAU_PF": xau_head["PF"],
        "EUR_WR%": eur_head["WR%"],
        "EUR_PF": eur_head["PF"],
        "avg_year_pnl_$": round(avg_year_pnl, 0),
        "avg_year_return%": round(avg_year_pct, 1),
        "by_year": by_year,
    }


def main():
    variants = [
        ("PTP+1R", "xau_ensemble_ptp1r_trades.csv", "eur_ensemble_ptp1r_trades.csv"),
        ("PTP+2R", "xau_ensemble_ptp2r_trades.csv", "eur_ensemble_ptp2r_trades.csv"),
    ]
    print(f"\n$5,000 account, monthly reset, 3% total risk split: 1.5% XAU + 1.5% EUR")
    print("=" * 96)
    for label, xau_file, eur_file in variants:
        xau = load_trades(PTP_DIR / xau_file)
        eur = load_trades(PTP_DIR / eur_file)
        res = avg_year_stats(xau, eur, label=label,
                              xau_risk_pct=XAU_RISK_PCT, eur_risk_pct=EUR_RISK_PCT)
        print(f"\n[{res['label']}] covered years: {res['covered_years']} ({res['pos_years']} positive)")
        print(f"  avg year trades: {res['avg_year_trades']:.0f}")
        print(f"  COMBINED      WR={res['combined_WR%']}%  PF={res['combined_PF']}  R:R={res['combined_R:R']}")
        print(f"  XAU leg       WR={res['XAU_WR%']}%  PF={res['XAU_PF']}")
        print(f"  EUR leg       WR={res['EUR_WR%']}%  PF={res['EUR_PF']}")
        print(f"  >>> AVG YEAR  PNL=${res['avg_year_pnl_$']:>8,.0f}  RETURN={res['avg_year_return%']:>6.1f}%")
        print(f"  by-year breakdown:")
        print(res["by_year"].to_string(index=False))


if __name__ == "__main__":
    main()
