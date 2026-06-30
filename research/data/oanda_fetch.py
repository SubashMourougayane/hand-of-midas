"""OANDA historical candle downloader for XAU_USD.

Uses practice host (api-fxpractice.oanda.com). Practice token works for
historical reads.

Pagination: 5000 candles per call. Walk forward by 'from' timestamp.

Output: parquet per granularity.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import pandas as pd


HOST = "https://api-fxpractice.oanda.com"
TOKEN = os.environ.get("OANDA_TOKEN") or ""

GRANULARITY_SECS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D": 86400,
}


def fetch_batch(symbol: str, gran: str, from_ts: datetime, count: int = 5000) -> list[dict]:
    params = {
        "from": from_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "granularity": gran,
        "count": count,
        "price": "M",  # mid
    }
    url = f"{HOST}/v3/instruments/{symbol}/candles?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    for attempt in range(5):
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            return data.get("candles", [])
        except HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                print(f"  [429] backoff {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as exc:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)
    return []


def candles_to_df(candles: list[dict]) -> pd.DataFrame:
    rows = []
    for c in candles:
        if not c.get("complete"):
            continue
        ts = pd.to_datetime(c["time"], utc=True)
        m = c["mid"]
        rows.append({
            "timestamp": ts,
            "open": float(m["o"]),
            "high": float(m["h"]),
            "low": float(m["l"]),
            "close": float(m["c"]),
            "volume": float(c.get("volume", 0)),
        })
    return pd.DataFrame(rows)


def fetch_range(symbol: str, gran: str, start: datetime, end: datetime,
                out_path: Path, batch_count: int = 5000):
    """Paginate from start → end. Save parquet."""
    if not TOKEN:
        raise SystemExit("OANDA_TOKEN missing from env")
    print(f"[fetch] {symbol} {gran} {start.date()} → {end.date()}")
    all_rows = []
    sec_per = GRANULARITY_SECS[gran]
    cursor = start
    while cursor < end:
        candles = fetch_batch(symbol, gran, cursor, count=batch_count)
        if not candles:
            print(f"  [empty] @ {cursor.isoformat()} — advancing 1 day")
            cursor = cursor + pd.Timedelta(days=1).to_pytimedelta()
            continue
        df = candles_to_df(candles)
        if len(df) == 0:
            cursor = cursor + pd.Timedelta(seconds=sec_per * batch_count).to_pytimedelta()
            continue
        all_rows.append(df)
        last_ts = df["timestamp"].iloc[-1].to_pydatetime()
        cursor = last_ts + pd.Timedelta(seconds=sec_per).to_pytimedelta()
        if cursor > end:
            break
        print(f"  +{len(df):>5d} bars  cursor={cursor.isoformat()}  total={sum(len(d) for d in all_rows):,}")
    if not all_rows:
        print("[empty]")
        return
    full = pd.concat(all_rows, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    full = full[(full["timestamp"] >= start_ts) & (full["timestamp"] < end_ts)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full.to_parquet(out_path, compression="snappy")
    print(f"[save] {len(full):,} bars → {out_path}")
    return full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAU_USD")
    ap.add_argument("--gran", default="H1")
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--out", default="/tmp/oanda_xau_h1.parquet")
    args = ap.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    fetch_range(args.symbol, args.gran, start, end, Path(args.out))


if __name__ == "__main__":
    # Load .env if needed
    env_path = Path("/Users/subash/SUBASH/GoldDigger/.env")
    if env_path.exists() and not TOKEN:
        for line in env_path.read_text().splitlines():
            if line.startswith("OANDA_TOKEN="):
                os.environ["OANDA_TOKEN"] = line.split("=", 1)[1].strip()
                TOKEN = os.environ["OANDA_TOKEN"]
                break
    main()
