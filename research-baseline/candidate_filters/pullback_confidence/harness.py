"""Pullback confidence → edge research.

Question: does the QUALITY of the retracement into the fib zone predict which
Fib V2 A/D trades win? Currently the strategy treats every zone-touch equally.

Post-hoc, causal, ZERO strategy edit. Reads baseline b6604240 trades + raw M5.
For each trade, reconstruct pullback-quality features from bars STRICTLY BEFORE
entry_ts, then correlate with net_r outcome.

Pullback features (all causal — from setup_confirm_ts → entry_ts window):
  1. retrace_depth   = (fib_H - entry) / fib_diff  (long)  — how deep the pullback
  2. impulse_strength= fib_diff / D1_ATR14         — scale-invariant impulse size
  3. bars_to_zone    = # M15 bars from setup_confirm_ts to entry (pullback speed)
  4. pullback_velocity = fib_diff / bars_to_zone   — $ retraced per bar
  5. entry_body_ratio= |close-open|/(high-low) of entry-signal bar (confirmation strength)
  6. zone_dwell      = # bars price spent inside zone before entry

Output: per-feature win-rate + PF split into quintiles. If any feature cleanly
separates winners from losers, it's a candidate for the 3-phase gauntlet.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get("BT_ENGINE_DB_URL",
                        "postgresql+psycopg2://subash@localhost:5432/golddigger_bt")
RUN_ID = "b6604240-14f4-464f-86b4-0d0e32755838"
M5_PATH = Path("/tmp/oanda_xau_m5.parquet")
OUT = Path(__file__).parent


def load_trades() -> pd.DataFrame:
    eng = create_engine(DB_URL)
    q = text("""
        SELECT trade_id::text, entry_timestamp, exit_timestamp, side, leg,
               entry_price, net_r, bars_held,
               (raw_features->>'fib_L')::numeric AS fib_l,
               (raw_features->>'fib_H')::numeric AS fib_h,
               (raw_features->>'fib_diff')::numeric AS fib_diff,
               (raw_features->>'setup_confirm_ts') AS setup_confirm_ts,
               (raw_features->>'ny_hr')::int AS ny_hr
        FROM bt_trades
        WHERE run_id = :rid AND net_r IS NOT NULL AND raw_features ? 'fib_L'
        ORDER BY entry_timestamp
    """)
    with eng.connect() as c:
        df = pd.read_sql(q, c, params={"rid": RUN_ID})
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["setup_confirm_ts"] = pd.to_datetime(df["setup_confirm_ts"], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    for c in ["entry_price", "net_r", "fib_l", "fib_h", "fib_diff"]:
        df[c] = df[c].astype(float)
    df["win"] = (df["net_r"] > 0).astype(int)
    return df


def build_d1_atr(m5, period=14):
    d1 = (m5.set_index("timestamp").resample("1D", label="left", closed="left")
          .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
          .dropna().reset_index())
    if d1["timestamp"].dt.tz is None:
        d1["timestamp"] = d1["timestamp"].dt.tz_localize("UTC")
    d1["pc"] = d1["close"].shift(1)
    tr = pd.concat([(d1.high - d1.low), (d1.high - d1.pc).abs(), (d1.low - d1.pc).abs()], axis=1).max(axis=1)
    d1["atr14"] = tr.rolling(period, min_periods=period).mean()
    d1["close_ts"] = d1["timestamp"] + pd.Timedelta("1D")
    return d1.dropna(subset=["atr14"]).reset_index(drop=True)


def compute_features(df, m5, d1):
    ts = m5["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    o = m5["open"].to_numpy(); h = m5["high"].to_numpy()
    lo = m5["low"].to_numpy(); cl = m5["close"].to_numpy()
    d1c = d1["close_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    d1a = d1["atr14"].to_numpy()

    feats = []
    for _, t in df.iterrows():
        entry_np = t["entry_timestamp"].tz_convert("UTC").tz_localize(None).to_datetime64()
        setup_np = t["setup_confirm_ts"].tz_convert("UTC").tz_localize(None).to_datetime64() if pd.notna(t["setup_confirm_ts"]) else entry_np

        # D1 ATR causal
        m = d1c <= entry_np
        atr = float(d1a[m.sum() - 1]) if m.any() else np.nan

        # retrace depth (long: (H-entry)/diff, short: (entry-L)/diff)
        if t["side"] > 0:
            retrace = (t["fib_h"] - t["entry_price"]) / t["fib_diff"] if t["fib_diff"] > 0 else np.nan
        else:
            retrace = (t["entry_price"] - t["fib_l"]) / t["fib_diff"] if t["fib_diff"] > 0 else np.nan

        # bars from setup_confirm to entry
        i_setup = int(np.searchsorted(ts, setup_np, side="right"))
        i_entry = int(np.searchsorted(ts, entry_np, side="right"))
        bars_to_zone = max(1, (i_entry - i_setup))  # M5 bars

        # pullback velocity ($ per bar)
        velocity = t["fib_diff"] / bars_to_zone if bars_to_zone > 0 else np.nan

        # entry signal bar body ratio (bar just before entry fill)
        j = max(0, i_entry - 1)
        rng = h[j] - lo[j]
        body_ratio = abs(cl[j] - o[j]) / rng if rng > 0 else 0.0

        feats.append({
            "trade_id": t["trade_id"],
            "impulse_strength": t["fib_diff"] / atr if atr and atr > 0 else np.nan,
            "retrace_depth": retrace,
            "bars_to_zone": bars_to_zone,
            "pullback_velocity": velocity,
            "entry_body_ratio": body_ratio,
        })
    return pd.DataFrame(feats)


def quintile_report(df, feat):
    print(f"\n=== {feat} — quintile split ===", flush=True)
    d = df.dropna(subset=[feat]).copy()
    if len(d) < 100:
        print(f"  too few ({len(d)})"); return
    d["q"] = pd.qcut(d[feat], 5, labels=[1,2,3,4,5], duplicates="drop")
    for q in sorted(d["q"].dropna().unique()):
        s = d[d["q"] == q]
        n = len(s); wr = 100*s["win"].mean()
        pf_num = s.loc[s.net_r > 0, "net_r"].sum()
        pf_den = -s.loc[s.net_r <= 0, "net_r"].sum()
        pf = pf_num/pf_den if pf_den > 0 else float("inf")
        rng = f"[{s[feat].min():.3f}, {s[feat].max():.3f}]"
        print(f"  Q{q}  n={n:>5,d}  wr={wr:>5.2f}%  sumR={s.net_r.sum():>+8.1f}  "
              f"PF={pf:>5.3f}  range={rng}", flush=True)


def main():
    print(f"[{time.strftime('%H:%M:%S')}] loading...", flush=True)
    df = load_trades()
    print(f"  {len(df):,} trades", flush=True)
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    d1 = build_d1_atr(m5)
    print(f"  M5 {len(m5):,}  D1-ATR {len(d1):,}", flush=True)

    feats = compute_features(df, m5, d1)
    merged = df.merge(feats, on="trade_id")
    merged.to_parquet(OUT / "pullback_features.parquet")
    print(f"  features computed", flush=True)

    print(f"\n=== BASELINE (all) ===")
    print(f"  n={len(merged):,}  wr={100*merged.win.mean():.2f}%  sumR={merged.net_r.sum():+.1f}", flush=True)

    for f in ["impulse_strength", "retrace_depth", "bars_to_zone",
              "pullback_velocity", "entry_body_ratio"]:
        quintile_report(merged, f)

    # Split by leg too — A vs D may differ
    for leg in ["intraday_a_long", "intraday_d_short"]:
        sub = merged[merged.leg == leg]
        print(f"\n########## LEG {leg} (n={len(sub):,}) ##########", flush=True)
        for f in ["impulse_strength", "retrace_depth", "pullback_velocity"]:
            quintile_report(sub, f)

    print(f"\n[{time.strftime('%H:%M:%S')}] DONE", flush=True)


if __name__ == "__main__":
    main()
