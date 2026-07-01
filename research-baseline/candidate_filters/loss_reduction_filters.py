"""Loss-reduction filters — POST-HOC RESEARCH ONLY. Zero production code changes.

Approach:
1. Load closed trades from bt_trades run `b6604240` (Model B A+D combined, 22yr, +$851k).
2. Load raw OANDA M5 parquet used by that BT.
3. For each trade, look up its entry_timestamp. Compute filter value from bars
   STRICTLY BEFORE that timestamp (causal).
4. Apply filter accept/reject. If reject → drop the trade from the ledger.
5. Recompute headline: trades, WR, net$, PF, worst-losers etc.
6. Print vs baseline. No strategy re-BT — this is pure ledger surgery.

Filters:
  A. Momentum EMA slope (M15, len=5 default). Long: slope > 0. Short: slope < 0.
  B. ATR compression skip. Skip if current-day ATR14 < ratio × 20-day median D1 ATR.
  C. H1 confluence. Long: last-closed H1 close > open. Short: close < open.

Zero look-ahead: all filter inputs are bars whose timestamp < entry_timestamp.

Run:
  python3 research-baseline/candidate_filters/loss_reduction_filters.py \
    --run-id b6604240-14f4-464f-86b4-0d0e32755838 \
    --m5-parquet /tmp/oanda_xau_m5.parquet
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)


# ────────────────────────── data loaders ──────────────────────────


def load_trades(run_id: str) -> pd.DataFrame:
    eng = create_engine(DB_URL)
    q = text("""
        select trade_id::text, entry_timestamp, direction, leg,
               net_r, gross_r,
               (raw_features->>'pnl_usd')::numeric as pnl_usd,
               exit_reason
        from bt_trades
        where run_id = :run_id
          and net_r is not null
        order by entry_timestamp
    """)
    with eng.connect() as c:
        df = pd.read_sql(q, c, params={"run_id": run_id})
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["net_r"] = df["net_r"].astype(float)
    df["pnl_usd"] = df["pnl_usd"].astype(float).fillna(0.0)
    return df


def load_m5(path: Path) -> pd.DataFrame:
    m5 = pd.read_parquet(path)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return m5


def resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    return (idx.resample("15min", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min",
                      "close": "last", "volume": "sum"})
                .dropna().reset_index())


def resample_h1(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    return (idx.resample("1h", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min",
                      "close": "last", "volume": "sum"})
                .dropna().reset_index())


def resample_h4(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    return (idx.resample("4h", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min",
                      "close": "last", "volume": "sum"})
                .dropna().reset_index())


def resample_d1(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    return (idx.resample("1D", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min",
                      "close": "last", "volume": "sum"})
                .dropna().reset_index())


# ────────────────────────── filter helpers ──────────────────────────


def build_m15_slope(m15: pd.DataFrame, ema_len: int) -> pd.Series:
    """Slope proxy: close[i] - close[i-ema_len]. Indexed by timestamp.
    Value at bar i uses closes at i-ema_len and i BOTH already closed.
    """
    s = m15.set_index("timestamp")["close"]
    slope = s - s.shift(ema_len)
    return slope


def build_d1_atr14(d1: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """Return d1 with columns [timestamp, atr14, median20]. Both causal (uses
    only rows <= own row). median20 is rolling median of PRIOR 20 atr14 values.
    """
    d = d1.copy().sort_values("timestamp").reset_index(drop=True)
    d["prev_close"] = d["close"].shift(1)
    tr = pd.concat([
        (d["high"] - d["low"]),
        (d["high"] - d["prev_close"]).abs(),
        (d["low"]  - d["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(atr_period, min_periods=atr_period).mean()
    # Median of PRIOR 20 atr14 values (exclude current).
    d["median20"] = d["atr14"].shift(1).rolling(20, min_periods=20).median()
    return d[["timestamp", "atr14", "median20"]]


def find_prior_bar(df: pd.DataFrame, ts_col: str, at: pd.Timestamp) -> pd.Series | None:
    """Return the last row where `df[ts_col] < at`, or None."""
    mask = df[ts_col] < at
    if not mask.any():
        return None
    return df[mask].iloc[-1]


# ────────────────────────── filters ──────────────────────────


def filter_momentum(trades: pd.DataFrame, m15: pd.DataFrame, ema_len: int) -> pd.Series:
    """Return bool mask: True = KEEP trade, False = filtered out."""
    slope = build_m15_slope(m15, ema_len)
    keeps = []
    m15_ts = m15["timestamp"].values
    for _, tr in trades.iterrows():
        ts = tr["entry_timestamp"]
        # Latest closed M15 bar STRICTLY BEFORE entry.
        # entry_timestamp is on the M15 boundary; strategy signaled at bar[k-1].close;
        # entry at bar[k].open. Prior closed bar = k-1.
        prior_mask = m15_ts < ts.to_datetime64()
        if not prior_mask.any():
            keeps.append(True)  # no data — pass
            continue
        # Index of last prior bar
        idx = prior_mask.sum() - 1
        ts_prior = m15.iloc[idx]["timestamp"]
        if ts_prior not in slope.index:
            keeps.append(True); continue
        sl_val = slope.loc[ts_prior]
        if pd.isna(sl_val):
            keeps.append(True); continue
        direction = tr["direction"]
        if direction == "long":
            keeps.append(sl_val > 0)
        else:
            keeps.append(sl_val < 0)
    return pd.Series(keeps, index=trades.index)


def filter_atr_compression(trades: pd.DataFrame, d1: pd.DataFrame, ratio: float) -> pd.Series:
    """True = KEEP. Reject if current-day atr14 (from LAST FULLY-CLOSED D1) < ratio × median20.

    Causality: D1 bar labeled `D` covers `D` through `D + 24h`. It closes at
    `D + 24h`. At entry_ts, use only bars where label + 24h <= entry_ts,
    i.e. `bar_label <= entry_ts - 24h`.
    """
    atr = build_d1_atr14(d1)
    atr = atr.dropna()
    if atr.empty:
        return pd.Series([True] * len(trades), index=trades.index)
    atr_ts = atr["timestamp"].values
    d1_close_delta = pd.Timedelta("1D").to_timedelta64()
    keeps = []
    for _, tr in trades.iterrows():
        ts = tr["entry_timestamp"].to_datetime64()
        # Fully-closed daily bar: label + 24h <= entry_ts
        prior_mask = atr_ts <= ts - d1_close_delta
        if not prior_mask.any():
            keeps.append(True); continue
        idx = prior_mask.sum() - 1
        row = atr.iloc[idx]
        if pd.isna(row["atr14"]) or pd.isna(row["median20"]) or row["median20"] <= 0:
            keeps.append(True); continue
        compressed = row["atr14"] < ratio * row["median20"]
        keeps.append(not compressed)  # REJECT if compressed
    return pd.Series(keeps, index=trades.index)


def filter_htf_confluence(trades: pd.DataFrame, htf: pd.DataFrame, tf_delta: pd.Timedelta,
                            label: str = "H1") -> pd.Series:
    """True = KEEP. Long: last FULLY-CLOSED HTF body bullish. Short: bearish.

    Causality: HTF bar labeled `t` covers `t` through `t + tf_delta`. It's
    fully closed at `t + tf_delta`. At entry_ts, use only bars where
    `t + tf_delta <= entry_ts`, i.e. `t <= entry_ts - tf_delta`.
    """
    keeps = []
    htf_ts = htf["timestamp"].values
    delta = tf_delta.to_timedelta64()
    for _, tr in trades.iterrows():
        ts = tr["entry_timestamp"].to_datetime64()
        prior_mask = htf_ts <= ts - delta
        if not prior_mask.any():
            keeps.append(True); continue
        idx = prior_mask.sum() - 1
        row = htf.iloc[idx]
        if tr["direction"] == "long":
            keeps.append(float(row["close"]) > float(row["open"]))
        else:
            keeps.append(float(row["close"]) < float(row["open"]))
    return pd.Series(keeps, index=trades.index)


def filter_h1_confluence(trades: pd.DataFrame, h1: pd.DataFrame) -> pd.Series:
    return filter_htf_confluence(trades, h1, pd.Timedelta("1h"), "H1")


def filter_h4_confluence(trades: pd.DataFrame, h4: pd.DataFrame) -> pd.Series:
    return filter_htf_confluence(trades, h4, pd.Timedelta("4h"), "H4")


# ────────────────────────── analysis ──────────────────────────


def headline(name: str, trades: pd.DataFrame, ref_trades: int, ref_usd: float) -> dict:
    n = len(trades)
    win = int((trades["net_r"] > 0).sum())
    loss = int((trades["net_r"] <= 0).sum())
    sum_r = float(trades["net_r"].sum())
    sum_usd = float(trades["pnl_usd"].sum())
    wr = 100.0 * win / n if n else 0
    profit = float(trades.loc[trades["net_r"] > 0, "pnl_usd"].sum())
    loss_usd = float(-trades.loc[trades["net_r"] <= 0, "pnl_usd"].sum())
    pf = profit / loss_usd if loss_usd > 0 else float("inf")
    max_dd_r = _max_drawdown_r(trades)
    print(f"\n=== {name} ===")
    print(f"  trades:   {n:>7,d}  ({n - ref_trades:+,d} vs baseline)")
    print(f"  win/loss: {win:>7,d} / {loss:,d}  WR {wr:.2f}%")
    print(f"  sum_r:    {sum_r:+.1f}R")
    print(f"  net_usd:  ${sum_usd:+,.2f}  ({sum_usd - ref_usd:+,.2f} vs baseline, "
          f"{100 * (sum_usd - ref_usd) / abs(ref_usd) if ref_usd else 0:+.1f}%)")
    print(f"  PF:       {pf:.3f}")
    print(f"  max_dd_r: {max_dd_r:+.2f}R")
    return {"name": name, "n": n, "wr": wr, "sum_r": sum_r, "net_usd": sum_usd, "pf": pf}


def _max_drawdown_r(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    eq = trades["net_r"].cumsum()
    peak = eq.cummax()
    dd = eq - peak
    return float(dd.min())


# ────────────────────────── main ──────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="b6604240-14f4-464f-86b4-0d0e32755838")
    p.add_argument("--m5-parquet", default="/tmp/oanda_xau_m5.parquet")
    p.add_argument("--ema-len", type=int, default=5)
    p.add_argument("--atr-ratio", type=float, default=0.5)
    args = p.parse_args()

    print(f"[LOAD] trades from run {args.run_id}...")
    trades = load_trades(args.run_id)
    print(f"  loaded {len(trades):,} closed trades")
    print(f"  entry_ts range: {trades['entry_timestamp'].min()} → {trades['entry_timestamp'].max()}")

    m5_path = Path(args.m5_parquet)
    if not m5_path.exists():
        print(f"[FATAL] M5 parquet not found: {m5_path}", file=sys.stderr)
        sys.exit(1)
    print(f"[LOAD] M5 parquet {m5_path}...")
    m5 = load_m5(m5_path)
    print(f"  loaded {len(m5):,} M5 bars")
    print(f"  range: {m5['timestamp'].min()} → {m5['timestamp'].max()}")

    print("[LOAD] resampling M15 / H1 / H4 / D1...")
    m15 = resample_m15(m5)
    h1 = resample_h1(m5)
    h4 = resample_h4(m5)
    d1 = resample_d1(m5)
    print(f"  M15={len(m15):,}  H1={len(h1):,}  H4={len(h4):,}  D1={len(d1):,}")

    # Filter trades to those whose entry_ts falls within M15 range (parquet may not
    # cover the earliest BT bars if it's a shortened OANDA dump).
    ts_min = m15["timestamp"].min()
    ts_max = m15["timestamp"].max()
    in_range = (trades["entry_timestamp"] >= ts_min) & (trades["entry_timestamp"] <= ts_max)
    trades = trades[in_range].reset_index(drop=True)
    print(f"[COVERAGE] {len(trades):,} trades fall within parquet coverage")

    # Baseline headline (no filter).
    ref_n = len(trades)
    ref_usd = float(trades["pnl_usd"].sum())
    headline("BASELINE (no filter)", trades, ref_n, ref_usd)

    # Filter A
    keep_A = filter_momentum(trades, m15, args.ema_len)
    headline(f"A · momentum slope > 0 (ema{args.ema_len})",
             trades[keep_A].reset_index(drop=True), ref_n, ref_usd)

    # Filter B
    keep_B = filter_atr_compression(trades, d1, args.atr_ratio)
    headline(f"B · ATR compression skip (ratio={args.atr_ratio})",
             trades[keep_B].reset_index(drop=True), ref_n, ref_usd)

    # Filter C — H1 confluence (last fully-closed H1)
    keep_C = filter_h1_confluence(trades, h1)
    headline("C · H1 confluence (last fully-closed H1 body aligns)",
             trades[keep_C].reset_index(drop=True), ref_n, ref_usd)

    # Filter D — H4 confluence (last fully-closed H4)
    keep_D = filter_h4_confluence(trades, h4)
    headline("D · H4 confluence (last fully-closed H4 body aligns)",
             trades[keep_D].reset_index(drop=True), ref_n, ref_usd)

    # Combos of most-interesting filters
    headline("C+D (both H1 and H4 aligned)",
             trades[keep_C & keep_D].reset_index(drop=True), ref_n, ref_usd)
    headline("C or D (either H1 or H4 aligned)",
             trades[keep_C | keep_D].reset_index(drop=True), ref_n, ref_usd)
    headline("A+B+C+D", trades[keep_A & keep_B & keep_C & keep_D].reset_index(drop=True), ref_n, ref_usd)

    # Per-filter loss trim visibility
    print("\n=== Per-filter effect ===")
    for name, keep in [("A", keep_A), ("B", keep_B), ("C", keep_C), ("D", keep_D)]:
        dropped = trades[~keep]
        d_win = (dropped["net_r"] > 0).sum()
        d_loss = (dropped["net_r"] <= 0).sum()
        d_usd = float(dropped["pnl_usd"].sum())
        print(f"  {name}: dropped {len(dropped):,} trades  "
              f"(dropped-winners {d_win}  dropped-losers {d_loss}  "
              f"dropped-$ sum ${d_usd:+,.2f})")


if __name__ == "__main__":
    main()
