"""Summarize fire_analysis.csv: do partial-bar fires underperform completed-bar?

Reports per-fire-type stats: count, win rate, average R, profit factor, total R.
Then bucket partial fires by minutes-to-close to see if "fired late in the
H1 bar" is materially different from "fired early."

Usage:
    python scripts/analyze_fire_results.py [path-to-csv]
"""
import os
import sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def summarize(df: pd.DataFrame, label: str):
    n = len(df)
    if n == 0:
        print(f"{label}: 0 fires")
        return
    wins = df[df["r_multiple"] > 0]
    losses = df[df["r_multiple"] <= 0]
    win_rate = len(wins) / n
    avg_r = df["r_multiple"].mean()
    total_r = df["r_multiple"].sum()
    sum_win = wins["r_multiple"].sum() if len(wins) else 0.0
    sum_loss = -losses["r_multiple"].sum() if len(losses) else 0.0
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    by_exit = df["exit_reason"].value_counts().to_dict()
    print(f"{label}:")
    print(f"  N={n}  win_rate={win_rate*100:5.1f}%  avg_R={avg_r:+.3f}  total_R={total_r:+.1f}  PF={pf:.2f}")
    print(f"  exits: {by_exit}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "scripts/output/fire_analysis_full.csv")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "scripts/output/fire_analysis.csv")
    print(f"Loading {path}\n")
    df = pd.read_csv(path)
    df["partial_minutes"] = df["partial_minutes"].astype(float)
    df["r_multiple"] = df["r_multiple"].astype(float)

    print(f"Total fires: {len(df)}\n")

    print("=" * 70)
    print("By fire_type")
    print("=" * 70)
    summarize(df[df["fire_type"] == "partial"], "PARTIAL")
    print()
    summarize(df[df["fire_type"] == "completed"], "COMPLETED")
    print()

    # Partial subdivided by minutes-to-close. partial_minutes is negative for partial,
    # ranging from -60 (just-past-open) to 0 (H1 close).
    print("=" * 70)
    print("Partial fires by minutes-into-bar")
    print("=" * 70)
    p = df[df["fire_type"] == "partial"].copy()
    p["min_into_bar"] = 60 + p["partial_minutes"]  # 0 = bar open, 60 = bar close
    buckets = [(0, 15), (15, 30), (30, 45), (45, 60)]
    for lo, hi in buckets:
        sub = p[(p["min_into_bar"] >= lo) & (p["min_into_bar"] < hi)]
        summarize(sub, f"partial [{lo:2d}-{hi:2d} min into bar]")
        print()

    # By direction
    print("=" * 70)
    print("By direction × fire_type")
    print("=" * 70)
    for d in ("long", "short"):
        for ft in ("partial", "completed"):
            sub = df[(df["direction"] == d) & (df["fire_type"] == ft)]
            summarize(sub, f"{d:5s} {ft}")
            print()

    # By year
    print("=" * 70)
    print("Partial vs Completed by year")
    print("=" * 70)
    df["year"] = pd.to_datetime(df["fire_ts"]).dt.year
    by_year = df.groupby(["year", "fire_type"]).agg(
        n=("r_multiple", "size"),
        avg_r=("r_multiple", "mean"),
        total_r=("r_multiple", "sum"),
    ).reset_index()
    print(by_year.to_string(index=False))


if __name__ == "__main__":
    main()
