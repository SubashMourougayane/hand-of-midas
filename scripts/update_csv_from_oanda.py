"""Update local CSV files with fresh OANDA candles.

Pulls XAU_USD + BCO_USD from OANDA REST, appends new bars (post last
existing timestamp) to the existing data/raw/*.csv files. Idempotent.

Format matches existing CSV header:
  timestamp,bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,volume

Daily CSV uses simpler format:
  timestamp,open,high,low,close,volume

Usage:
  python3 scripts/update_csv_from_oanda.py
  python3 scripts/update_csv_from_oanda.py --dry-run

Reads OANDA_TOKEN from .env at repo root.
"""
import os
import sys
import csv
import json
import time
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from dotenv import load_dotenv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO, "data", "raw")
load_dotenv(os.path.join(REPO, ".env"))

OANDA_TOKEN = os.getenv("OANDA_TOKEN", "")
OANDA_URL = os.getenv("OANDA_URL", "https://api-fxpractice.oanda.com/v3")

if not OANDA_TOKEN:
    print("ERROR: OANDA_TOKEN missing in .env")
    sys.exit(1)

INSTRUMENTS = [
    ("XAU_USD", "Gold"),
    ("BCO_USD", "Brent Oil"),
]

TIMEFRAMES = [
    # (granularity, csv_suffix, oanda_max_count_per_call)
    ("D",  "_D.csv",  500),
    ("H1", "_H1.csv", 5000),
    ("M3", "_M3.csv", 5000),
]


def _last_ts_in_csv(path: str) -> str:
    """Return the most recent timestamp in the CSV (string compare)."""
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 4096))
        tail = f.read().decode("utf-8", errors="replace").strip().split("\n")
    if not tail:
        return ""
    return tail[-1].split(",", 1)[0].strip()


def _normalize_ts(ts: str) -> str:
    """Convert OANDA '2026-06-18T13:00:00.000000000Z' → '2026-06-18 13:00:00+00:00'.
    Matches the recent format used in existing CSVs."""
    body = ts[:-1] if ts.endswith("Z") else ts
    body = body.replace("T", " ")
    # Drop nanoseconds — keep only YYYY-MM-DD HH:MM:SS
    if "." in body:
        body = body.split(".")[0]
    # Add +00:00
    if "+" not in body[10:] and not body.endswith("+00:00"):
        body = body + "+00:00"
    return body


def _csv_ts_compare_key(ts: str) -> str:
    """Normalize a CSV timestamp into a comparable form regardless of which
    legacy format it uses (some old rows are 'YYYY-MM-DDTHH:MM:SS.000000000Z',
    newer rows are 'YYYY-MM-DD HH:MM:SS+00:00'). Both flatten to the same
    YYYY-MM-DDTHH:MM:SS prefix for ordering."""
    if not ts:
        return ""
    ts = ts.strip()
    if "T" in ts:
        body = ts.split(".")[0].rstrip("Z")
        return body
    if " " in ts and "+" in ts:
        body = ts.split("+")[0]
        return body.replace(" ", "T")
    return ts


def _fetch_oanda_candles(instrument: str, granularity: str, from_ts: str = None, count: int = 5000):
    """Single OANDA candles call. from_ts in RFC3339. Returns list of dicts."""
    params = {
        "granularity": granularity,
        "price": "BA",
        "count": count,
    }
    if from_ts:
        params["from"] = from_ts
        # OANDA pagination: from + count, up to count bars
    url = f"{OANDA_URL}/instruments/{instrument}/candles?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {OANDA_TOKEN}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("candles", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  ERR HTTP {e.code}: {body}")
        return []
    except Exception as e:
        print(f"  ERR: {e}")
        return []


def _candle_to_row(c: dict, granularity: str) -> list | None:
    """Convert OANDA candle JSON → CSV row.
    Daily uses mid OHLC (no bid/ask — matches existing _D.csv format).
    H1/M3 use bid/ask quad."""
    if not c.get("complete"):
        return None  # skip incomplete current bar
    ts = _normalize_ts(c["time"])
    bid = c.get("bid", {})
    ask = c.get("ask", {})
    vol = c.get("volume", 0)

    if granularity == "D":
        # daily existing format: timestamp,open,high,low,close,volume (mid only)
        bo, bh, bl, bc = float(bid.get("o", 0)), float(bid.get("h", 0)), float(bid.get("l", 0)), float(bid.get("c", 0))
        ao, ah, al, ac = float(ask.get("o", 0)), float(ask.get("h", 0)), float(ask.get("l", 0)), float(ask.get("c", 0))
        mo, mh, ml, mc = (bo+ao)/2, (bh+ah)/2, (bl+al)/2, (bc+ac)/2
        return [ts, f"{mo:.4f}", f"{mh:.4f}", f"{ml:.4f}", f"{mc:.4f}", vol]

    return [
        ts,
        f"{float(bid.get('o', 0)):.4f}", f"{float(bid.get('h', 0)):.4f}", f"{float(bid.get('l', 0)):.4f}", f"{float(bid.get('c', 0)):.4f}",
        f"{float(ask.get('o', 0)):.4f}", f"{float(ask.get('h', 0)):.4f}", f"{float(ask.get('l', 0)):.4f}", f"{float(ask.get('c', 0)):.4f}",
        vol,
    ]


def _ts_to_rfc3339(csv_ts: str) -> str:
    """Convert CSV ts ('2026-05-22 06:00:00+00:00' or 'T-Z') to RFC3339 for OANDA from=."""
    if not csv_ts:
        return ""
    body = csv_ts.strip()
    # Already RFC3339-ish
    if body.endswith("Z"):
        return body.split(".")[0] + "Z"
    if "+" in body[10:]:
        body = body.split("+")[0].replace(" ", "T") + "Z"
        return body
    return body.replace(" ", "T") + "Z"


def update_one(instrument: str, granularity: str, csv_path: str, dry_run: bool = False):
    last_ts_csv = _last_ts_in_csv(csv_path)
    last_norm = _csv_ts_compare_key(last_ts_csv)
    print(f"  last in CSV: {last_ts_csv!r} (key: {last_norm})")

    if last_ts_csv:
        from_ts = _ts_to_rfc3339(last_ts_csv)
    else:
        from_ts = "2026-01-01T00:00:00Z"

    # Paginate — OANDA caps at ~5000 bars per call. Loop until we get a
    # batch smaller than 5000 (= no more data).
    all_bars = []
    cursor = from_ts
    page = 0
    while True:
        page += 1
        print(f"  page {page}: fetching from {cursor}")
        bars = _fetch_oanda_candles(instrument, granularity, from_ts=cursor, count=5000)
        if not bars:
            break
        all_bars.extend(bars)
        if len(bars) < 5000:
            break
        # Next cursor = last bar's time + 1 second (avoid duplicate)
        last_time = bars[-1]["time"]
        cursor = last_time
        if page >= 20:  # safety
            print(f"  WARN: pagination cap hit (20 pages)")
            break
        time.sleep(0.3)

    if not all_bars:
        print(f"  no bars returned")
        return 0
    first_oanda = all_bars[0]["time"]
    last_oanda = all_bars[-1]["time"]
    print(f"  OANDA total: {len(all_bars)} bars, {first_oanda} → {last_oanda}")

    # Dedupe (cursor overlap can produce duplicates) + filter strictly newer
    seen_keys = set()
    new_rows = []
    for c in all_bars:
        row = _candle_to_row(c, granularity)
        if not row:
            continue
        new_key = _csv_ts_compare_key(row[0])
        if last_norm and new_key <= last_norm:
            continue
        if new_key in seen_keys:
            continue
        seen_keys.add(new_key)
        new_rows.append(row)

    # Sort by timestamp (ascending) just to be safe
    new_rows.sort(key=lambda r: _csv_ts_compare_key(r[0]))

    print(f"  new rows to append: {len(new_rows)}")
    if not new_rows:
        return 0

    if dry_run:
        print(f"  DRY-RUN — would append {len(new_rows)} rows. First: {new_rows[0][0]}, last: {new_rows[-1][0]}")
        return len(new_rows)

    with open(csv_path, "a", newline="") as f:
        w = csv.writer(f)
        for row in new_rows:
            w.writerow(row)
    print(f"  appended {len(new_rows)} rows to {csv_path}")
    return len(new_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--instrument", default=None, help="XAU_USD or BCO_USD (both if omitted)")
    args = ap.parse_args()

    instruments = [(i, label) for i, label in INSTRUMENTS if not args.instrument or i == args.instrument]
    if not instruments:
        print(f"unknown instrument: {args.instrument}")
        sys.exit(1)

    total_appended = 0
    for instrument, label in instruments:
        print(f"\n========== {instrument} ({label}) ==========")
        for tf, suffix, _maxc in TIMEFRAMES:
            csv_path = os.path.join(RAW_DIR, f"{instrument}{suffix}")
            print(f"\n  -- {tf} → {csv_path}")
            if not os.path.exists(csv_path):
                print(f"  CSV missing — skip")
                continue
            n = update_one(instrument, tf, csv_path, dry_run=args.dry_run)
            total_appended += n
            time.sleep(0.5)  # OANDA rate-limit-friendly

    print(f"\n=== Done. Total {total_appended} new rows appended {'(dry run)' if args.dry_run else ''} ===")


if __name__ == "__main__":
    main()
