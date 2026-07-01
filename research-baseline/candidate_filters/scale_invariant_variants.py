"""Scale-invariant variants of the fib_diff noise-cutoff filter.

Post-hoc on baseline trade ledger. Same trade set, different filter functions.

Variants:
  V1 · fib_diff / entry_price (as pct) — invariant to price scale
  V2 · fib_diff / D1_ATR14 (vol-normalized)
  V3 · fib_diff > yearly_20th_percentile (rank-based within-year)

All values MUST be known at signal-decision time (no future peek). This
script uses raw_features already recorded at trade-open time (fib_diff,
entry_price, fib_100 which = L or H) + independently computed D1 ATR14
from raw M5 using bars STRICTLY before entry_ts.

For each variant, sweep the threshold and report headline stats.
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


def load_trades() -> pd.DataFrame:
    eng = create_engine(DB_URL)
    q = text("""
        select trade_id::text as trade_id, entry_timestamp, direction, leg, net_r,
               (raw_features->>'fib_diff')::numeric as fib_diff,
               (raw_features->>'pnl_usd')::numeric as pnl_usd,
               entry_price
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
    df["entry_price"] = df["entry_price"].astype(float)
    return df


def load_d1_atr14() -> pd.DataFrame:
    """Build D1 ATR14 series from raw M5. All values causal — atr14 at day D
    uses D's OHLC + previous close (already closed at D+1)."""
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    idx = m5.set_index("timestamp")
    d1 = (idx.resample("1D", label="left", closed="left")
              .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
              .dropna().reset_index())
    if d1["timestamp"].dt.tz is None:
        d1["timestamp"] = d1["timestamp"].dt.tz_localize("UTC")
    d1["prev_close"] = d1["close"].shift(1)
    tr = pd.concat([
        (d1["high"] - d1["low"]),
        (d1["high"] - d1["prev_close"]).abs(),
        (d1["low"] - d1["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    d1["atr14"] = tr.rolling(14, min_periods=14).mean()
    return d1[["timestamp", "atr14"]].dropna()


def attach_atr(trades: pd.DataFrame, d1_atr: pd.DataFrame) -> pd.DataFrame:
    """Attach the LAST fully-closed D1 ATR14 for each trade.
    Fully-closed = day D whose label + 24h <= entry_ts.
    """
    # Strip tz from d1_ts so numpy comparison works vs also-tz-stripped entry_ts.
    d1_ts = d1_atr["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    d1_atr_vals = d1_atr["atr14"].to_numpy()
    delta_1d = pd.Timedelta("1D").to_timedelta64()
    atrs = []
    for _, tr in trades.iterrows():
        ts = tr["entry_timestamp"].tz_convert("UTC").tz_localize(None).to_datetime64()
        # bar_label + 24h <= entry_ts
        mask = d1_ts <= ts - delta_1d
        if not mask.any():
            atrs.append(np.nan)
        else:
            atrs.append(d1_atr_vals[mask.sum() - 1])
    trades = trades.copy()
    trades["d1_atr14"] = atrs
    return trades


def attach_yearly_percentile(trades: pd.DataFrame) -> pd.DataFrame:
    """For each trade, compute its fib_diff percentile RANK within the year.

    CAUSAL: uses only trades from the SAME YEAR that happened BEFORE this trade.
    (Simple year-rank would be look-ahead — future trades would inform the rank.)
    """
    trades = trades.copy().sort_values("entry_timestamp").reset_index(drop=True)
    pcts = []
    for i, tr in trades.iterrows():
        y = tr["year"]
        # Prior trades this year
        mask = (trades["year"] == y) & (trades.index < i)
        prior = trades.loc[mask, "fib_diff"]
        if len(prior) < 30:
            # Not enough sample yet — pass (don't filter this early trade)
            pcts.append(np.nan)
        else:
            pcts.append((prior < tr["fib_diff"]).mean() * 100)
    trades["yearly_pct"] = pcts
    return trades


def hdr(name: str, tr: pd.DataFrame, base_n: int, base_usd: float) -> None:
    n = len(tr)
    if n == 0:
        print(f"  {name:<45s}  n=0"); return
    win = int((tr["net_r"] > 0).sum())
    sum_r = float(tr["net_r"].sum())
    sum_usd = float(tr["pnl_usd"].sum())
    wr = 100.0 * win / n
    profit = float(tr.loc[tr["net_r"] > 0, "pnl_usd"].sum())
    loss = float(-tr.loc[tr["net_r"] <= 0, "pnl_usd"].sum())
    pf = profit / loss if loss > 0 else float("inf")
    delta_pct = 100.0 * (sum_usd - base_usd) / abs(base_usd) if base_usd else 0
    print(f"  {name:<45s}  n={n:>6,d}  wr={wr:>5.2f}%  "
          f"$={sum_usd:>+12,.0f}  Δ={delta_pct:>+5.1f}%  PF={pf:>5.3f}")


def main() -> None:
    print("[LOAD] trades...")
    tr = load_trades()
    print(f"  {len(tr):,} trades")

    print("[LOAD] D1 ATR14 from raw M5...")
    d1 = load_d1_atr14()
    print(f"  {len(d1):,} D1 bars with ATR14")

    print("[MERGE] attaching last-closed D1 ATR14 to each trade...")
    tr = attach_atr(tr, d1)
    print(f"  attached (non-NaN: {tr['d1_atr14'].notna().sum():,})")

    print("[MERGE] attaching within-year percentile...")
    tr = attach_yearly_percentile(tr)
    print(f"  attached (non-NaN: {tr['yearly_pct'].notna().sum():,})")

    tr["fib_pct_price"] = tr["fib_diff"] / tr["entry_price"] * 100.0
    tr["fib_over_atr"] = tr["fib_diff"] / tr["d1_atr14"]

    base_n = len(tr)
    base_usd = float(tr["pnl_usd"].sum())

    print("\n=== BASELINE ===")
    hdr("BASELINE (no filter)", tr, base_n, base_usd)

    print("\n=== V1 · fib_diff / entry_price (pct of price) ===")
    for th in [0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00]:
        keep = tr[tr["fib_pct_price"] >= th]
        hdr(f"pct >= {th:.2f}%", keep, base_n, base_usd)

    print("\n=== V2 · fib_diff / D1_ATR14 (vol-normalized) ===")
    valid = tr[tr["d1_atr14"].notna()]
    print(f"  (valid subset: {len(valid):,} of {base_n:,})")
    for th in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00, 1.50]:
        keep = valid[valid["fib_over_atr"] >= th]
        hdr(f"fib/atr >= {th:.2f}", keep, len(valid), float(valid["pnl_usd"].sum()))

    print("\n=== V3 · yearly rank percentile (within-year, causal) ===")
    valid = tr[tr["yearly_pct"].notna()]
    print(f"  (valid subset: {len(valid):,} of {base_n:,})")
    for th in [10, 15, 20, 25, 30, 40, 50]:
        keep = valid[valid["yearly_pct"] >= th]
        hdr(f"yearly_pct >= {th}%", keep, len(valid), float(valid["pnl_usd"].sum()))

    # Era-check: does each variant behave the same across eras?
    print("\n=== ERA CHECK (2006-2012 · 2013-2019 · 2020-2026) ===")
    eras = [(2006, 2012, "pre-2013"), (2013, 2019, "mid"), (2020, 2026, "post-2019")]
    for var_name, col, th in [
        ("V1 fib_pct_price>=0.20%", "fib_pct_price", 0.20),
        ("V2 fib_over_atr>=0.30", "fib_over_atr", 0.30),
        ("V3 yearly_pct>=20%", "yearly_pct", 20),
    ]:
        print(f"\n  {var_name}")
        for y0, y1, label in eras:
            era_tr = tr[(tr["year"] >= y0) & (tr["year"] <= y1) & tr[col].notna()]
            if era_tr.empty:
                continue
            kept = era_tr[era_tr[col] >= th]
            drop_pct = 100.0 * (1 - len(kept) / len(era_tr))
            pf_base = _pf(era_tr)
            pf_filt = _pf(kept)
            print(f"    {label:>10s}  n={len(era_tr):>5,d}  dropped={drop_pct:>5.1f}%  "
                   f"pf_base={pf_base:>5.3f}  pf_filt={pf_filt:>5.3f}  "
                   f"Δpf={pf_filt-pf_base:>+5.3f}")


def _pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return 0.0
    p = float(tr.loc[tr["net_r"] > 0, "pnl_usd"].sum())
    l = float(-tr.loc[tr["net_r"] <= 0, "pnl_usd"].sum())
    return p / l if l > 0 else float("inf")


if __name__ == "__main__":
    main()
