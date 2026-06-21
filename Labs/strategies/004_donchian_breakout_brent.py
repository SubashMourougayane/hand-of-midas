"""004 — Donchian Channel Breakout on Brent (intraday H1).

Source: Richard Donchian (1949) channel system; Turtle Traders (Dennis &
Eckhardt, 1983) codified the 20/10-day variant. Famous trend-following
template.

Concept (intraday adaptation):
- Compute trailing N-bar HIGH and trailing M-bar LOW on H1.
- LONG when current bar breaks above N-bar high (excludes current bar).
- SHORT when current bar breaks below N-bar low.
- Exit when price breaks the OPPOSITE M-bar channel (Turtle 10-day exit).
- Adapted for intraday: N=20 H1 bars (~ 20 hours), M=10 H1 bars.

Why it COULD work on Brent:
- Brent has macro news flow (OPEC, geopolitics, EIA) that creates
  multi-hour trends. Donchian rides those.
- Trend-following is the OPPOSITE of mean reversion (#002). If MR loses
  badly, trend should win — IF the time horizon matches the trend.

Why it might NOT work on Brent intraday:
- 20-hour breakouts are slow; Brent often retraces back into the channel.
- Large SLs on long trends → small accounts can't ride them through DD.

Live-reproducibility:
- 20-bar high uses bars [i-20, i-1] — strictly past, excluding current.
- Entry on bar i if bar.mid_close > 20-bar high.
- Exit logic: SL = recent 10-bar opposite extreme; TP = un-hittable
  (we use max_bars timed exit to keep it simple — Turtle's true exit
  is more complex).
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
class DonchianConfig:
    breakout_lookback: int = 20  # H1 bars for breakout high/low
    sl_lookback: int = 10  # H1 bars for SL placement
    max_bars: int = 240  # M3 bars (= 12 hours)
    one_trade_per_day: bool = True


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: DonchianConfig | None = None,
) -> list[Signal]:
    if cfg is None:
        cfg = DonchianConfig()

    signals: list[Signal] = []

    # Compute H1 trailing channels using shift(1) so the channel uses bars
    # i-N..i-1 (excludes current bar i).
    h1_high = h1["mid_high"].rolling(cfg.breakout_lookback).max().shift(1)
    h1_low = h1["mid_low"].rolling(cfg.breakout_lookback).min().shift(1)
    h1_sl_high = h1["mid_high"].rolling(cfg.sl_lookback).max().shift(1)
    h1_sl_low = h1["mid_low"].rolling(cfg.sl_lookback).min().shift(1)

    # Track per-day fired flag
    last_fire_day = None

    for ts, bar in h1.iterrows():
        if cfg.one_trade_per_day:
            day = ts.normalize()
            if last_fire_day == day:
                continue

        breakout_high = h1_high.loc[ts]
        breakout_low = h1_low.loc[ts]
        sl_high = h1_sl_high.loc[ts]
        sl_low = h1_sl_low.loc[ts]
        if pd.isna(breakout_high) or pd.isna(breakout_low):
            continue

        h_close = float(bar["mid_close"])
        h_high = float(bar["mid_high"])
        h_low = float(bar["mid_low"])

        direction = None
        entry_price = None
        sl = None

        if h_high > breakout_high and h_close > breakout_high:
            direction = "long"
            entry_price = float(bar["ask_close"])
            sl = float(sl_low)
        elif h_low < breakout_low and h_close < breakout_low:
            direction = "short"
            entry_price = float(bar["bid_close"])
            sl = float(sl_high)

        if direction is None:
            continue

        # Need to find the corresponding M3 bar to enter on. Live, the
        # trade fires the moment the H1 bar CLOSES — so entry_bar_ts on
        # M3 should be the FIRST M3 bar at-or-after the H1 bar close.
        h1_close_ts = ts + pd.Timedelta(hours=1)
        m3_after_close = m3[m3.index >= h1_close_ts]
        if m3_after_close.empty:
            continue
        entry_bar_ts = m3_after_close.index[0]

        risk = abs(entry_price - sl)
        if risk <= 0:
            continue

        # TP at 2R for trend-following — modest reward target
        if direction == "long":
            tp = entry_price + 2.0 * risk
        else:
            tp = entry_price - 2.0 * risk

        signals.append(Signal(
            entry_bar_ts=entry_bar_ts,
            direction=direction,
            entry=entry_price,
            sl=sl,
            tp=tp,
            max_bars=cfg.max_bars,
            metadata={
                "strategy": "DONCHIAN",
                "breakout_high": float(breakout_high),
                "breakout_low": float(breakout_low),
                "h1_bar_ts": ts.isoformat(),
            },
        ))
        if cfg.one_trade_per_day:
            last_fire_day = ts.normalize()

    return sorted(signals, key=lambda s: s.entry_bar_ts)


def main() -> None:
    from Labs.shared.data import get_brent
    from Labs.shared.runner import run_strategy, print_report
    from Labs.shared.safeguards import (
        lookahead_audit, random_baseline, print_safeguard_report,
    )

    print("Loading dev data via sealed gateway...")
    d1, h1, m3 = get_brent()
    print(f"  M3={len(m3):,}  H1={len(h1):,}")

    cfg = DonchianConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)
    result = run_strategy(fn, (d1, h1, m3))
    print_report("004 — Donchian Breakout (20-bar/10-bar H1, RR=2)", result)

    la = lookahead_audit(fn, (d1, h1, m3))
    rb = random_baseline((d1, h1, m3), n_trades=max(result.total_trades, 200))
    trusted = print_safeguard_report("004 — Donchian", la, rb)
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED'}")


if __name__ == "__main__":
    main()
