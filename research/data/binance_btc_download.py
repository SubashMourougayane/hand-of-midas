"""Pull BTCUSDT 1m OHLCV from Binance public data dumps → local parquet.

Source: https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/
Each month is a zipped CSV (no API key, no rate limit worries). We concat all
months, normalise to the SAME schema the XAU causal harness uses
(timestamp[UTC], open, high, low, close, volume), dedup + sort, and save one
parquet.

Binance monthly kline CSV columns (no header):
  0 open_time(ms)  1 open  2 high  3 low  4 close  5 volume
  6 close_time     7 quote_volume  8 count  9 taker_buy_base
  10 taker_buy_quote  11 ignore

STRICT: open_time is the bar's OPEN (left-labelled), UTC. This matches the
XAU harness (resample label='left'). No look-ahead introduced here — pure ingest.
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

import numpy as np
import pandas as pd

BASE = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m"
OUT_DIR = Path("/Users/subash/SUBASH/GoldDigger/research/data/btc")
OUT_PARQUET = OUT_DIR / "BTCUSDT_M1.parquet"

# Match the XAU research window start; go to last full month.
START_YM = (2019, 10)


def _months(start_ym, end_ym):
    y, m = start_ym
    ey, em = end_ym
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _fetch_month(y: int, m: int) -> pd.DataFrame | None:
    url = f"{BASE}/BTCUSDT-1m-{y:04d}-{m:02d}.zip"
    try:
        raw = urlopen(url, timeout=60).read()
    except HTTPError as e:
        print(f"  {y}-{m:02d}: HTTP {e.code} (skip)")
        return None
    except Exception as e:
        print(f"  {y}-{m:02d}: {e} (skip)")
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            # Binance switched to a header row in some 2025 files; detect it.
            df = pd.read_csv(
                f, header=None,
                names=["open_time", "open", "high", "low", "close", "volume",
                       "close_time", "quote_volume", "count", "tbb", "tbq", "ignore"],
            )
    # Drop a stray header row if the file included one.
    if not str(df.iloc[0]["open_time"]).replace(".", "").isdigit():
        df = df.iloc[1:].reset_index(drop=True)
    for c in ["open_time", "open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open_time", "open", "high", "low", "close"])
    # open_time is ms since epoch. Some months are in microseconds (2025+) — detect.
    ot = df["open_time"].astype("int64")
    unit = "us" if ot.iloc[0] > 10**14 else "ms"
    df["timestamp"] = pd.to_datetime(ot, unit=unit, utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    # Last COMPLETE month.
    end_y, end_m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    frames = []
    for y, m in _months(START_YM, (end_y, end_m)):
        d = _fetch_month(y, m)
        if d is not None and len(d):
            frames.append(d)
            print(f"  {y}-{m:02d}: {len(d):>6d} bars")
    if not frames:
        print("NO DATA FETCHED", file=sys.stderr)
        return 1
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    out.to_parquet(OUT_PARQUET)

    # Integrity report — no look-ahead here, just ingest QA.
    ts = out["timestamp"]
    gaps = ts.diff().dt.total_seconds().dropna()
    n_gap = int((gaps > 60).sum())  # >1 bar missing
    print("\n=== BTCUSDT M1 ingest ===")
    print(f"  rows       : {len(out):,}")
    print(f"  range      : {ts.min()} → {ts.max()}")
    print(f"  monotonic  : {ts.is_monotonic_increasing}")
    print(f"  dups       : {int(ts.duplicated().sum())}")
    print(f"  nan_ohlc   : {int(out[['open','high','low','close']].isna().any(axis=1).sum())}")
    print(f"  gaps>1min  : {n_gap}  (BTC is 24/7 — some venue-maintenance gaps expected)")
    print(f"  saved      : {OUT_PARQUET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
