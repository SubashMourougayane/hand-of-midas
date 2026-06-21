"""Per-strategy safeguards.

Every Labs strategy run must pass these BEFORE its results are trusted:

1. **Lookahead audit.** For 10 random sample signals, re-run the strategy
   with data truncated at the signal's entry_bar_ts. Assert the same
   signal appears in the truncated run. If not, the strategy is reading
   future data.

2. **Random-baseline check.** Generate fake signals at random timestamps
   matching the strategy's signal frequency, run them through the same
   fill model. If random > 0 P&L → fill model is biased; the strategy's
   result is meaningless until the bias is found and fixed.

A strategy result is REPORTED as "TRUSTED" only if both safeguards pass.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from Labs.shared.fill_model import execute_trade
from Labs.shared.runner import Signal


@dataclass
class LookaheadVerdict:
    passed: bool
    sample_size: int
    mismatches: int
    detail: str


def lookahead_audit(
    strategy_fn: Callable,
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    sample_size: int = 10,
    seed: int = 42,
) -> LookaheadVerdict:
    """Re-run strategy on truncated data and check signals are stable.

    For each of `sample_size` randomly-chosen signals from the full run:
        - truncate D1, H1, M3 to bars with index <= signal.entry_bar_ts
        - re-run strategy on the truncation
        - assert the original signal still appears in the truncated output
          (matching by entry_bar_ts + direction)

    If the truncated run produces a DIFFERENT signal at the same ts, OR
    drops the signal entirely, the strategy is using future data.
    """
    d1, h1, m3 = data
    full_signals = strategy_fn(d1, h1, m3)
    if not full_signals:
        return LookaheadVerdict(
            passed=True, sample_size=0, mismatches=0,
            detail="strategy produced 0 signals; nothing to audit",
        )

    rng = random.Random(seed)
    sample = rng.sample(full_signals, min(sample_size, len(full_signals)))
    mismatches = 0
    detail_lines = []

    for sig in sample:
        T = sig.entry_bar_ts
        d1_t = d1[d1.index <= T]
        h1_t = h1[h1.index <= T]
        m3_t = m3[m3.index <= T]
        truncated = strategy_fn(d1_t, h1_t, m3_t)
        # Find a matching signal in truncated by ts + direction
        match = next(
            (s for s in truncated
             if s.entry_bar_ts == T and s.direction == sig.direction),
            None
        )
        if match is None:
            mismatches += 1
            detail_lines.append(
                f"  T={T} dir={sig.direction}: truncated run did NOT produce this signal"
            )
        elif (
            abs(match.entry - sig.entry) > 1e-6
            or abs(match.sl - sig.sl) > 1e-6
            or abs(match.tp - sig.tp) > 1e-6
        ):
            mismatches += 1
            detail_lines.append(
                f"  T={T} dir={sig.direction}: signal levels differ between full and truncated"
            )

    detail = ("PASS" if mismatches == 0 else f"FAIL — {mismatches} mismatch(es):\n" + "\n".join(detail_lines))
    return LookaheadVerdict(
        passed=mismatches == 0,
        sample_size=len(sample),
        mismatches=mismatches,
        detail=detail,
    )


@dataclass
class RandomBaselineVerdict:
    passed: bool
    random_pnl: float
    random_trades: int
    detail: str


_MIN_RANDOM_BASELINE_TRADES = 2000


def random_baseline(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    n_trades: int,
    seed: int = 42,
    risk_units: float | None = None,
    risk_bar_ranges: float = 3.0,
    reward_to_risk: float = 1.0,
    max_bars: int = 80,
) -> RandomBaselineVerdict:
    # Below ~2000 trades, sample variance dominates the slippage signal
    # and we get false positives (random run looks profitable purely by
    # sampling luck). Force a minimum.
    n_trades = max(n_trades, _MIN_RANDOM_BASELINE_TRADES)
    """Run `n_trades` random LONG/SHORT entries through the fill model.

    Random entries:
        - random M3 bar (uniformly distributed across data)
        - random direction (50/50)
        - SL/TP set symmetrically around the bar's mid_close

    Risk sizing:
        If `risk_units` is None (default), SL/TP are placed at
        `risk_bar_ranges × median_bar_range` from entry. This auto-scales
        across instruments — Brent (median range $0.07) gets ~$0.21 SL,
        Gold (median range $0.76) gets ~$2.28 SL — both far enough away
        that a typical bar can't hit both SL and TP intra-bar (which
        would mask slippage drag).

        If `risk_units` is given, that absolute value is used. ONLY pass
        explicitly when you know the instrument's bar range.

    A correct fill model returns NEGATIVE P&L on random entries because
    of slippage on SL fills. If random_pnl >= 0, the fill model is biased
    OR the SL/TP are too tight and getting filled inside one bar.
    """
    d1, h1, m3 = data
    rng = random.Random(seed)
    if len(m3) < n_trades + max_bars + 10:
        return RandomBaselineVerdict(
            passed=False, random_pnl=0.0, random_trades=0,
            detail=f"data too short for {n_trades} random trades + {max_bars} bars hold",
        )

    if risk_units is None:
        median_bar_range = float((m3["mid_high"] - m3["mid_low"]).median())
        risk_units = risk_bar_ranges * median_bar_range

    valid_range = len(m3) - max_bars - 5
    pnls = []
    for _ in range(n_trades):
        bar_idx = rng.randint(5, valid_range)
        bar = m3.iloc[bar_idx]
        direction = rng.choice(["long", "short"])
        mid = float(bar["mid_close"])
        if direction == "long":
            entry = mid
            sl = mid - risk_units
            tp = mid + risk_units * reward_to_risk
        else:
            entry = mid
            sl = mid + risk_units
            tp = mid - risk_units * reward_to_risk
        result = execute_trade(m3, bar_idx, entry, sl, tp, direction, max_bars)
        if result:
            pnls.append(result.pnl_per_unit)

    total = sum(pnls)
    n = len(pnls)
    return RandomBaselineVerdict(
        passed=total < 0,  # random entries should LOSE (slippage drag)
        random_pnl=round(total, 4),
        random_trades=n,
        detail=(
            f"{n} random trades; sum P&L per unit = {total:.4f}; "
            f"expected NEGATIVE due to slippage."
        ),
    )


def print_safeguard_report(
    name: str,
    la: LookaheadVerdict,
    rb: RandomBaselineVerdict,
) -> bool:
    """Pretty-print safeguard results. Returns True iff both passed."""
    print()
    print(f"  Safeguards for: {name}")
    la_label = "PASS" if la.passed else "FAIL"
    rb_label = "PASS" if rb.passed else "FAIL"
    print(f"    Lookahead audit       : {la_label}  ({la.sample_size} samples, {la.mismatches} mismatches)")
    print(f"    Random baseline check : {rb_label}  (PnL/unit = {rb.random_pnl}, {rb.random_trades} trades)")
    if not la.passed:
        print(f"      LA detail: {la.detail}")
    if not rb.passed:
        print(f"      RB detail: {rb.detail}")
    return la.passed and rb.passed
