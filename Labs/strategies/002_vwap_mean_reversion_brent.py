"""002 — VWAP Mean Reversion on Brent.

Source: institutional execution literature; many publicly-described
implementations, e.g. Hull-Moving-Average + VWAP combos in QuantStart,
Robust Cmdty Trading "VWAP fade" templates. The concept is older —
volume-weighted average price as an intraday "fair value" anchor that
extended price tends to revert toward.

Concept:
- Compute intraday VWAP starting at the session anchor (resets each day).
- When price extends >= K × intraday-rolling-stdev away from VWAP, fade
  it back to VWAP.
- LONG when price is K stdevs BELOW VWAP, target VWAP, SL = entry minus
  M × stdev (M > K so the SL is wider than the entry trigger).
- SHORT when K stdevs ABOVE.

Why it COULD work on Brent:
- Brent has institutional flow that uses VWAP for execution benchmarks.
  Extensions tend to invite mean-reversion flows.
- Mean-reversion thrives on choppy / range-bound days, which Brent has
  many of.

Why it might NOT work on Brent:
- On trending days (announcements, OPEC headlines, geopolitical),
  extensions just go further. SL gets hit before VWAP touches.
- The "K stdevs" threshold is parameter-sensitive.

Live-reproducibility:
- VWAP at time T uses ONLY bars [session_start, T]. Including bar T's
  own typical price + volume in the running sum is fine — that bar is
  closed by definition at decision time.
- Stdev computed on the same window.
- Entry on first bar where (mid_close - vwap) / stdev exceeds threshold.

Parameters (start at literature defaults — DO NOT optimize):
- session_start_hour_utc: 0 (24-hr instrument; resets at UTC midnight)
- entry_stdev_threshold: 2.0 (price > 2σ from VWAP triggers fade)
- sl_stdev_multiplier: 3.0 (SL at 3σ — gives the trade room)
- min_warmup_bars: 30 (don't trade before 30 M3 bars of VWAP data exist)
- max_bars: 80
- one_trade_per_extreme: True (don't re-fire on same extension)
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
class VWAPConfig:
    session_start_hour_utc: int = 0  # UTC midnight reset
    entry_stdev_threshold: float = 2.0
    sl_stdev_multiplier: float = 3.0
    min_warmup_bars: int = 30
    max_bars: int = 80
    one_trade_per_extreme: bool = True


def _compute_vwap_and_stdev(
    bars: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Cumulative VWAP and rolling stdev of (typical_price - VWAP).

    typical_price = (mid_high + mid_low + mid_close) / 3
    VWAP[i] = sum(typical * volume)[0..i] / sum(volume)[0..i]
    stdev[i] = std of (typical - vwap) over [0..i]

    Live-safe: at any index i, the value uses bars 0..i only. Bar i is
    the bar that just closed; live can compute identical numbers.
    """
    tp = (bars["mid_high"] + bars["mid_low"] + bars["mid_close"]) / 3.0
    if "volume" in bars.columns:
        vol = bars["volume"].astype(float)
    else:
        vol = pd.Series(1.0, index=bars.index)

    cum_pv = (tp * vol).cumsum()
    cum_v = vol.cumsum().replace(0.0, np.nan)
    vwap = cum_pv / cum_v

    deviation = tp - vwap
    # Expanding stdev — uses only data 0..i
    stdev = deviation.expanding(min_periods=2).std(ddof=0)
    return vwap, stdev


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: VWAPConfig | None = None,
) -> list[Signal]:
    if cfg is None:
        cfg = VWAPConfig()

    signals: list[Signal] = []

    for date, day_df in m3.groupby(m3.index.normalize()):
        # Need MORE than min_warmup_bars so at least one bar exists to trade.
        # Was previously `+ 5` which created a 5-bar future-data dependency
        # (truncated runs at bar #min_warmup_bars+1 would skip the day even
        # though the bar in question is fully present).
        if len(day_df) <= cfg.min_warmup_bars:
            continue

        vwap, stdev = _compute_vwap_and_stdev(day_df)

        long_fired = False
        short_fired = False

        for i, (ts, bar) in enumerate(day_df.iterrows()):
            if i < cfg.min_warmup_bars:
                continue
            v = vwap.iat[i]
            s = stdev.iat[i]
            if not np.isfinite(v) or not np.isfinite(s) or s <= 0:
                continue

            mid_close = float(bar["mid_close"])
            z = (mid_close - v) / s

            # SHORT — price too far ABOVE VWAP, fade back down
            if not short_fired and z >= cfg.entry_stdev_threshold:
                entry = float(bar["bid_close"])
                sl = entry + cfg.sl_stdev_multiplier * s - (cfg.entry_stdev_threshold * s)
                tp = float(v)  # target is VWAP
                if entry - tp <= 0 or sl - entry <= 0:
                    short_fired = True
                    continue
                signals.append(Signal(
                    entry_bar_ts=ts,
                    direction="short",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    max_bars=cfg.max_bars,
                    metadata={
                        "strategy": "VWAP_MR",
                        "z": round(z, 3),
                        "vwap": round(float(v), 4),
                        "stdev": round(float(s), 4),
                    },
                ))
                short_fired = True
                if cfg.one_trade_per_extreme:
                    # Don't fire LONG on the same day if SHORT already fired
                    # (avoid intraday whipsaw). Set both flags.
                    long_fired = True
                continue

            # LONG — price too far BELOW VWAP
            if not long_fired and z <= -cfg.entry_stdev_threshold:
                entry = float(bar["ask_close"])
                sl = entry - cfg.sl_stdev_multiplier * s + (cfg.entry_stdev_threshold * s)
                tp = float(v)
                if tp - entry <= 0 or entry - sl <= 0:
                    long_fired = True
                    continue
                signals.append(Signal(
                    entry_bar_ts=ts,
                    direction="long",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    max_bars=cfg.max_bars,
                    metadata={
                        "strategy": "VWAP_MR",
                        "z": round(z, 3),
                        "vwap": round(float(v), 4),
                        "stdev": round(float(s), 4),
                    },
                ))
                long_fired = True
                if cfg.one_trade_per_extreme:
                    short_fired = True

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

    cfg = VWAPConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)

    print("\nRunning strategy...")
    result = run_strategy(fn, (d1, h1, m3))
    print_report("002 — VWAP Mean Reversion (z=2.0, sl_z=3.0, max=80 bars)", result)

    print("Safeguards...")
    la = lookahead_audit(fn, (d1, h1, m3))
    rb = random_baseline((d1, h1, m3), n_trades=max(result.total_trades, 200))
    trusted = print_safeguard_report("002 — VWAP MR", la, rb)
    print()
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED — investigate before reporting'}")


if __name__ == "__main__":
    main()
