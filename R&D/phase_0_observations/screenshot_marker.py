"""Phase 0 B1 — chart screenshotter for vision-assisted marking.

OVERRIDE NOTICE (D-004 in DECISIONS.md):
This module exists because the user explicitly overrode the
"user-marks-only" safeguard. The assistant is authorized to view these
PNGs, identify candidate setups, and pre-fill manual_marks.jsonl. The
user retains review/reject authority.

Each generated PNG corresponds to ONE trading day. PNG filename format:
    BCO_USD_M3_YYYY-MM-DD.png

The mark structure adds a `screenshot_path` field so any mark we save
can be audited back to the exact image we looked at.

Hard rules (lab walls intact):
- Reads price data ONLY through R&D/data_split.py:get_data(Phase.DEVELOPMENT).
  No raw CSV access from this script.
- Refuses to render any date outside the development window.
- Logs every rendered date to data_access_log.jsonl via the gateway.

Usage:
    # Render a single day:
    python R&D/phase_0_observations/screenshot_marker.py --date 2019-09-26

    # Render the next N days starting at a date:
    python R&D/phase_0_observations/screenshot_marker.py --start 2019-09-26 --count 30

    # Render every Nth day (samples across the dev window):
    python R&D/phase_0_observations/screenshot_marker.py --sample 30
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_split import Phase, get_data

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _render_day(m3: pd.DataFrame, day: pd.Timestamp, out_path: Path) -> bool:
    """Render one day's M3 candles to PNG. Returns True iff data existed."""
    next_day = day + pd.Timedelta(days=1)
    df = m3[(m3.index >= day) & (m3.index < next_day)]
    if df.empty:
        return False

    # 14x7 at dpi=100 → 1400x700 px (well under 2000 px API limit)
    fig, ax = plt.subplots(figsize=(14, 7))

    n = len(df)
    width = 0.7
    for x, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = row["mid_open"], row["mid_high"], row["mid_low"], row["mid_close"]
        color = "#26a69a" if c >= o else "#ef5350"
        ax.plot([x, x], [l, h], color=color, linewidth=0.6, zorder=1)
        body_low = min(o, c)
        body_high = max(o, c)
        ax.add_patch(Rectangle(
            (x - width / 2, body_low),
            width,
            max(body_high - body_low, (h - l) * 0.001),
            facecolor=color, edgecolor=color, linewidth=0.4, zorder=2,
        ))

    # Hourly time labels
    tick_positions = []
    tick_labels = []
    for i, ts in enumerate(df.index):
        if ts.minute == 0 and ts.second == 0:
            tick_positions.append(i)
            tick_labels.append(ts.strftime("%H:%M"))
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=10)
    ax.set_xlim(-0.5, n - 0.5)

    ymin = df["mid_low"].min()
    ymax = df["mid_high"].max()
    ypad = (ymax - ymin) * 0.06
    ax.set_ylim(ymin - ypad, ymax + ypad)
    ax.tick_params(axis="y", labelsize=10)
    ax.grid(True, alpha=0.3, linestyle="--", linewidth=0.5)

    # Annotate each candle index every 20 bars (= every hour) with a
    # tiny number above the chart so we have something specific to point
    # to when proposing a mark.
    for i in range(0, n, 20):
        ts = df.index[i]
        ax.annotate(
            f"{ts.strftime('%H:%M')}\n#{i}",
            xy=(i, ymax + ypad * 0.3),
            ha="center", va="bottom", fontsize=7, color="#999",
        )

    wd = DAY_LABELS[day.weekday()]
    title = (
        f"BCO_USD M3   —   {day.strftime('%Y-%m-%d')} ({wd})   "
        f"|   {n} bars   "
        f"|   range ${ymin:.2f} → ${ymax:.2f}   "
        f"(${(ymax - ymin):.2f})"
    )
    ax.set_title(title, fontsize=13, weight="bold")
    ax.set_xlabel("Time (UTC)  —  bar index numbers above chart for mark references", fontsize=9)
    ax.set_ylabel("BCO_USD price", fontsize=10)

    fig.tight_layout()
    fig.savefig(out_path, dpi=100, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return True


def render_dates(m3: pd.DataFrame, dates: list[pd.Timestamp]) -> list[Path]:
    """Render the supplied dates. Skip any with no data (weekends, holidays).

    Returns list of paths actually written.
    """
    written = []
    for day in dates:
        out_path = SCREENSHOTS_DIR / f"BCO_USD_M3_{day.strftime('%Y-%m-%d')}.png"
        if out_path.exists():
            print(f"  skip (exists): {out_path.name}")
            written.append(out_path)
            continue
        ok = _render_day(m3, day, out_path)
        if ok:
            print(f"  wrote: {out_path.name}")
            written.append(out_path)
        else:
            print(f"  no data: {day.strftime('%Y-%m-%d')} (weekend / holiday)")
    return written


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", type=str, help="Render a single day, e.g. 2019-09-26")
    g.add_argument("--start", type=str, help="Render N days starting from this date")
    g.add_argument("--sample", type=int, help="Render every Nth trading day across dev window")
    p.add_argument("--count", type=int, default=1, help="Used with --start (default 1)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print("Loading dev data via sealed gateway...")
    _, _, m3 = get_data(Phase.DEVELOPMENT, "BCO_USD")
    all_dates = sorted(set(m3.index.normalize().unique()))
    trading_dates = [d for d in all_dates if d.weekday() < 5]
    print(f"  Trading days available: {len(trading_dates)}  "
          f"({trading_dates[0].date()} → {trading_dates[-1].date()})")

    if args.date:
        target = pd.Timestamp(args.date, tz="UTC").normalize()
        if target not in trading_dates:
            print(f"  ERROR: {target.date()} is not a trading day (weekend / out of window).")
            return
        dates = [target]
    elif args.start:
        start = pd.Timestamp(args.start, tz="UTC").normalize()
        # Find first trading day at or after start
        idx = next((i for i, d in enumerate(trading_dates) if d >= start), None)
        if idx is None:
            print(f"  ERROR: {start.date()} is past the dev window end.")
            return
        dates = trading_dates[idx: idx + args.count]
    else:
        # --sample N
        every = args.sample
        dates = trading_dates[::every]

    print(f"Rendering {len(dates)} day(s)...")
    written = render_dates(m3, dates)
    print(f"Done. {len(written)} PNG(s) in {SCREENSHOTS_DIR}/")
    print()
    print(f"Run timestamp: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
