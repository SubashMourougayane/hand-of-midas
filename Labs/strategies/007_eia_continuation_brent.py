"""007 — Wednesday EIA Continuation on Brent.

Sprint 2-B. Strategy #005 (mean reversion on EIA) was a clear loser
(PF 0.28). The opposite direction — buying the up-spike, selling the
down-spike — is the obvious counter-test.

Same release time, same z-threshold detection. Direction inverted.

Walk-forward: same Train/Validate split as 2-A.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.runner import Signal, run_strategy


@dataclass(frozen=True)
class EIAContinuationConfig:
    release_hour_utc: int = 14
    release_minute: int = 30
    pre_stdev_bars: int = 30
    decision_bars_after: int = 2
    overshoot_stdev_threshold: float = 2.0
    sl_buffer_stdev: float = 1.5
    rr: float = 2.0  # TP at RR × risk in CONTINUATION direction
    max_bars: int = 40


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: EIAContinuationConfig | None = None,
) -> list[Signal]:
    if cfg is None:
        cfg = EIAContinuationConfig()

    signals: list[Signal] = []

    for date, day_df in m3.groupby(m3.index.normalize()):
        if date.weekday() != 2:  # Wednesday only
            continue

        release_ts = date + pd.Timedelta(hours=cfg.release_hour_utc, minutes=cfg.release_minute)
        decision_ts = release_ts + pd.Timedelta(minutes=cfg.decision_bars_after * 3)

        if release_ts not in day_df.index or decision_ts not in day_df.index:
            continue

        pre_release = day_df[day_df.index < release_ts].tail(cfg.pre_stdev_bars)
        if len(pre_release) < cfg.pre_stdev_bars:
            continue

        pre_close = float(pre_release["mid_close"].iat[-1])
        pre_stdev = float(pre_release["mid_close"].diff().dropna().std())
        if pre_stdev <= 0:
            continue

        spike_window = day_df[(day_df.index >= release_ts) & (day_df.index <= decision_ts)]
        if len(spike_window) < cfg.decision_bars_after:
            continue

        decision_bar = day_df.loc[decision_ts]
        spike_high = float(spike_window["mid_high"].max())
        spike_low = float(spike_window["mid_low"].min())

        move_up = (spike_high - pre_close) / pre_stdev
        move_down = (pre_close - spike_low) / pre_stdev

        direction = None
        entry = None
        sl = None
        tp = None

        # CONTINUATION:
        #   Up-spike of 2σ → keep going UP → enter LONG
        #   Down-spike of 2σ → keep going DOWN → enter SHORT
        if move_up >= cfg.overshoot_stdev_threshold:
            entry = float(decision_bar["ask_close"])
            sl = pre_close  # if we revert, exit
            risk = entry - sl
            if risk <= 0:
                continue
            tp = entry + cfg.rr * risk
            direction = "long"

        elif move_down >= cfg.overshoot_stdev_threshold:
            entry = float(decision_bar["bid_close"])
            sl = pre_close
            risk = sl - entry
            if risk <= 0:
                continue
            tp = entry - cfg.rr * risk
            direction = "short"

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
                "strategy": "EIA_WED_CONT",
                "pre_close": round(pre_close, 4),
                "move_up_z": round(move_up, 3),
                "move_down_z": round(move_down, 3),
            },
        ))

    return sorted(signals, key=lambda s: s.entry_bar_ts)


def main() -> None:
    from Labs.shared.data import get_brent
    from Labs.shared.runner import print_report
    from Labs.shared.safeguards import (
        lookahead_audit, random_baseline, print_safeguard_report,
    )
    from Labs.shared.walk_forward import split_dev, describe_split

    print("Loading dev data via sealed gateway...")
    data = get_brent()
    wf = split_dev(data)
    print(describe_split(wf))

    cfg = EIAContinuationConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)

    train_r = run_strategy(fn, wf.train)
    print_report("007 — EIA Wed CONTINUATION (Train 2019-2022)", train_r)

    val_r = run_strategy(fn, wf.validate)
    print_report("007 — EIA Wed CONTINUATION (Validate 2023)", val_r)

    print(f"\n=== Walk-forward summary ===")
    print(f"  Train PF    : {train_r.profit_factor:.3f}  (P&L ${train_r.total_pnl:+,.2f})")
    print(f"  Validate PF : {val_r.profit_factor:.3f}  (P&L ${val_r.total_pnl:+,.2f})")

    if val_r.profit_factor < 1.10:
        print(f"\n  ==> NO PROMOTION  (Validate PF {val_r.profit_factor:.3f} below 1.10)")
        return

    la = lookahead_audit(fn, wf.validate)
    rb = random_baseline(wf.validate, n_trades=max(val_r.total_trades, 200))
    trusted = print_safeguard_report("007 — EIA Continuation", la, rb)
    if val_r.max_dd_pct_yearly_worst >= 50:
        print(f"  ==> NO PROMOTION  (Validate DD {val_r.max_dd_pct_yearly_worst:.1f}% ≥ 50%)")
        return
    if not trusted:
        print(f"  ==> NO PROMOTION  (safeguards failed)")
        return
    print(f"\n  ==> CANDIDATE FOR SPRINT 3")


if __name__ == "__main__":
    main()
