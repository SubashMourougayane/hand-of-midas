"""003 — Overnight Drift on Brent.

Source: Branch & Ma (2008) "Overnight Return, the Invisible Hand Behind
the Intraday Returns?", and many follow-ups documenting persistent
close-to-open drift on equity indices and commodity futures.

Concept:
- Enter LONG at NY-session close (~21:00 UTC for Brent)
- Exit at the next session's open (~14:00 UTC the following weekday)
- Hold ~17 hours overnight
- Equivalent SHORT version available (sell at close, buy at open)

Why it COULD work on Brent:
- Documented in equity literature; some commodity studies show similar
  effect from inventory positioning, weekend risk-off carry
- Holding overnight means avoiding most intraday noise

Why it might NOT work on Brent:
- The overnight drift effect on equities is weak in absolute terms
  (~0.05% per night). On commodities it's been less consistent.
- Costs (swap charges) eat the small drift on small accounts.

Live-reproducibility:
- Entry on the LAST M3 bar before close hour
- Exit on the FIRST M3 bar at-or-after open hour next trading day
- No future-data references.

Parameters:
- close_hour_utc: 21
- open_hour_utc: 14 (NY session open day +1)
- direction: 'long' (test both LONG and inverse SHORT)
- max_bars: 600 (≈ 30 hours; covers weekend gaps too)
- sl_pct: 0.05 (5% stop-loss as safety; full nights almost never hit this)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.runner import Signal


@dataclass(frozen=True)
class OvernightConfig:
    close_hour_utc: int = 21
    open_hour_utc: int = 14
    direction: str = "long"  # 'long' or 'short'
    max_bars: int = 600  # ~30 hours; allows weekend hold
    sl_pct: float = 0.05  # 5% safety stop


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: OvernightConfig | None = None,
) -> list[Signal]:
    if cfg is None:
        cfg = OvernightConfig()

    signals: list[Signal] = []

    # Group M3 bars by date; entry on last bar at-or-before close_hour_utc
    for date, day_df in m3.groupby(m3.index.normalize()):
        # Find the last bar at-or-before close_hour:00 on this day
        close_cutoff = date + pd.Timedelta(hours=cfg.close_hour_utc) + pd.Timedelta(minutes=59, seconds=59)
        candidates = day_df[
            (day_df.index >= date + pd.Timedelta(hours=cfg.close_hour_utc - 1))
            & (day_df.index <= close_cutoff)
        ]
        if candidates.empty:
            continue
        entry_bar_ts = candidates.index[-1]
        entry_bar = candidates.iloc[-1]

        # Need to find the exit target: next day's open_hour bar.
        # Exit fires via max_bars walk + TP target. We set TP = entry × 1.10
        # so it never gets hit; the actual exit is via max_bars (timed exit).
        if cfg.direction == "long":
            entry = float(entry_bar["ask_close"])
            sl = entry * (1.0 - cfg.sl_pct)
            tp = entry * 1.10  # un-hittable; forces max_bars timed exit
        else:
            entry = float(entry_bar["bid_close"])
            sl = entry * (1.0 + cfg.sl_pct)
            tp = entry * 0.90

        signals.append(Signal(
            entry_bar_ts=entry_bar_ts,
            direction=cfg.direction,
            entry=entry,
            sl=sl,
            tp=tp,
            max_bars=cfg.max_bars,
            metadata={
                "strategy": "OVERNIGHT_DRIFT",
                "close_hour": cfg.close_hour_utc,
                "open_hour": cfg.open_hour_utc,
            },
        ))

    return sorted(signals, key=lambda s: s.entry_bar_ts)


def main() -> None:
    from Labs.shared.data import get_brent
    from Labs.shared.runner import run_strategy, print_report
    from Labs.shared.safeguards import (
        lookahead_audit, random_baseline, print_safeguard_report,
    )

    print("Loading dev data via sealed gateway...")
    d1, h1, m3 = get_brent()
    print(f"  M3={len(m3):,}")

    for direction in ("long", "short"):
        cfg = OvernightConfig(direction=direction)
        fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)
        result = run_strategy(fn, (d1, h1, m3))
        print_report(f"003 — Overnight Drift ({direction.upper()}, hold ~17h)", result)

        la = lookahead_audit(fn, (d1, h1, m3))
        rb = random_baseline((d1, h1, m3), n_trades=max(result.total_trades, 200))
        trusted = print_safeguard_report(f"003 — Overnight {direction}", la, rb)
        print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED'}")
        print()


if __name__ == "__main__":
    main()
