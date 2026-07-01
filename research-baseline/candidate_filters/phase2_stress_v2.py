"""Phase 2 · 15-point stress battery on V2 = fib_diff / D1_ATR14 >= 0.30 filter.

Same tests as phase2_stress_fib_diff.py but with V2 filter definition.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)
RUN_ID = "b6604240-14f4-464f-86b4-0d0e32755838"
M5_PATH = Path("/tmp/oanda_xau_m5.parquet")


def load_trades_with_atr() -> pd.DataFrame:
    eng = create_engine(DB_URL)
    q = text("""
        select trade_id::text as trade_id, entry_timestamp, direction, leg, net_r,
               (raw_features->>'fib_diff')::numeric as fib_diff,
               (raw_features->>'pnl_usd')::numeric as pnl_usd,
               (raw_features->>'ny_hr')::int as ny_hr,
               entry_price
        from bt_trades where run_id = :run_id and net_r is not null
        order by entry_timestamp
    """)
    with eng.connect() as c:
        tr = pd.read_sql(q, c, params={"run_id": RUN_ID})
    tr["entry_timestamp"] = pd.to_datetime(tr["entry_timestamp"], utc=True)
    tr["year"] = tr["entry_timestamp"].dt.year
    for col in ["fib_diff", "pnl_usd", "entry_price", "net_r"]:
        tr[col] = tr[col].astype(float)
    tr["pnl_usd"] = tr["pnl_usd"].fillna(0.0)

    # Load D1 ATR14 causally
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    d1 = (m5.set_index("timestamp")
              .resample("1D", label="left", closed="left")
              .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
              .dropna().reset_index())
    if d1["timestamp"].dt.tz is None:
        d1["timestamp"] = d1["timestamp"].dt.tz_localize("UTC")
    d1["prev_close"] = d1["close"].shift(1)
    trng = pd.concat([
        (d1["high"] - d1["low"]),
        (d1["high"] - d1["prev_close"]).abs(),
        (d1["low"] - d1["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    d1["atr14"] = trng.rolling(14, min_periods=14).mean()
    d1 = d1.dropna(subset=["atr14"]).reset_index(drop=True)

    d1_ts = d1["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    d1_atr = d1["atr14"].to_numpy()
    day_delta = pd.Timedelta("1D").to_timedelta64()
    atrs = []
    for _, tr_row in tr.iterrows():
        ts_np = tr_row["entry_timestamp"].tz_convert("UTC").tz_localize(None).to_datetime64()
        mask = d1_ts <= ts_np - day_delta
        atrs.append(d1_atr[mask.sum() - 1] if mask.any() else np.nan)
    tr["d1_atr14"] = atrs
    tr["fib_over_atr"] = tr["fib_diff"] / tr["d1_atr14"]
    return tr


def stats(name, tr):
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
    return {"name": name, "n": n, "wr": wr, "sum_r": sum_r, "sum_usd": sum_usd, "pf": pf}


def prow(s):
    if s["n"] == 0:
        print(f"  {s['name']:<40s}   n=0"); return
    print(f"  {s['name']:<40s}   n={s['n']:>6,d}  wr={s['wr']:>5.2f}%  "
          f"$={s['sum_usd']:>+12,.0f}  R={s['sum_r']:>+8.1f}  PF={s['pf']:>5.3f}")


def test_1_yearly(base, filt):
    print("\n=== TEST 1 · Year-by-year ===")
    years = sorted(base["year"].unique())
    b_pos = f_pos = 0
    for y in years:
        b = base[base["year"] == y]
        f = filt[filt["year"] == y]
        bu = float(b["pnl_usd"].sum()); fu = float(f["pnl_usd"].sum())
        bwr = 100 * (b["net_r"] > 0).sum() / max(1, len(b))
        fwr = 100 * (f["net_r"] > 0).sum() / max(1, len(f))
        if bu > 0: b_pos += 1
        if fu > 0: f_pos += 1
        print(f"  {y:6d}  base_$={bu:>+10,.0f}  filt_$={fu:>+10,.0f}  base_wr={bwr:.2f}  filt_wr={fwr:.2f}")
    print(f"  positive years: base {b_pos}/{len(years)}  filt {f_pos}/{len(years)}")


def test_2_is_oos(base, filt):
    print("\n=== TEST 2 · IS/OOS split ===")
    for nm, df in [("BASE", base), ("FILT", filt)]:
        prow({**stats(f"{nm}·IS", df[df.year <= 2018]), "name": f"{nm} · IS"})
        prow({**stats(f"{nm}·OOS", df[df.year >= 2019]), "name": f"{nm} · OOS"})


def test_3_bootstrap(base, filt, n_iter=5000, seed=42):
    print(f"\n=== TEST 3 · Bootstrap P(net<0) {n_iter} iters ===")
    rng = np.random.default_rng(seed)
    for nm, df in [("BASE", base), ("FILT", filt)]:
        p = df["pnl_usd"].to_numpy(); n = len(p)
        s = np.empty(n_iter)
        for i in range(n_iter):
            s[i] = p[rng.integers(0, n, n)].sum()
        ci = np.percentile(s, [2.5, 97.5])
        print(f"  {nm}  P(net<0)={100*(s<0).mean():.3f}%  mean=${s.mean():+.0f}  "
              f"CI=[${ci[0]:+.0f}, ${ci[1]:+.0f}]")


def test_4_permutation(base, filt, n_iter=1000, seed=42):
    print(f"\n=== TEST 4 · Permutation MC {n_iter} iters ===")
    rng = np.random.default_rng(seed)
    for nm, df in [("BASE", base), ("FILT", filt)]:
        abs_p = df["pnl_usd"].abs().to_numpy()
        obs = float(df["pnl_usd"].sum())
        s = np.empty(n_iter)
        for i in range(n_iter):
            s[i] = (rng.choice([-1, 1], len(abs_p)) * abs_p).sum()
        print(f"  {nm}  obs=${obs:+.0f}  perm_mean=${s.mean():+.0f}  "
              f"perm_std=${s.std():.0f}  p={100*(s>=obs).mean():.3f}%")


def test_5_cost(base, filt):
    print("\n=== TEST 5 · Cost stress ===")
    for nm, df in [("BASE", base), ("FILT", filt)]:
        for extra in [0, 0.3, 1, 5, 10]:
            adj = df["pnl_usd"].to_numpy() - extra
            print(f"  {nm}  +${extra:>5.2f}/trade  sum=${adj.sum():+,.0f}")


def test_6_sample(base, filt):
    print("\n=== TEST 6 · Sample size per year ===")
    for y in sorted(base["year"].unique()):
        b = len(base[base["year"] == y]); f = len(filt[filt["year"] == y])
        warn = " ⚠LOW" if f < 30 else ""
        print(f"  {y}  base_n={b:>6,d}  filt_n={f:>6,d}  ratio={100*f/b:.1f}%{warn}")


def test_7_leg(base, filt):
    print("\n=== TEST 7 · Direction split ===")
    for nm, df in [("BASE", base), ("FILT", filt)]:
        for leg in sorted(df["leg"].dropna().unique()):
            prow({**stats(f"{nm}·{leg}", df[df["leg"] == leg]), "name": f"{nm} · {leg}"})


def test_9_threshold_sweep(base):
    print("\n=== TEST 9 · Threshold sweep (fib_over_atr) ===")
    prow(stats("baseline", base))
    for k in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.75, 1.00]:
        f = base[base["fib_over_atr"] >= k]
        prow({**stats(f"fib/atr >= {k:.2f}", f), "name": f"fib/atr >= {k:.2f}"})


def test_10_flip(base, filt):
    print("\n=== TEST 10 · FLIP test ===")
    for nm, df in [("BASE", base), ("FILT", filt)]:
        fl = df.copy(); fl["pnl_usd"] = -fl["pnl_usd"]; fl["net_r"] = -fl["net_r"]
        prow({**stats(f"{nm}·flipped", fl), "name": f"{nm} · flipped"})


def test_11_sharpe(base, filt):
    print("\n=== TEST 11 · Sharpe/MAR ===")
    for nm, df in [("BASE", base), ("FILT", filt)]:
        r = df["net_r"].to_numpy()
        if len(r) < 2: continue
        sharpe = float(r.mean() / r.std() * np.sqrt(252))
        eq = np.cumsum(r); dd = eq - np.maximum.accumulate(eq)
        mx = float(dd.min()); tot = float(r.sum())
        mar = -tot / mx if mx < 0 else float("inf")
        print(f"  {nm}  R={tot:+.1f}  sharpe={sharpe:.3f}  max_dd_r={mx:+.2f}  MAR={mar:.3f}")


def test_12_streak(base, filt):
    print("\n=== TEST 12 · Max consec losers ===")
    for nm, df in [("BASE", base), ("FILT", filt)]:
        s = df.sort_values("entry_timestamp")["net_r"].to_numpy()
        cur = mx = 0
        for x in s:
            if x <= 0: cur += 1; mx = max(mx, cur)
            else: cur = 0
        print(f"  {nm}  max={mx}")


def test_13_ablation(base, k=0.30):
    print("\n=== TEST 13 · Ablation — dropped bucket composition ===")
    drop = base[base["fib_over_atr"] < k]
    dw = int((drop["net_r"] > 0).sum()); dl = int((drop["net_r"] <= 0).sum())
    wu = float(drop.loc[drop["net_r"] > 0, "pnl_usd"].sum())
    lu = float(-drop.loc[drop["net_r"] <= 0, "pnl_usd"].sum())
    print(f"  dropped n={len(drop):,}  winners={dw:,} (${wu:+,.0f})  losers={dl:,} (${-lu:+,.0f})")
    print(f"  ratio losers:winners = {dl/max(1,dw):.2f}:1")
    print(f"  net dropped ${wu - lu:+,.0f}")


def test_14_hour(base, filt):
    print("\n=== TEST 14 · Hour split ===")
    for h in range(24):
        b = base[base["ny_hr"] == h]; f = filt[filt["ny_hr"] == h]
        bn = len(b); fn = len(f)
        bwr = 100 * (b["net_r"] > 0).sum() / bn if bn else 0
        fwr = 100 * (f["net_r"] > 0).sum() / fn if fn else 0
        print(f"  hr {h:>2d}  base_wr={bwr:.2f} filt_wr={fwr:.2f} boost={fwr-bwr:+.2f}  base_n={bn:,} filt_n={fn:,}")


def main():
    print("[LOAD]...")
    base = load_trades_with_atr()
    valid = base[base["d1_atr14"].notna()].reset_index(drop=True)
    print(f"  {len(base):,} trades, {len(valid):,} valid with ATR14")

    K = 0.30
    filt = valid[valid["fib_over_atr"] >= K].reset_index(drop=True)
    print(f"[FILTER] fib_over_atr >= {K}: {len(filt):,} ({100*len(filt)/len(valid):.1f}% of valid)")

    print("\n=== HEADLINE ===")
    prow(stats("BASELINE (all trades)", base))
    prow(stats("BASELINE (valid ATR subset)", valid))
    prow(stats(f"FILT fib/atr >= {K}", filt))

    test_1_yearly(valid, filt)
    test_2_is_oos(valid, filt)
    test_3_bootstrap(valid, filt)
    test_4_permutation(valid, filt)
    test_5_cost(valid, filt)
    test_6_sample(valid, filt)
    test_7_leg(valid, filt)
    test_9_threshold_sweep(valid)
    test_10_flip(valid, filt)
    test_11_sharpe(valid, filt)
    test_12_streak(valid, filt)
    test_13_ablation(valid, K)
    test_14_hour(valid, filt)


if __name__ == "__main__":
    main()
