from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "results" / "base"
STRESS = ROOT / "results" / "stress"
DOCS = ROOT / "docs"
TRADES = BASE / "base_sleeve1_trades.csv"
R_COL = "net_r"
SEED = 29062026


def max_drawdown(values: pd.Series) -> float:
    equity = values.fillna(0).cumsum()
    peak = equity.cummax()
    return float((equity - peak).min())


def summary(df: pd.DataFrame) -> dict[str, float | int | str]:
    r = df[R_COL].astype(float)
    wins = r[r > 0]
    losses = r[r < 0]
    years = sorted(df["year"].dropna().astype(int).unique().tolist())
    yearly = df.groupby("year")[R_COL].sum()
    monthly = df.groupby("month")[R_COL].sum()
    gross_win = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    return {
        "trades": int(len(df)),
        "net_r": float(r.sum()),
        "avg_r_per_trade": float(r.mean()),
        "avg_r_per_year": float(r.sum() / max(1, len(years))),
        "win_rate": float((r > 0).mean()),
        "profit_factor": float(gross_win / gross_loss) if gross_loss else np.inf,
        "max_drawdown_r": max_drawdown(r),
        "positive_years": int((yearly > 0).sum()),
        "negative_years": int((yearly <= 0).sum()),
        "positive_months": int((monthly > 0).sum()),
        "negative_months": int((monthly <= 0).sum()),
        "worst_year_r": float(yearly.min()),
        "best_year_r": float(yearly.max()),
        "worst_month_r": float(monthly.min()),
        "best_month_r": float(monthly.max()),
        "start": str(pd.to_datetime(df["entry_timestamp"], utc=True).min()),
        "end": str(pd.to_datetime(df["entry_timestamp"], utc=True).max()),
    }


def make_yearly(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, g in df.groupby("year"):
        s = summary(g)
        s["year"] = int(year)
        rows.append(s)
    return pd.DataFrame(rows)


def make_monthly(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, g in df.groupby("month"):
        s = summary(g)
        s["month"] = month
        rows.append(s)
    return pd.DataFrame(rows)


def cost_stress(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cost in [0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20]:
        x = df.copy()
        x[R_COL] = x[R_COL].astype(float) - cost
        s = summary(x)
        s["extra_cost_r_per_trade"] = cost
        rows.append(s)
    return pd.DataFrame(rows)


def monte_carlo(df: pd.DataFrame, n: int = 5000) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    r = df[R_COL].astype(float).to_numpy()
    rows = []
    for i in range(n):
        perm = rng.permutation(r)
        eq = np.cumsum(perm)
        dd = np.min(eq - np.maximum.accumulate(eq))
        rows.append({"run": i, "net_r": float(eq[-1]), "max_drawdown_r": float(dd)})
    paths = pd.DataFrame(rows)
    q = paths["max_drawdown_r"].quantile([0.01, 0.05, 0.5]).to_dict()
    out = pd.DataFrame(
        [
            {
                "runs": n,
                "net_r": float(r.sum()),
                "dd_p01": float(q[0.01]),
                "dd_p05": float(q[0.05]),
                "dd_median": float(q[0.5]),
                "prob_dd_worse_15r": float((paths["max_drawdown_r"] <= -15).mean()),
                "prob_dd_worse_20r": float((paths["max_drawdown_r"] <= -20).mean()),
            }
        ]
    )
    return paths, out


def bootstrap(df: pd.DataFrame, n: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(SEED + 1)
    r = df[R_COL].astype(float).to_numpy()
    years = max(1, df["year"].nunique())
    rows = []
    for i in range(n):
        sample = rng.choice(r, size=len(r), replace=True)
        wins = sample[sample > 0].sum()
        losses = abs(sample[sample < 0].sum())
        eq = np.cumsum(sample)
        dd = np.min(eq - np.maximum.accumulate(eq))
        rows.append(
            {
                "run": i,
                "net_r": float(sample.sum()),
                "avg_r_per_year": float(sample.sum() / years),
                "win_rate": float((sample > 0).mean()),
                "profit_factor": float(wins / losses) if losses else np.inf,
                "max_drawdown_r": float(dd),
            }
        )
    paths = pd.DataFrame(rows)
    return pd.DataFrame(
        [
            {
                "runs": n,
                "net_r_p01": float(paths["net_r"].quantile(0.01)),
                "net_r_p05": float(paths["net_r"].quantile(0.05)),
                "net_r_median": float(paths["net_r"].median()),
                "avg_r_year_p05": float(paths["avg_r_per_year"].quantile(0.05)),
                "wr_p05": float(paths["win_rate"].quantile(0.05)),
                "pf_p05": float(paths["profit_factor"].quantile(0.05)),
                "prob_negative_net": float((paths["net_r"] <= 0).mean()),
                "dd_p05": float(paths["max_drawdown_r"].quantile(0.05)),
            }
        ]
    )


def write_report(s: dict, mc: pd.DataFrame, boot: pd.DataFrame) -> None:
    report = f"""# XAU-SDR-001 Regenerated Report

Source ledger: `{TRADES}`

## Base

- Trades: `{s['trades']}`
- Net R: `{s['net_r']:.2f}R`
- Average R/year: `{s['avg_r_per_year']:.2f}R`
- Win rate: `{s['win_rate']:.2%}`
- Profit factor: `{s['profit_factor']:.2f}`
- Max drawdown: `{s['max_drawdown_r']:.2f}R`
- Positive years: `{s['positive_years']}`
- Negative years: `{s['negative_years']}`

## Monte Carlo

- Median DD: `{mc.loc[0, 'dd_median']:.2f}R`
- 5% DD: `{mc.loc[0, 'dd_p05']:.2f}R`
- 1% DD: `{mc.loc[0, 'dd_p01']:.2f}R`
- Probability DD worse than 20R: `{mc.loc[0, 'prob_dd_worse_20r']:.2%}`

## Bootstrap

- 5% net: `{boot.loc[0, 'net_r_p05']:.2f}R`
- 5% average/year: `{boot.loc[0, 'avg_r_year_p05']:.2f}R`
- Probability net <= 0: `{boot.loc[0, 'prob_negative_net']:.2%}`
"""
    (DOCS / "XAU_SDR_001_REGENERATED_REPORT.md").write_text(report, encoding="utf-8")


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    STRESS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(TRADES)
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    if "year" not in df.columns:
        df["year"] = df["entry_timestamp"].dt.year
    if "month" not in df.columns:
        df["month"] = df["entry_timestamp"].dt.strftime("%Y-%m")

    s = summary(df)
    pd.DataFrame([s]).to_csv(BASE / "xau_sdr_001_summary_regenerated.csv", index=False)
    make_yearly(df).to_csv(BASE / "xau_sdr_001_yearly_regenerated.csv", index=False)
    make_monthly(df).to_csv(BASE / "xau_sdr_001_monthly_regenerated.csv", index=False)
    cost_stress(df).to_csv(STRESS / "xau_sdr_001_cost_stress_regenerated.csv", index=False)
    mc_paths, mc_summary = monte_carlo(df)
    mc_paths.to_csv(STRESS / "xau_sdr_001_monte_carlo_paths_regenerated.csv", index=False)
    mc_summary.to_csv(STRESS / "xau_sdr_001_monte_carlo_summary_regenerated.csv", index=False)
    boot_summary = bootstrap(df)
    boot_summary.to_csv(STRESS / "xau_sdr_001_bootstrap_summary_regenerated.csv", index=False)
    write_report(s, mc_summary, boot_summary)
    print(f"Wrote XAU-SDR-001 regenerated report under {ROOT}")


if __name__ == "__main__":
    main()
