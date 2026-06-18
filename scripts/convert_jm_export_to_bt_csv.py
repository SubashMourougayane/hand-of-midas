"""Convert raw MT5/JM export CSVs from data/raw/F28/ → standard BT CSV format.

INPUT (MT5 native export, tab-separated):
  <DATE>  <TIME>  <OPEN>  <HIGH>  <LOW>  <CLOSE>  <TICKVOL>  <VOL>  <SPREAD>
  2020.01.02  00:00:00  66.50  66.55  66.46  66.50  18  0  6

OUTPUT (matches existing data/raw/*.csv format used by BT engines):
  - For D:    timestamp,open,high,low,close,volume
  - For M3/H1: timestamp,bid_open,bid_high,bid_low,bid_close,
               ask_open,ask_high,ask_low,ask_close,volume

BID/ASK reconstruction: MT5 OHLC for symbols on JustMarkets is the BID side.
ASK = BID + (SPREAD × point_size). Brent (BRENT.ecn) point_size = 0.01.
Gold (XAUUSD.ecn) point_size = 0.01.

Per-row spread is preserved — when SPREAD is 0 (off-hours / illiquid moments)
we leave bid==ask.

Usage:
  python3 scripts/convert_jm_export_to_bt_csv.py
  python3 scripts/convert_jm_export_to_bt_csv.py --instrument BCO_USD --start-year 2020
  python3 scripts/convert_jm_export_to_bt_csv.py --output-dir data/raw/jm

Default writes to data/raw/jm/ so we DON'T overwrite the existing OANDA-based
CSVs in data/raw/.
"""
import os
import sys
import csv
import argparse
import glob
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F28_DIR = os.path.join(REPO, "data", "raw", "F28")

# Symbol naming: MT5 uses BRENT.ecn / XAUUSD.ecn. Map to our internal.
SYMBOL_MAP = {
    "BRENT": "BCO_USD",
    "XAUUSD": "XAU_USD",
}

# Point size for ASK reconstruction
# (SPREAD is in points; point_size in price terms)
POINT_SIZE = {
    "BCO_USD": 0.01,
    "XAU_USD": 0.01,
}


def find_input_files(symbol_filter: str | None = None) -> list[tuple[str, str, str]]:
    """Walk F28_DIR, return list of (mt5_symbol, timeframe, full_path).

    Filenames look like: BRENT.ecn_M1_201601040000_202606181841.csv
    """
    out = []
    for path in sorted(glob.glob(os.path.join(F28_DIR, "*.csv"))):
        name = os.path.basename(path)
        # Parse: <SYMBOL>.ecn_<TF>_<from>_<to>.csv
        try:
            head = name.split(".csv")[0]
            parts = head.split("_")
            symbol_with_ecn = parts[0]  # BRENT.ecn → BRENT
            mt5_sym = symbol_with_ecn.split(".")[0]
            tf = parts[1]  # M1 / M3 / H1 / D
        except (IndexError, ValueError):
            print(f"  skip (bad name): {name}")
            continue

        internal = SYMBOL_MAP.get(mt5_sym)
        if not internal:
            print(f"  skip (unknown symbol {mt5_sym}): {name}")
            continue
        if symbol_filter and internal != symbol_filter:
            continue

        out.append((internal, tf, path))
    return out


def convert_one(internal_sym: str, tf: str, src_path: str, out_dir: str,
                start_year: int, end_year: int):
    """Convert one MT5 export file → standard CSV format."""
    point = POINT_SIZE.get(internal_sym, 0.01)
    is_daily = (tf == "D")
    out_filename = f"{internal_sym}_{tf}.csv"
    out_path = os.path.join(out_dir, out_filename)

    # Standard header
    if is_daily:
        header = ["timestamp", "open", "high", "low", "close", "volume"]
    else:
        header = ["timestamp",
                  "bid_open", "bid_high", "bid_low", "bid_close",
                  "ask_open", "ask_high", "ask_low", "ask_close",
                  "volume"]

    n_in = 0
    n_out = 0
    n_filtered = 0
    n_skipped_year = 0

    with open(src_path, "r") as fin, open(out_path, "w", newline="") as fout:
        r = csv.reader(fin, delimiter="\t")
        w = csv.writer(fout)
        in_header = next(r)
        w.writerow(header)

        for row in r:
            n_in += 1
            try:
                dt_str = row[0]  # 2020.01.02
                tm_str = row[1]  # 00:00:00
                o = float(row[2]); h = float(row[3]); l = float(row[4]); c = float(row[5])
                tickvol = int(row[6]) if row[6] else 0
                spread_pts = int(row[8]) if row[8] else 0
            except (ValueError, IndexError):
                continue

            year = int(dt_str.split(".")[0])
            if year < start_year or year > end_year:
                n_skipped_year += 1
                continue

            # Filter out daily-only rows (00:00:00) for intraday timeframes
            # so we don't pollute M3/H1/M1 with daily fallback bars
            if not is_daily and tm_str == "00:00:00":
                n_filtered += 1
                continue

            # Build ISO timestamp matching existing CSV format:
            # "2026-05-22 06:00:00+00:00"
            iso_ts = f"{dt_str.replace('.', '-')} {tm_str}+00:00"

            if is_daily:
                w.writerow([iso_ts, f"{o:.4f}", f"{h:.4f}", f"{l:.4f}", f"{c:.4f}", tickvol])
            else:
                # MT5 OHLC = BID. ASK = BID + (SPREAD × point_size)
                spread_price = spread_pts * point
                w.writerow([
                    iso_ts,
                    f"{o:.4f}", f"{h:.4f}", f"{l:.4f}", f"{c:.4f}",  # bid
                    f"{o + spread_price:.4f}", f"{h + spread_price:.4f}",
                    f"{l + spread_price:.4f}", f"{c + spread_price:.4f}",  # ask
                    tickvol,
                ])
            n_out += 1

    print(f"  {internal_sym} {tf}: read {n_in:,}, wrote {n_out:,} "
          f"(filtered {n_filtered:,} 00:00 bars, skipped {n_skipped_year:,} out-of-year) "
          f"→ {out_path}")
    return n_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default=None,
                    help="BCO_USD or XAU_USD (both if omitted)")
    ap.add_argument("--start-year", type=int, default=2019,
                    help="Drop rows before this year (default 2019 — first intraday data)")
    ap.add_argument("--end-year", type=int, default=2099)
    ap.add_argument("--output-dir", default=os.path.join(REPO, "data", "raw", "jm"),
                    help="Where to write converted CSVs (default data/raw/jm/ to keep OANDA CSVs separate)")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    inputs = find_input_files(symbol_filter=args.instrument)
    if not inputs:
        print(f"No input files found in {F28_DIR}")
        sys.exit(1)

    print(f"Output dir: {args.output_dir}")
    print(f"Year range: {args.start_year}–{args.end_year}")
    print()
    total = 0
    h1_paths_by_sym: dict[str, str] = {}  # remember H1 source for daily aggregation
    for internal_sym, tf, src in inputs:
        if tf == "M1":
            print(f"  skip M1 (not used by BT engines): {os.path.basename(src)}")
            continue
        if tf == "H1":
            h1_paths_by_sym[internal_sym] = src
        n = convert_one(internal_sym, tf, src, args.output_dir,
                        args.start_year, args.end_year)
        total += n

    # Build daily CSV by aggregating H1 bars (one daily bar per UTC day).
    # Bias filter (V1+V2) needs daily mid OHLC.
    for internal_sym, h1_src in h1_paths_by_sym.items():
        n = build_daily_from_h1(internal_sym, h1_src, args.output_dir,
                                args.start_year, args.end_year)
        total += n

    print(f"\n=== Done. Wrote {total:,} rows total ===")


def build_daily_from_h1(internal_sym: str, h1_src: str, out_dir: str,
                        start_year: int, end_year: int) -> int:
    """Aggregate H1 bars into daily OHLC. Output matches existing _D.csv format.

    Daily bias (V1+V2) compute uses MID OHLC. We keep simple: average of bid+ask.
    """
    point = POINT_SIZE.get(internal_sym, 0.01)
    out_path = os.path.join(out_dir, f"{internal_sym}_D.csv")

    # Bucket by date (YYYY-MM-DD)
    from collections import defaultdict
    buckets: dict[str, dict] = defaultdict(lambda: {"o": None, "h": -1e9, "l": 1e9, "c": None, "v": 0})
    n_in = 0
    with open(h1_src, "r") as fin:
        r = csv.reader(fin, delimiter="\t")
        next(r)
        for row in r:
            n_in += 1
            try:
                dt_str = row[0]   # 2020.01.02
                tm_str = row[1]   # HH:MM:SS
                o = float(row[2]); h = float(row[3]); l = float(row[4]); c = float(row[5])
                tickvol = int(row[6]) if row[6] else 0
                spread_pts = int(row[8]) if row[8] else 0
            except (ValueError, IndexError):
                continue
            year = int(dt_str.split(".")[0])
            if year < start_year or year > end_year:
                continue

            # Skip the 00:00 daily-fallback rows (2016-2018) — only aggregate
            # actual intraday H1 bars.
            if tm_str == "00:00:00":
                continue

            # Mid prices (bid + spread/2 = mid, but simpler: use bid for OHLC and
            # add spread/2 to get mid)
            half_sp = (spread_pts * point) / 2
            o_m = o + half_sp; h_m = h + half_sp
            l_m = l + half_sp; c_m = c + half_sp

            d_key = dt_str.replace(".", "-")
            b = buckets[d_key]
            if b["o"] is None:
                b["o"] = o_m
            if h_m > b["h"]:
                b["h"] = h_m
            if l_m < b["l"]:
                b["l"] = l_m
            b["c"] = c_m  # last bar's close
            b["v"] += tickvol

    rows = sorted(buckets.items())
    # Match the M3/H1 format so backend.data.cache.load_candles can derive
    # mid_* columns. Daily synthesizes bid==ask (no historical spread per
    # day; using the H1 spreads to reconstruct daily bid/ask isn't
    # meaningful at this granularity).
    with open(out_path, "w", newline="") as fout:
        w = csv.writer(fout)
        w.writerow(["timestamp",
                    "bid_open", "bid_high", "bid_low", "bid_close",
                    "ask_open", "ask_high", "ask_low", "ask_close",
                    "volume"])
        for d_key, b in rows:
            ts = f"{d_key} 00:00:00+00:00"
            w.writerow([ts,
                        f"{b['o']:.4f}", f"{b['h']:.4f}",
                        f"{b['l']:.4f}", f"{b['c']:.4f}",
                        f"{b['o']:.4f}", f"{b['h']:.4f}",
                        f"{b['l']:.4f}", f"{b['c']:.4f}",
                        b["v"]])
    print(f"  {internal_sym} D (aggregated from H1): read {n_in:,} H1, "
          f"wrote {len(rows):,} daily bars → {out_path}")
    return len(rows)


if __name__ == "__main__":
    main()
