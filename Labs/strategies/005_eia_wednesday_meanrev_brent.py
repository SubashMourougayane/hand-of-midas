"""005 — Wednesday EIA Mean Reversion on Brent.

Source: trading-floor folklore + several published commodity-news papers.
US EIA Petroleum Status Report releases Wednesday 10:30 ET (14:30 UTC
in winter, 14:30 UTC year-round if you fix to UTC). The release creates
a sharp price reaction in the first 5-10 minutes; well-documented that
the IMMEDIATE reaction frequently overshoots and partially mean-reverts
within 30-60 minutes.

Concept:
- ONLY on Wednesdays.
- Compute the M3 bar at 14:30 UTC. Note its high and low.
- After the next K M3 bars (~ 5-10 min), compare price against its
  pre-release reference. If price has moved more than X stdev (using
  the prior 30-bar M3 stdev) in either direction, fade it back toward
  the pre-release midpoint.
- Specifically: if up move beyond threshold → SHORT. If down move → LONG.
- TP = pre-release midpoint. SL = beyond the spike high/low + buffer.

Why it COULD work on Brent:
- News-driven volatility OFTEN overshoots; institutional fades are well-
  documented (research on equity index futures around FOMC has the same
  shape).
- Sharp 5-10-min spike → reversion is a discrete, testable event.

Why it might NOT work on Brent:
- The "overshoot" can keep going (genuinely bullish/bearish surprise).
- BCO_USD is Brent (London-based) but EIA inventories are about WTI;
  the cross-correlation is usually high but not always.

Live-reproducibility:
- 30-bar pre-release stdev uses M3 bars BEFORE 14:30 (closed by then).
- Pre-release reference high/low fixed at 14:30 bar's open/close (closed
  by 14:33 — read from THAT bar, not from 14:30 at 14:30).
- Wait K bars (~ 5 min = 1-2 M3 bars). Decision at 14:33 or 14:36.
- All inputs are bars closed before decision time.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.runner import Signal


@dataclass(frozen=True)
class EIAConfig:
    release_hour_utc: int = 14
    release_minute: int = 30  # 14:30 UTC release time (year-round)
    pre_stdev_bars: int = 30  # ~ 90 min of M3 bars
    decision_bars_after: int = 2  # decision 6 min after release (= 14:36)
    overshoot_stdev_threshold: float = 2.0
    sl_buffer_stdev: float = 1.5  # additional buffer beyond spike extreme
    max_bars: int = 40  # ~ 2 hours hold


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: EIAConfig | None = None,
) -> list[Signal]:
    if cfg is None:
        cfg = EIAConfig()

    signals: list[Signal] = []

    # Walk by date, only Wednesdays
    for date, day_df in m3.groupby(m3.index.normalize()):
        if date.weekday() != 2:  # Wednesday only
            continue

        # Pre-release reference window: 30 M3 bars BEFORE 14:30
        release_ts = date + pd.Timedelta(hours=cfg.release_hour_utc, minutes=cfg.release_minute)
        decision_ts = release_ts + pd.Timedelta(minutes=cfg.decision_bars_after * 3)

        if release_ts not in day_df.index:
            continue
        if decision_ts not in day_df.index:
            continue

        pre_release = day_df[day_df.index < release_ts].tail(cfg.pre_stdev_bars)
        if len(pre_release) < cfg.pre_stdev_bars:
            continue

        # Pre-release reference: midpoint of last bar before release
        pre_close = float(pre_release["mid_close"].iat[-1])
        # Pre-release stdev of bar-to-bar change in mid_close
        ret = pre_release["mid_close"].diff().dropna()
        pre_stdev = float(ret.std())
        if pre_stdev <= 0:
            continue

        # Spike extremes between release and decision (inclusive of decision bar)
        spike_window = day_df[(day_df.index >= release_ts) & (day_df.index <= decision_ts)]
        if len(spike_window) < cfg.decision_bars_after:
            continue

        decision_bar = day_df.loc[decision_ts]
        decision_close = float(decision_bar["mid_close"])
        spike_high = float(spike_window["mid_high"].max())
        spike_low = float(spike_window["mid_low"].min())

        # Move size since pre-release close, in stdev units
        move_up = (spike_high - pre_close) / pre_stdev
        move_down = (pre_close - spike_low) / pre_stdev

        direction = None
        entry = None
        sl = None
        tp = None

        # Overshoot UP → SHORT (fade back to pre_close)
        if move_up >= cfg.overshoot_stdev_threshold:
            entry = float(decision_bar["bid_close"])
            # SL = above the spike high + buffer
            sl = spike_high + cfg.sl_buffer_stdev * pre_stdev
            tp = pre_close
            if entry - tp <= 0 or sl - entry <= 0:
                continue
            direction = "short"

        elif move_down >= cfg.overshoot_stdev_threshold:
            entry = float(decision_bar["ask_close"])
            sl = spike_low - cfg.sl_buffer_stdev * pre_stdev
            tp = pre_close
            if tp - entry <= 0 or entry - sl <= 0:
                continue
            direction = "long"

        if direction is None:
            continue

        signals.append(Signal(
            entry_bar_ts=decision_ts,
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            max_bars=cfg.max_bars,
            metadata={
                "strategy": "EIA_WED_MR",
                "pre_close": round(pre_close, 4),
                "pre_stdev": round(pre_stdev, 4),
                "move_up_z": round(move_up, 3),
                "move_down_z": round(move_down, 3),
                "spike_high": round(spike_high, 4),
                "spike_low": round(spike_low, 4),
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

    cfg = EIAConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)
    result = run_strategy(fn, (d1, h1, m3))
    print_report("005 — EIA Wed Mean-Reversion (release=14:30 UTC, z=2.0)", result)

    la = lookahead_audit(fn, (d1, h1, m3))
    rb = random_baseline((d1, h1, m3), n_trades=max(result.total_trades, 200))
    trusted = print_safeguard_report("005 — EIA Wed MR", la, rb)
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED'}")


if __name__ == "__main__":
    main()
