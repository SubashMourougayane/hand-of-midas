"""Direct Dukascopy XAUUSD M1 OHLC downloader (bypasses broken duka pkg).

Downloads tick .bi5 files from datafeed.dukascopy.com, decompresses LZMA,
aggregates to M1 bars (UTC), saves yearly parquets.

Dukascopy URL format:
  https://datafeed.dukascopy.com/datafeed/<SYM>/<YYYY>/<MM-1 zeropad>/<DD>/<HH>h_ticks.bi5
  (note: month is 0-indexed; January=00)

Tick format (LZMA-compressed):
  uint32  time_ms since hour
  uint32  ask_price * 10^(point_size)
  uint32  bid_price * 10^(point_size)
  float32 ask_volume
  float32 bid_volume
  big-endian; point_size for XAUUSD = 3 (price * 1000)
"""
from __future__ import annotations

import argparse
import lzma
import struct
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

import numpy as np
import pandas as pd

POINT = 1000.0  # XAUUSD: price stored as int*1000

BASE = "https://datafeed.dukascopy.com/datafeed"


def fetch_hour(symbol: str, dt: datetime) -> list[tuple[float, float, float]]:
    """Returns list of (ts_epoch_s, mid_price, volume) ticks for the hour."""
    url = f"{BASE}/{symbol}/{dt.year:04d}/{(dt.month-1):02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    import time as _t
    data = None
    for _att in range(6):
        try:
            resp = urlopen(url, timeout=30)
            data = resp.read()
            break
        except HTTPError as e:
            if e.code == 404:
                return []
            if e.code in (503, 429, 500):
                _t.sleep(1.5 * (_att + 1))  # backoff on rate-limit
                continue
            raise
        except Exception:
            _t.sleep(1.5 * (_att + 1)); continue
    if data is None:
        return []
    if not data:
        return []
    raw = lzma.decompress(data)
    n = len(raw) // 20
    out = []
    hour_start = dt.replace(minute=0, second=0, microsecond=0).timestamp()
    for i in range(n):
        time_ms, ask_i, bid_i, askv, bidv = struct.unpack_from(">IIIff", raw, i * 20)
        ts = hour_start + time_ms / 1000.0
        ask = ask_i / POINT
        bid = bid_i / POINT
        mid = (ask + bid) / 2.0
        vol = (askv + bidv) / 2.0
        out.append((ts, mid, vol))
    return out


def fetch_day(symbol: str, day: datetime) -> pd.DataFrame:
    """Returns M1 OHLCV DataFrame for one UTC day."""
    rows = []
    for h in range(24):
        dt = day.replace(hour=h)
        try:
            rows.extend(fetch_hour(symbol, dt))
        except Exception as exc:
            print(f"  [warn] {dt.isoformat()} fail: {exc}", file=sys.stderr)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts", "mid", "vol"])
    df["timestamp"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df.set_index("timestamp", inplace=True)
    m1 = df.resample("1min").agg(
        open=("mid", "first"),
        high=("mid", "max"),
        low=("mid", "min"),
        close=("mid", "last"),
        volume=("vol", "sum"),
    ).dropna().reset_index()
    return m1


def fetch_year(symbol: str, year: int, out_dir: Path, threads: int = 8) -> Path:
    """Aggregate full year of M1 bars; save parquet."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}_M1_{year}.parquet"
    if out_path.exists():
        print(f"  [skip] {out_path.name} exists")
        return out_path
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    days = []
    d = start
    while d < end:
        days.append(d)
        d += timedelta(days=1)
    print(f"[fetch] {symbol} {year}: {len(days)} days, {threads} threads...")
    frames = []
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(fetch_day, symbol, d): d for d in days}
        done = 0
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                df = fut.result()
            except Exception as exc:
                print(f"  [err] {d.date()}: {exc}", file=sys.stderr)
                continue
            if len(df):
                frames.append(df)
            done += 1
            if done % 30 == 0:
                print(f"  {year}: {done}/{len(days)} days done")
    if not frames:
        print(f"[empty] {symbol} {year}")
        return out_path
    full = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    full = full.drop_duplicates(subset="timestamp").reset_index(drop=True)
    full.to_parquet(out_path, compression="snappy")
    print(f"[save] {symbol} {year}: {len(full):,} M1 bars → {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--start-year", type=int, default=2005)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--out", default="/tmp/duka_xauusd")
    ap.add_argument("--threads", type=int, default=12)
    args = ap.parse_args()
    out_dir = Path(args.out)
    for yr in range(args.start_year, args.end_year + 1):
        fetch_year(args.symbol, yr, out_dir, threads=args.threads)


if __name__ == "__main__":
    main()
