"""001 — Opening Range Breakout (ORB) on Brent.

Source: Toby Crabel, "Day Trading with Short-Term Price Patterns and
Opening Range Breakout" (1990). One of the oldest documented day-trading
strategies; later popularized by Larry Williams and others.

Concept:
- Define an "opening range" as the first N minutes of a session
  (Crabel uses 30-90 min on equities; for 24-hour oil we pick a session
  start hour and N minutes after it).
- After the opening range closes, a LONG triggers on a break above the
  range high, a SHORT on a break below the range low.
- One trade per direction per day max. SL on the opposite side of the
  range (long: below range low, short: above range high). TP at fixed
  R-multiple of risk.

Why it COULD work on Brent:
- Daily session anchor (e.g., NY open at 13:30 UTC) creates a focal
  level institutional traders watch for breakouts.
- After accumulation/decision-making in the range, breakouts tend to
  travel with momentum.

Why it might NOT work on Brent:
- 24-hour oil has no clean "session open" the way equities do.
- Modern markets are more efficient at fading "obvious" breakouts.

Live-reproducibility:
- All references are to bars CLOSED before decision time.
- Range high/low are computed from bars in [open_hr, open_hr+N_minutes].
  The breakout candle is checked AFTER the range bars have closed.
- Entry on first bar where mid_close pierces the range edge.
- No future-data lookups.

Parameters (start at source-cited defaults; do NOT optimize until baseline
is recorded):
- session_open_hour_utc: 13 (close to NY open / EIA day session)
- range_minutes: 60 (= first hour after open)
- sl_buffer_pct: 0.10 (SL = opposite range edge minus 10% of range height)
- reward_to_risk: 2.0
- max_bars: 80 (= 4 hours on M3)
- one_trade_per_day: True
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Add repo root so `Labs.shared.*` imports resolve regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.runner import Signal


@dataclass(frozen=True)
class ORBConfig:
    session_open_hour_utc: int = 13
    range_minutes: int = 60
    sl_buffer_pct: float = 0.10
    reward_to_risk: float = 2.0
    max_bars: int = 80
    one_trade_per_day: bool = True


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: ORBConfig | None = None,
) -> list[Signal]:
    """Walk M3 bars day-by-day, build the opening range, emit breakout signals."""
    if cfg is None:
        cfg = ORBConfig()

    signals: list[Signal] = []
    range_bars_count = cfg.range_minutes // 3  # M3 bars in the range window

    # Group by date. M3 bar index is UTC, weekend gaps already absent.
    for date, day_df in m3.groupby(m3.index.normalize()):
        # Skip weekends (no bars) and partial days
        if len(day_df) < range_bars_count + 5:
            continue

        # Bars within the opening-range window (after session open hour)
        open_start = date + pd.Timedelta(hours=cfg.session_open_hour_utc)
        open_end = open_start + pd.Timedelta(minutes=cfg.range_minutes)
        range_df = day_df[(day_df.index >= open_start) & (day_df.index < open_end)]
        if len(range_df) < range_bars_count // 2:
            # Less than half the range window has data — skip
            continue

        range_high = float(range_df["mid_high"].max())
        range_low = float(range_df["mid_low"].min())
        range_size = range_high - range_low
        if range_size <= 0:
            continue

        # Now scan bars AFTER the range window for a breakout.
        # Even one scan bar is enough — the strategy fires the moment a
        # breakout candle prints. Requiring ≥ 2 bars would create a 1-bar
        # lookahead requirement (the BT would only emit a signal once a
        # second confirmation bar exists, which live cannot do at the
        # exact moment the breakout occurs).
        scan_df = day_df[day_df.index >= open_end]
        if len(scan_df) < 1:
            continue

        long_fired = False
        short_fired = False

        for ts, bar in scan_df.iterrows():
            mid_close = float(bar["mid_close"])
            mid_high = float(bar["mid_high"])
            mid_low = float(bar["mid_low"])

            # LONG breakout: bar's high pierces above range_high AND closes above
            if not long_fired and mid_high > range_high and mid_close > range_high:
                entry = float(bar["ask_close"])
                # SL = range_low - sl_buffer_pct * range_size (sits below range)
                sl = range_low - cfg.sl_buffer_pct * range_size
                risk = entry - sl
                if risk <= 0:
                    long_fired = True  # mark as attempted to avoid same-day re-fire
                    continue
                tp = entry + cfg.reward_to_risk * risk
                signals.append(Signal(
                    entry_bar_ts=ts,
                    direction="long",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    max_bars=cfg.max_bars,
                    metadata={
                        "strategy": "ORB",
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_size": range_size,
                        "session_open_hour_utc": cfg.session_open_hour_utc,
                    },
                ))
                long_fired = True
                if cfg.one_trade_per_day:
                    break

            # SHORT breakout
            if not short_fired and mid_low < range_low and mid_close < range_low:
                entry = float(bar["bid_close"])
                sl = range_high + cfg.sl_buffer_pct * range_size
                risk = sl - entry
                if risk <= 0:
                    short_fired = True
                    continue
                tp = entry - cfg.reward_to_risk * risk
                signals.append(Signal(
                    entry_bar_ts=ts,
                    direction="short",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    max_bars=cfg.max_bars,
                    metadata={
                        "strategy": "ORB",
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_size": range_size,
                        "session_open_hour_utc": cfg.session_open_hour_utc,
                    },
                ))
                short_fired = True
                if cfg.one_trade_per_day:
                    break

    return sorted(signals, key=lambda s: s.entry_bar_ts)


# ── Run as a script: load data, run, print stats ──────────────────────────


def main() -> None:
    from Labs.shared.data import get_brent
    from Labs.shared.runner import run_strategy, print_report
    from Labs.shared.safeguards import (
        lookahead_audit, random_baseline, print_safeguard_report,
    )

    print("Loading dev data via sealed gateway...")
    d1, h1, m3 = get_brent()
    print(f"  D1={len(d1):,}  H1={len(h1):,}  M3={len(m3):,}")

    cfg = ORBConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)

    print("\nRunning strategy...")
    result = run_strategy(fn, (d1, h1, m3))
    print_report("001 — ORB (session=13:00 UTC, 60 min range, RR=2.0)", result)

    print("Safeguards...")
    la = lookahead_audit(fn, (d1, h1, m3))
    rb = random_baseline((d1, h1, m3), n_trades=max(result.total_trades, 200))
    trusted = print_safeguard_report("001 — ORB", la, rb)
    print()
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED — investigate before reporting'}")


if __name__ == "__main__":
    main()
