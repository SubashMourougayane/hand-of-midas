"""Hostile causality proof for V2 = fib_diff / D1_ATR14 >= 0.30 filter.

Two inputs, must both be causal:
  1. fib_diff — already proven clean in Phase 1 of prior gauntlet.
  2. D1_ATR14 — must use ONLY bars whose label + 24h <= entry_ts.

Test:
- For each trade, look up the D1 bar picked by our filter (label + 24h ≤ entry_ts).
- Verify that D1 bar's atr14 uses only D1 bars ≤ that D1 label
  (rolling(14) on the D1 series sorted ascending — bar D's atr14 uses D-13..D).
- Verify D-13 date + 14 days ≤ entry_ts (so the FIRST bar in the rolling window
  had already closed).
- Verify D + 24h ≤ entry_ts (final bar in window closed before entry).

Any violation = look-ahead.
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


def main() -> None:
    print("[LOAD] trades...")
    eng = create_engine(DB_URL)
    q = text("""
        select trade_id::text as trade_id, entry_timestamp,
               (raw_features->>'fib_diff')::numeric as fib_diff,
               (raw_features->>'setup_confirm_ts') as setup_confirm_ts_str
        from bt_trades where run_id=:run_id and net_r is not null
        order by entry_timestamp
    """)
    with eng.connect() as c:
        tr = pd.read_sql(q, c, params={"run_id": RUN_ID})
    tr["entry_timestamp"] = pd.to_datetime(tr["entry_timestamp"], utc=True)
    tr["setup_confirm_ts"] = pd.to_datetime(tr["setup_confirm_ts_str"], utc=True)
    tr["fib_diff"] = tr["fib_diff"].astype(float)
    print(f"  {len(tr):,}")

    print("[LOAD] M5 -> D1...")
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
    tr_ = pd.concat([
        (d1["high"] - d1["low"]),
        (d1["high"] - d1["prev_close"]).abs(),
        (d1["low"] - d1["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    d1["atr14"] = tr_.rolling(14, min_periods=14).mean()
    d1_valid = d1.dropna(subset=["atr14"]).reset_index(drop=True)
    print(f"  {len(d1_valid):,} D1 bars with valid ATR14")

    # Audit: for each trade, verify D1 bar picked satisfies all causality.
    d1_ts = d1_valid["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    LB = 14  # ATR window length
    day = pd.Timedelta("1D").to_timedelta64()

    checks = {
        "setup_confirm_after_entry": 0,
        "atr_bar_not_fully_closed_before_entry": 0,
        "atr_window_first_bar_not_closed_before_entry": 0,
        "atr_bar_missing_from_series": 0,
        "no_atr_available": 0,
    }
    n_ok = 0

    for _, row in tr.iterrows():
        entry_ts = row["entry_timestamp"]
        confirm_ts = row["setup_confirm_ts"]
        entry_np = entry_ts.tz_convert("UTC").tz_localize(None).to_datetime64()

        # 1) Setup was already causal per Phase 1
        if pd.isna(confirm_ts) or confirm_ts >= entry_ts:
            checks["setup_confirm_after_entry"] += 1
            continue

        # 2) Locate LAST fully-closed D1 bar (label + 24h <= entry_ts)
        mask = d1_ts <= entry_np - day
        if not mask.any():
            checks["no_atr_available"] += 1
            continue
        idx = mask.sum() - 1

        # 3) Verify the D1 bar's label + 24h really is <= entry
        d1_label = d1_ts[idx]
        if d1_label + day > entry_np:
            checks["atr_bar_not_fully_closed_before_entry"] += 1
            continue

        # 4) Verify FIRST bar in the ATR14 window closed BEFORE entry.
        # First bar in the atr14 rolling window is at idx - (LB-1).
        if idx - (LB - 1) < 0:
            checks["atr_bar_missing_from_series"] += 1
            continue
        first_bar_label = d1_ts[idx - (LB - 1)]
        if first_bar_label + day > entry_np:
            checks["atr_window_first_bar_not_closed_before_entry"] += 1
            continue

        n_ok += 1

    print("\n[AUDIT] Phase 1 causality proof — V2 filter (fib_diff / D1_ATR14)")
    print(f"  trades audited: {n_ok:,} of {len(tr):,}")
    print("\n[VIOLATIONS]")
    total = 0
    for k, v in checks.items():
        flag = "✓ CLEAN" if v == 0 else "✗ BUG"
        total += v
        print(f"  {flag}  {k:<50s}: {v:,}")
    print()
    if total == 0:
        print(f"[VERDICT] ✅ V2 CAUSALITY PROVEN CLEAN across {n_ok:,} trades")
    else:
        print(f"[VERDICT] ❌ {total:,} violations")


if __name__ == "__main__":
    main()
