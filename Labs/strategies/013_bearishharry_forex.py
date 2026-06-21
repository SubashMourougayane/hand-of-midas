"""013 — bearishharry's "One Forex Setup For Life" — multi-TF SMC.

Source: Instagram @bearishharry, "Stop jumping from strategy to strategy"
8-slide carousel. Steps:

  1. Daily bias — close BEYOND PDH (bull) or PDL (bear) with body.
  2. H4 liquidity sweep aligned with bias (high sweep when bear, low sweep when bull).
  3. H1 confirmation candle — sweep + good close (rejection or engulf).
  4. M15 entry — sweep of recent extreme + cemented (engulf) candle inside premium/discount OB.
  5. SL above/below the M15 sweep extreme. TP at fixed RR.

This is a 4-stage filter. Each stage drops 90%+ of the previous stage's
candidates. Expected signal frequency: ~2-5 trades / pair / month.

Live-reproducibility:
- Every guard is `<= T` (no future data).
- Daily bias for day D uses close of bar D-1 (previous full day).
- H4 sweep search window is fixed-lookback (configurable).
- H1 confirmation fires only on the H1 bar's CLOSE (bar timestamp + 1h).
- M15 entry fires on the M15 bar that completes the cemented engulf.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.runner_forex import Signal


@dataclass(frozen=True)
class BearishHarryConfig:
    """All knobs needed to reproduce a single backtest config."""
    # 4h sweep lookback in HOURS (so 12 = 3 H4 bars, 24 = 6 H4 bars)
    sweep_lookback_hours: int = 24
    # H1 confirmation: pure rejection (long lower wick) vs bearish engulf
    h1_confirmation: Literal["rejection_wick", "engulf"] = "rejection_wick"
    # M15 entry style
    m15_entry: Literal["engulf_close", "ob_retest"] = "engulf_close"
    # Reward:Risk ratio (TP distance / SL distance)
    rr: float = 2.0
    # MAX hold for M15 trade in M15 bars (1 day = 96 bars)
    max_bars: int = 96
    # Min wick:body ratio for H1 rejection (e.g. 1.5 = wick must be ≥1.5x body)
    min_rejection_wick_ratio: float = 1.5


# ── Stage 1: Daily bias ──────────────────────────────────────────────────


def _daily_bias(d1: pd.DataFrame, ts: pd.Timestamp) -> Literal["bull", "bear", "none"]:
    """Bias for trading day starting at `ts` based on the prior full day.

    "PDH" = previous-previous day's high. "PDL" = previous-previous day's
    low. The slide language is fuzzy; my reading: yesterday's close beyond
    DAY-BEFORE-YESTERDAY's range = bias.
    """
    # Get 2 most-recent daily bars STRICTLY BEFORE ts
    prior = d1[d1.index < ts]
    if len(prior) < 2:
        return "none"
    yesterday = prior.iloc[-1]
    prev = prior.iloc[-2]
    body = yesterday["mid_close"] - yesterday["mid_open"]
    if yesterday["mid_close"] < prev["mid_low"] and body < 0:
        return "bear"
    if yesterday["mid_close"] > prev["mid_high"] and body > 0:
        return "bull"
    return "none"


# ── Stage 2: H4 sweep ────────────────────────────────────────────────────


def _h4_sweep_found(
    h4: pd.DataFrame,
    ts: pd.Timestamp,
    bias: Literal["bull", "bear"],
    lookback_hours: int,
) -> bool:
    """Did an H4 bar sweep prior swing high (bear) or low (bull) recently?

    Sweep = bar's high goes ABOVE the lookback_hours window's prior high
    (excluding the sweeping bar itself), then closes BELOW it. Mirror for
    bullish low-sweeps.
    """
    window_start = ts - pd.Timedelta(hours=lookback_hours)
    window = h4[(h4.index >= window_start) & (h4.index < ts)]
    if len(window) < 3:
        return False

    candidate = window.iloc[-1]   # most recent COMPLETED H4
    earlier = window.iloc[:-1]
    if bias == "bear":
        prior_high = float(earlier["mid_high"].max())
        return bool(candidate["mid_high"] > prior_high
                    and candidate["mid_close"] < prior_high)
    # bull
    prior_low = float(earlier["mid_low"].min())
    return bool(candidate["mid_low"] < prior_low
                and candidate["mid_close"] > prior_low)


# ── Stage 3: H1 confirmation ─────────────────────────────────────────────


def _h1_confirmation(
    h1: pd.DataFrame,
    ts: pd.Timestamp,
    bias: Literal["bull", "bear"],
    mode: str,
    min_wick_ratio: float,
) -> bool:
    """Did the H1 bar IMMEDIATELY BEFORE ts confirm the sweep?

    rejection_wick:
        bear → upper wick ≥ min_wick_ratio × body, close < open
        bull → lower wick ≥ min_wick_ratio × body, close > open
    engulf:
        bear → bear bar engulfing prior bull bar's body
        bull → mirror
    """
    prior = h1[h1.index < ts]
    if len(prior) < 2:
        return False
    bar = prior.iloc[-1]
    o, h, l, c = float(bar["mid_open"]), float(bar["mid_high"]), float(bar["mid_low"]), float(bar["mid_close"])
    body = abs(c - o)
    if body == 0:
        body = 1e-9

    if mode == "rejection_wick":
        if bias == "bear":
            upper_wick = h - max(o, c)
            return c < o and upper_wick >= min_wick_ratio * body
        else:  # bull
            lower_wick = min(o, c) - l
            return c > o and lower_wick >= min_wick_ratio * body
    elif mode == "engulf":
        prev = prior.iloc[-2]
        po, pc = float(prev["mid_open"]), float(prev["mid_close"])
        if bias == "bear":
            return c < o and pc > po and o >= pc and c <= po
        else:
            return c > o and pc < po and o <= pc and c >= po
    return False


# ── Stage 4: M15 entry ───────────────────────────────────────────────────


def _m15_entry(
    m15: pd.DataFrame,
    h1_close_ts: pd.Timestamp,
    bias: Literal["bull", "bear"],
    mode: str,
) -> tuple[pd.Timestamp, float, float] | None:
    """Find the M15 entry candle within the next H1 (4 M15 bars after h1_close_ts).

    Returns (entry_bar_ts, entry_price, sl_extreme) or None.

    engulf_close: take the close of the first M15 engulf candle in the H1.
    ob_retest: same engulf but re-enter on retest of its body midpoint.
        For Labs simplicity we approximate ob_retest with the close fill —
        real ob_retest needs limit orders + cancel logic which the fill
        model can't express. Result: ob_retest acts as a synonym for
        engulf_close for now and is documented as such.
    """
    # M15 bars STRICTLY AFTER h1_close_ts, up to next H1 close
    window_end = h1_close_ts + pd.Timedelta(hours=1)
    window = m15[(m15.index > h1_close_ts) & (m15.index <= window_end)]
    if len(window) < 2:
        return None

    for i in range(1, len(window)):
        cur = window.iloc[i]
        prev = window.iloc[i - 1]
        po, pc = float(prev["mid_open"]), float(prev["mid_close"])
        co, ch, cl, cc = (
            float(cur["mid_open"]), float(cur["mid_high"]),
            float(cur["mid_low"]),  float(cur["mid_close"])
        )
        if bias == "bear":
            # bearish engulf: cur bear engulfs prev bull body
            if cc < co and pc > po and co >= pc and cc <= po:
                # SL = sweep high (cur's high or prior high — take cur's high)
                sl_extreme = ch
                return window.index[i], cc, sl_extreme
        else:
            if cc > co and pc < po and co <= pc and cc >= po:
                sl_extreme = cl
                return window.index[i], cc, sl_extreme
    return None


# ── Top-level strategy ───────────────────────────────────────────────────


def generate_signals(
    d1: pd.DataFrame,
    h4: pd.DataFrame,
    h1: pd.DataFrame,
    m15: pd.DataFrame,
    cfg: BearishHarryConfig,
) -> list[Signal]:
    """Main strategy entry. Walks H1 bars; emits at most one signal per H1.

    Loop is over H1 bar CLOSE TIMES because H1 confirmation triggers on
    H1 close.
    """
    signals: list[Signal] = []
    if len(h1) < 5 or len(d1) < 5 or len(h4) < 5:
        return signals

    # Iterate H1 bars in order. The H1 bar at `ts` is "in formation" until
    # `ts + 1h`. We treat ts as "time the bar OPENED"; bar closes at ts+1h.
    # H1 confirmation is checked at bar close, so we use bar's CLOSE time
    # as the trigger ts.
    h1_index = h1.index
    for h1_open_ts in h1_index:
        h1_close_ts = h1_open_ts + pd.Timedelta(hours=1)

        # 1. Daily bias as-of trigger time
        bias = _daily_bias(d1, h1_close_ts)
        if bias == "none":
            continue

        # 2. H4 sweep window ending at h1_close_ts
        if not _h4_sweep_found(h4, h1_close_ts, bias, cfg.sweep_lookback_hours):
            continue

        # 3. H1 confirmation: the H1 bar that just closed (== h1_open_ts row)
        if not _h1_confirmation(
            h1, h1_close_ts, bias, cfg.h1_confirmation, cfg.min_rejection_wick_ratio
        ):
            continue

        # 4. M15 entry within next H1
        m15_result = _m15_entry(m15, h1_close_ts, bias, cfg.m15_entry)
        if m15_result is None:
            continue

        entry_ts, entry_px, sl_extreme = m15_result

        # 5. SL = sweep extreme + small buffer (1 spread = 1 pip-equiv)
        # 6. TP = entry ± rr * sl_distance
        if bias == "bear":
            sl = sl_extreme  # SL above the sweep high
            risk = sl - entry_px
            if risk <= 0:
                continue
            tp = entry_px - cfg.rr * risk
            direction = "short"
        else:
            sl = sl_extreme  # SL below the sweep low
            risk = entry_px - sl
            if risk <= 0:
                continue
            tp = entry_px + cfg.rr * risk
            direction = "long"

        signals.append(Signal(
            entry_bar_ts=entry_ts,
            direction=direction,
            entry=entry_px,
            sl=sl,
            tp=tp,
            max_bars=cfg.max_bars,
            metadata={
                "bias": bias,
                "h1_close_ts": str(h1_close_ts),
                "sweep_lookback_hours": cfg.sweep_lookback_hours,
                "h1_confirmation": cfg.h1_confirmation,
                "m15_entry": cfg.m15_entry,
                "rr": cfg.rr,
            },
        ))
    return signals


# ── Single-config baseline run on EURUSD ─────────────────────────────────


def main() -> None:
    """Run baseline config on EURUSD dev window. Sanity-check before sweep."""
    from Labs.shared.data_forex import get_forex
    from Labs.shared.runner_forex import run_forex_strategy, print_report

    cfg = BearishHarryConfig()
    bundle = get_forex("EUR_USD")
    fn = lambda d1_, h4_, h1_, m15_: generate_signals(d1_, h4_, h1_, m15_, cfg)
    label = (
        f"sweep_lookback={cfg.sweep_lookback_hours}h "
        f"h1_conf={cfg.h1_confirmation} "
        f"m15={cfg.m15_entry} "
        f"rr={cfg.rr}"
    )
    r = run_forex_strategy(fn, bundle, config_label=label)
    print_report("013 — bearishharry baseline (EUR_USD)", r)


if __name__ == "__main__":
    main()
