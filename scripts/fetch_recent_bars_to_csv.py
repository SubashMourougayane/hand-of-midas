"""Fetch H1, M3, D bars from MT5/DWX and append-only-new rows to CSV files.

Reads the existing CSV (last timestamp), pulls recent bars from MT5, and
appends only rows newer than the existing last timestamp. Idempotent —
running twice does nothing on the second run.

Output rows match the existing CSV header:
  timestamp,bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,volume

Run on VPS only (needs DWX dir / live MT5 buffer).
"""
import os, sys, csv
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.execution.mt5_executor import get_candles

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO, "data", "raw")

INSTRUMENT = "XAU_USD"
TIMEFRAMES = [
    ("D",  "XAU_USD_D.csv",  100),
    ("H1", "XAU_USD_H1.csv", 800),
    ("M3", "XAU_USD_M3.csv", 8000),
]


def _last_ts(path: str) -> str:
    """Return the last (most recent) timestamp string in the CSV, or empty
    string if the file is missing/empty. The check below is a string compare,
    which works because all timestamps are stored in ISO-8601 UTC format."""
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        # Read last 4KB
        f.seek(max(0, size - 4096))
        tail = f.read().decode("utf-8", errors="replace").strip().split("\n")
    if not tail:
        return ""
    last = tail[-1]
    return last.split(",", 1)[0].strip()


def _normalize_ts(ts: str) -> str:
    """Existing CSV uses two formats:
      - '2006-03-19T20:00:00.000000000Z'  (very old rows)
      - '2026-05-24 21:00:00+00:00'       (recent rows)
    DWX get_candles returns '2026-06-12T13:00:00Z'. We standardize to the
    space-separated form to match the most recent existing rows.
    """
    # Strip trailing Z and convert T → ' '
    if ts.endswith("Z"):
        body = ts[:-1]
    else:
        body = ts
    body = body.replace("T", " ")
    # Add explicit +00:00 so downstream parsers treat as UTC
    if "+" not in body[10:] and not body.endswith("+00:00"):
        body = body + "+00:00"
    return body


def _row(bar: dict) -> list:
    return [
        _normalize_ts(bar["timestamp"]),
        bar["bid_open"], bar["bid_high"], bar["bid_low"], bar["bid_close"],
        bar["ask_open"], bar["ask_high"], bar["ask_low"], bar["ask_close"],
        bar.get("volume", 0),
    ]


def main():
    for tf, fname, count in TIMEFRAMES:
        path = os.path.join(RAW_DIR, fname)
        last = _last_ts(path)
        print(f"\n=== {tf} ({fname}) ===")
        print(f"  last existing ts: {last!r}")
        bars = get_candles(instrument=INSTRUMENT, granularity=tf, count=count)
        if not bars:
            print(f"  WARN: get_candles returned 0 bars for {tf}")
            continue
        first_dwx = bars[0]["timestamp"]
        last_dwx = bars[-1]["timestamp"]
        print(f"  DWX buffer: {len(bars)} bars, {first_dwx} → {last_dwx}")
        # Only append rows STRICTLY newer than last existing.
        last_norm = last  # raw string from CSV — has '+00:00'
        appended = 0
        rows_to_write = []
        for bar in bars:
            new_ts = _normalize_ts(bar["timestamp"])
            if last_norm and new_ts <= last_norm:
                continue
            rows_to_write.append(_row(bar))
            appended += 1
        if not rows_to_write:
            print(f"  no new rows to append")
            continue
        # Append (no header — file has it)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            for r in rows_to_write:
                w.writerow(r)
        print(f"  appended {appended} new rows (oldest {rows_to_write[0][0]}, newest {rows_to_write[-1][0]})")


if __name__ == "__main__":
    main()
