"""Fetch fresh BRENT.ecn + XAUUSD.ecn bars from JM/MT5 via DWX, append to local CSVs.

Pulls D / H1 / M3 candles via DWX `get_candles` (which reads from DWX EA's
shared market_data files), appends only new rows to existing CSVs in-place
(idempotent re-runs).

This is the JM-broker-side equivalent of update_csv_from_oanda.py.
Use THIS to get the same prices the live trading sees, NOT the structurally
different OANDA BCO_USD/XAU_USD prices.

Usage (VPS only — DWX EA must be running):
  python scripts\\update_csv_from_mt5.py
  python scripts\\update_csv_from_mt5.py --dry-run
  python scripts\\update_csv_from_mt5.py --instrument BCO_USD

Limits:
- DWX `get_candles` returns at most ~8000 bars per call. M3 covers ~16 days.
  If gap > that, run multiple times catching up incrementally, OR raise
  COUNT below if your broker holds longer history.
"""
import os
import sys
import csv
import argparse
import time as _time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.execution.mt5_executor import get_candles

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO, "data", "raw")

INSTRUMENTS = [
    ("XAU_USD", "Gold"),
    ("BCO_USD", "Brent Oil"),
]

TIMEFRAMES = [
    # (granularity, suffix, max bars to request from DWX)
    ("D",  "_D.csv",  500),
    ("H1", "_H1.csv", 2000),
    ("M3", "_M3.csv", 8000),
]


def _last_ts_in_csv(path: str) -> str:
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


def _csv_ts_compare_key(ts: str) -> str:
    """Normalize CSV timestamp to comparable form across legacy formats."""
    if not ts:
        return ""
    ts = ts.strip()
    if "T" in ts:
        return ts.split(".")[0].rstrip("Z")
    if " " in ts and "+" in ts:
        return ts.split("+")[0].replace(" ", "T")
    return ts


def _normalize_dwx_ts(ts: str) -> str:
    """DWX returns '2026-06-18T13:00:00Z'. Normalize to '2026-06-18 13:00:00+00:00'
    matching recent rows in the existing CSV."""
    body = ts[:-1] if ts.endswith("Z") else ts
    body = body.replace("T", " ")
    if "." in body:
        body = body.split(".")[0]
    if "+" not in body[10:] and not body.endswith("+00:00"):
        body = body + "+00:00"
    return body


def _bar_to_row(bar: dict, granularity: str) -> list | None:
    """Convert DWX candle dict to CSV row. Daily uses mid OHLC."""
    ts = _normalize_dwx_ts(bar["timestamp"])
    if granularity == "D":
        bo, bh, bl, bc = bar["bid_open"], bar["bid_high"], bar["bid_low"], bar["bid_close"]
        ao, ah, al, ac = bar["ask_open"], bar["ask_high"], bar["ask_low"], bar["ask_close"]
        mo, mh, ml, mc = (bo+ao)/2, (bh+ah)/2, (bl+al)/2, (bc+ac)/2
        return [ts, f"{mo:.4f}", f"{mh:.4f}", f"{ml:.4f}", f"{mc:.4f}", bar.get("volume", 0)]
    return [
        ts,
        f"{bar['bid_open']:.4f}", f"{bar['bid_high']:.4f}", f"{bar['bid_low']:.4f}", f"{bar['bid_close']:.4f}",
        f"{bar['ask_open']:.4f}", f"{bar['ask_high']:.4f}", f"{bar['ask_low']:.4f}", f"{bar['ask_close']:.4f}",
        bar.get("volume", 0),
    ]


def update_one(instrument: str, granularity: str, csv_path: str, count: int, dry_run: bool):
    last_ts_csv = _last_ts_in_csv(csv_path)
    last_norm = _csv_ts_compare_key(last_ts_csv)
    print(f"  last in CSV: {last_ts_csv!r}  (key: {last_norm})")

    bars = get_candles(instrument=instrument, granularity=granularity, count=count, price="BA")
    if not bars:
        print(f"  WARN: get_candles returned 0 bars")
        return 0

    first_dwx = bars[0]["timestamp"]
    last_dwx = bars[-1]["timestamp"]
    print(f"  DWX returned: {len(bars)} bars, {first_dwx} → {last_dwx}")

    # Filter strictly newer than last in CSV
    seen = set()
    new_rows = []
    for b in bars:
        row = _bar_to_row(b, granularity)
        if not row:
            continue
        new_key = _csv_ts_compare_key(row[0])
        if last_norm and new_key <= last_norm:
            continue
        if new_key in seen:
            continue
        seen.add(new_key)
        new_rows.append(row)
    new_rows.sort(key=lambda r: _csv_ts_compare_key(r[0]))

    print(f"  new rows to append: {len(new_rows)}")
    if not new_rows:
        return 0
    if dry_run:
        print(f"  DRY-RUN — first={new_rows[0][0]}, last={new_rows[-1][0]}")
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

    total = 0
    for instrument, label in instruments:
        print(f"\n========== {instrument} ({label}) ==========")
        for tf, suffix, count in TIMEFRAMES:
            csv_path = os.path.join(RAW_DIR, f"{instrument}{suffix}")
            print(f"\n  -- {tf} → {csv_path}")
            if not os.path.exists(csv_path):
                print(f"  CSV missing — skip")
                continue
            n = update_one(instrument, tf, csv_path, count=count, dry_run=args.dry_run)
            total += n
            _time.sleep(0.3)

    print(f"\n=== Done. Total {total} new rows appended {'(dry run)' if args.dry_run else ''} ===")


if __name__ == "__main__":
    main()
