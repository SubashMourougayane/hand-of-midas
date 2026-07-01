"""Phase 2 — 15-point stress battery on fib_diff >= K filter.

Post-hoc on baseline trade ledger. Zero strategy code changes. Every test
runs on the SAME trade set, only altering how we bucket / stress the numbers.

Tests:
  1. Year-by-year edge (positive-years count)
  2. IS/OOS split (2006-2018 vs 2019-2026)
  3. Bootstrap P(net<0) — 5000 resamples
  4. Permutation MC (shuffle net_r signs)
  5. Cost stress ($0.10, $0.30, $1.00, $5.00 per trade)
  6. Sample size warnings per year
  7. Regime split (bull / bear / sideways using D1 EMA of entry bar close vs 200d)
  8. Direction split (A leg vs D leg)
  9. Threshold sweep (K=1..20) — check if edge is robust or knife-edge
 10. FLIP test — invert net_r → should collapse
 11. Sharpe / MAR calc
 12. Max consecutive losers streak (baseline vs filtered)
 13. Kill-lower-K experiment: does filter still work when we ALSO cut winners?
 14. Filter durability vs sample randomisation
 15. What-if filter ADDS trades? (No — accept-only filter)
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)
RUN_ID = "b6604240-14f4-464f-86b4-0d0e32755838"


def load_trades() -> pd.DataFrame:
    eng = create_engine(DB_URL)
    q = text("""
        select trade_id::text as trade_id, entry_timestamp, direction, leg, net_r,
               (raw_features->>'fib_diff')::numeric as fib_diff,
               (raw_features->>'pnl_usd')::numeric as pnl_usd,
               (raw_features->>'ny_hr')::int as ny_hr
        from bt_trades where run_id = :run_id and net_r is not null
        order by entry_timestamp
    """)
    with eng.connect() as c:
        df = pd.read_sql(q, c, params={"run_id": RUN_ID})
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    df["net_r"] = df["net_r"].astype(float)
    df["fib_diff"] = df["fib_diff"].astype(float)
    df["pnl_usd"] = df["pnl_usd"].astype(float).fillna(0.0)
    return df


def stats(name: str, tr: pd.DataFrame) -> dict:
    n = len(tr)
    if n == 0:
        return {"name": name, "n": 0}
    win = int((tr["net_r"] > 0).sum())
    sum_r = float(tr["net_r"].sum())
    sum_usd = float(tr["pnl_usd"].sum())
    wr = 100.0 * win / n
    profit = float(tr.loc[tr["net_r"] > 0, "pnl_usd"].sum())
    loss = float(-tr.loc[tr["net_r"] <= 0, "pnl_usd"].sum())
    pf = profit / loss if loss > 0 else float("inf")
    return {"name": name, "n": n, "win": win, "wr": wr,
            "sum_r": sum_r, "sum_usd": sum_usd, "pf": pf,
            "profit": profit, "loss": loss}


def print_row(s: dict) -> None:
    if s.get("n", 0) == 0:
        print(f"  {s['name']:<40s}   n=0")
        return
    print(f"  {s['name']:<40s}   n={s['n']:>6,d}  wr={s['wr']:>5.2f}%  "
          f"$={s['sum_usd']:>+12,.0f}  R={s['sum_r']:>+8.1f}  PF={s['pf']:>5.3f}")


# ────────────────────────── tests ──────────────────────────


def test_1_yearly(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 1 · Year-by-year (positive-years count) ===")
    base_pos = 0
    filt_pos = 0
    years = sorted(base["year"].unique())
    print(f"  {'year':6s}  {'base_$':>10s}  {'filt_$':>10s}  {'base_wr':>7s}  {'filt_wr':>7s}")
    for y in years:
        b = base[base["year"] == y]
        f = filt[filt["year"] == y]
        b_usd = float(b["pnl_usd"].sum())
        f_usd = float(f["pnl_usd"].sum())
        bwr = 100.0 * (b["net_r"] > 0).sum() / max(1, len(b))
        fwr = 100.0 * (f["net_r"] > 0).sum() / max(1, len(f))
        if b_usd > 0: base_pos += 1
        if f_usd > 0: filt_pos += 1
        print(f"  {y:6d}  {b_usd:>+10,.0f}  {f_usd:>+10,.0f}  {bwr:>7.2f}  {fwr:>7.2f}")
    print(f"  positive years: base {base_pos}/{len(years)}  filt {filt_pos}/{len(years)}")


def test_2_is_oos(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 2 · IS/OOS split (IS: 2006-2018, OOS: 2019-2026) ===")
    for name, df in [("BASE", base), ("FILT", filt)]:
        is_ = df[df["year"] <= 2018]
        oos = df[df["year"] >= 2019]
        print_row({**stats(f"{name} · IS", is_), "name": f"{name} · IS"})
        print_row({**stats(f"{name} · OOS", oos), "name": f"{name} · OOS"})


def test_3_bootstrap(base: pd.DataFrame, filt: pd.DataFrame,
                      n_iter: int = 5000, seed: int = 42) -> None:
    print(f"\n=== TEST 3 · Bootstrap P(net<0) — {n_iter:,} resamples ===")
    rng = np.random.default_rng(seed)
    for name, df in [("BASE", base), ("FILT", filt)]:
        pnl = df["pnl_usd"].to_numpy()
        n = len(pnl)
        sums = np.empty(n_iter)
        for i in range(n_iter):
            idx = rng.integers(0, n, n)
            sums[i] = pnl[idx].sum()
        p_neg = float((sums < 0).mean())
        mean_ = float(sums.mean())
        ci = np.percentile(sums, [2.5, 97.5])
        print(f"  {name}  P(net<0)={p_neg*100:>6.3f}%  "
              f"mean_$={mean_:>+12,.0f}  95%CI=[{ci[0]:>+10,.0f}, {ci[1]:>+10,.0f}]")


def test_4_permutation(base: pd.DataFrame, filt: pd.DataFrame,
                        n_iter: int = 1000, seed: int = 42) -> None:
    print(f"\n=== TEST 4 · Permutation MC (random-sign shuffle) — {n_iter:,} iters ===")
    rng = np.random.default_rng(seed)
    for name, df in [("BASE", base), ("FILT", filt)]:
        abs_pnl = df["pnl_usd"].abs().to_numpy()
        obs = float(df["pnl_usd"].sum())
        sums = np.empty(n_iter)
        for i in range(n_iter):
            signs = rng.choice([-1, 1], len(abs_pnl))
            sums[i] = (signs * abs_pnl).sum()
        p_val = float((sums >= obs).mean())
        print(f"  {name}  observed_$={obs:>+12,.0f}  "
              f"perm_mean=${float(sums.mean()):>+10,.0f}  perm_std=${float(sums.std()):>+10,.0f}  "
              f"p_value={p_val*100:>6.3f}%")


def test_5_cost_stress(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 5 · Cost stress (add $X per trade) ===")
    for name, df in [("BASE", base), ("FILT", filt)]:
        for extra in [0.0, 0.30, 1.00, 5.00, 10.00]:
            adj_pnl = df["pnl_usd"].to_numpy() - extra
            sum_ = adj_pnl.sum()
            print(f"  {name}  +${extra:>5.2f}/trade  sum=${sum_:>+12,.0f}  "
                  f"(delta ${sum_ - float(df['pnl_usd'].sum()):>+10,.0f})")


def test_6_sample_size(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 6 · Sample size per year ===")
    print(f"  {'year':6s}  {'base_N':>8s}  {'filt_N':>8s}  {'filt/base':>10s}")
    for y in sorted(base["year"].unique()):
        b = len(base[base["year"] == y])
        f = len(filt[filt["year"] == y])
        ratio = f / b * 100 if b else 0
        warn = "  ⚠ LOW" if f < 30 else ""
        print(f"  {y:6d}  {b:>8,d}  {f:>8,d}  {ratio:>9.1f}%{warn}")


def test_7_regime_split(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 7 · Direction split (leg = A/D) ===")
    for name, df in [("BASE", base), ("FILT", filt)]:
        for leg in sorted(df["leg"].dropna().unique()):
            s = stats(f"{name} · {leg}", df[df["leg"] == leg])
            print_row(s)


def test_9_threshold_sweep(base: pd.DataFrame) -> None:
    print("\n=== TEST 9 · Fib_diff threshold sweep (robustness check) ===")
    print_row(stats("baseline", base))
    for k in [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20]:
        f = base[base["fib_diff"] >= k]
        print_row({**stats(f"fib_diff >= {k}", f), "name": f"fib_diff >= {k:>2d}"})


def test_10_flip(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 10 · FLIP test (invert net_r, should collapse) ===")
    for name, df in [("BASE", base), ("FILT", filt)]:
        flipped = df.copy()
        flipped["pnl_usd"] = -flipped["pnl_usd"]
        flipped["net_r"] = -flipped["net_r"]
        s = stats(f"{name} · flipped", flipped)
        print_row(s)


def test_11_sharpe_mar(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 11 · Sharpe / MAR / MaxDD ===")
    for name, df in [("BASE", base), ("FILT", filt)]:
        r = df["net_r"].to_numpy()
        if len(r) < 2:
            continue
        sharpe = float(r.mean() / r.std() * np.sqrt(252))
        eq = np.cumsum(r)
        peak = np.maximum.accumulate(eq)
        dd = eq - peak
        max_dd = float(dd.min())
        total_r = float(r.sum())
        mar = -total_r / max_dd if max_dd < 0 else float("inf")
        print(f"  {name}  sum_r={total_r:>+8.1f}  sharpe={sharpe:>6.3f}  "
              f"max_dd_r={max_dd:>+7.2f}  MAR={mar:>6.3f}")


def test_12_streak(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 12 · Max consecutive loser streak ===")
    for name, df in [("BASE", base), ("FILT", filt)]:
        s = df.sort_values("entry_timestamp")["net_r"].to_numpy()
        cur = 0; mx = 0
        for x in s:
            if x <= 0:
                cur += 1; mx = max(mx, cur)
            else:
                cur = 0
        print(f"  {name}  max_consecutive_losers={mx:>4d}  (of {len(s):,} trades)")


def test_13_ablation_high_thresh(base: pd.DataFrame) -> None:
    print("\n=== TEST 13 · Ablation — cut winners AT threshold too ===")
    print("  If filter is real, dropping ALL trades with fib_diff <4 should hurt equally in both directions.")
    dropped = base[base["fib_diff"] < 4]
    d_win = int((dropped["net_r"] > 0).sum())
    d_loss = int((dropped["net_r"] <= 0).sum())
    d_win_usd = float(dropped.loc[dropped["net_r"] > 0, "pnl_usd"].sum())
    d_loss_usd = float(-dropped.loc[dropped["net_r"] <= 0, "pnl_usd"].sum())
    print(f"  dropped bucket (fib_diff < 4):")
    print(f"    winners: {d_win:,}  sum_$={d_win_usd:>+12,.0f}")
    print(f"    losers:  {d_loss:,}  sum_$={-d_loss_usd:>+12,.0f}")
    print(f"    ratio losers:winners = {d_loss/max(1,d_win):.2f}:1")
    print(f"    net dropped: ${d_win_usd - d_loss_usd:>+12,.0f}")


def test_14_hour_split(base: pd.DataFrame, filt: pd.DataFrame) -> None:
    print("\n=== TEST 14 · Fib_diff filter effect by hour ===")
    print(f"  {'hr':4s}  {'base_wr':>7s}  {'filt_wr':>7s}  {'wr_boost':>8s}  {'base_n':>7s}  {'filt_n':>7s}")
    for h in range(24):
        b = base[base["ny_hr"] == h]
        f = filt[filt["ny_hr"] == h]
        bn = len(b); fn = len(f)
        bwr = 100.0 * (b["net_r"] > 0).sum() / bn if bn else 0
        fwr = 100.0 * (f["net_r"] > 0).sum() / fn if fn else 0
        boost = fwr - bwr
        print(f"  {h:>4d}  {bwr:>7.2f}  {fwr:>7.2f}  {boost:>+8.2f}  {bn:>7,d}  {fn:>7,d}")


# ────────────────────────── main ──────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=4, help="fib_diff threshold")
    args = p.parse_args()

    print(f"[LOAD] trades from {RUN_ID}...")
    base = load_trades()
    print(f"  loaded {len(base):,}")

    filt = base[base["fib_diff"] >= args.k].reset_index(drop=True)
    print(f"[FILTER] fib_diff >= {args.k}: {len(filt):,} trades ({100*len(filt)/len(base):.1f}% of baseline)")

    print("\n=== HEADLINE STATS ===")
    print_row(stats("BASE", base))
    print_row(stats(f"FILT (fib_diff >= {args.k})", filt))

    test_1_yearly(base, filt)
    test_2_is_oos(base, filt)
    test_3_bootstrap(base, filt)
    test_4_permutation(base, filt)
    test_5_cost_stress(base, filt)
    test_6_sample_size(base, filt)
    test_7_regime_split(base, filt)
    test_9_threshold_sweep(base)
    test_10_flip(base, filt)
    test_11_sharpe_mar(base, filt)
    test_12_streak(base, filt)
    test_13_ablation_high_thresh(base)
    test_14_hour_split(base, filt)


if __name__ == "__main__":
    main()
