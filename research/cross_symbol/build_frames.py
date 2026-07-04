"""Build H1 + M5 parquets from Dukascopy M1 yearly parquets for a cross-symbol test.

Duka fetch writes research/data/<sym>/<SYM>_M1_<year>.parquet (cols: timestamp, mid,
volume from the tick aggregator). We resample to M1 OHLC → then H1 + M5 in the schema
the Fib V2 rig expects (timestamp, open, high, low, close, volume).

Output: /tmp/oanda_<key>_h1.parquet, /tmp/oanda_<key>_m5.parquet
(the cross_symbol runners read from /tmp — reuse that convention).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def build(sym: str, key: str):
    ddir = Path(f"/Users/subash/SUBASH/GoldDigger/research/data/{key}")
    files = sorted(ddir.glob(f"{sym}_M1_*.parquet"))
    if not files:
        print(f"NO M1 files for {sym} in {ddir}", file=sys.stderr)
        return
    frames = [pd.read_parquet(f) for f in files]
    raw = pd.concat(frames, ignore_index=True)
    # Duka aggregator output: has 'timestamp' + 'mid' (+ maybe OHLC already). Normalise.
    if "close" not in raw.columns:
        # tick-mid → M1 OHLC
        raw = raw.sort_values("timestamp").set_index("timestamp")
        m1 = raw["mid"].resample("1min").ohlc()
        m1["volume"] = raw["volume"].resample("1min").sum() if "volume" in raw else 0.0
        m1 = m1.dropna().reset_index()
    else:
        m1 = raw[["timestamp", "open", "high", "low", "close", "volume"]].dropna()
    m1 = m1.sort_values("timestamp").reset_index(drop=True)
    if m1["timestamp"].dt.tz is None:
        m1["timestamp"] = m1["timestamp"].dt.tz_localize("UTC")

    def rs(rule):
        b = m1.set_index("timestamp").resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna().reset_index()
        return b

    h1 = rs("1h"); m5 = rs("5min")
    h1.to_parquet(f"/tmp/oanda_{key}_h1.parquet")
    m5.to_parquet(f"/tmp/oanda_{key}_m5.parquet")
    print(f"{sym}: M1 {len(m1):,} → H1 {len(h1):,}, M5 {len(m5):,}  "
          f"{m1['timestamp'].min()}→{m1['timestamp'].max()}  px {m1['close'].iloc[0]:.3f}")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "USDJPY"
    key = sys.argv[2] if len(sys.argv) > 2 else "jpy"
    build(sym, key)
