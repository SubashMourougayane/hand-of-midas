"""Safeguard 5 — Random-strategy baseline.

If you replace your strategy's signal generator with random entries (matched
signal frequency) and the BT engine still produces a positive P&L, the BT
engine has positive bias — likely a lookahead bug or fill model error.

A correct BT on a non-edge-having instrument should produce small negative
P&L on random entries (because of slippage + commission).

This safeguard fires whenever a phase produces "too good" results. The
sanity test is:

    expected: random_pnl < 0  (always)
    if random_pnl >= 0: BT engine is broken, NOT the strategy

Phase 0 status: framework only. The BT engine doesn't exist in R&D yet
(Phase 1 will build a clean one). When it does, this test gets wired up.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd
import pytest


@dataclass
class RandomSignal:
    signal_ts: pd.Timestamp
    direction: str   # "long" or "short"
    entry: float
    sl: float
    tp: float
    risk: float


def generate_random_signals(
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    *,
    target_count: int,
    avg_risk: float,
    avg_reward_to_risk: float,
    seed: int = 42,
) -> list[RandomSignal]:
    """Generate `target_count` random long/short signals using only data
    available at each signal's timestamp.

    The signals have realistic-looking SL/TP relative to the bar range, but
    the entry timing is uniformly random across the H1 bar set.

    Args:
        h1: full H1 DataFrame.
        m3: full M3 DataFrame.
        target_count: how many signals to generate (matching the real
            strategy's signal count keeps the comparison fair).
        avg_risk: average risk distance in price units.
        avg_reward_to_risk: average reward-to-risk ratio.
        seed: deterministic randomness.

    Returns:
        list of RandomSignal — same shape as a real strategy's signal list,
        ready to be fed into the BT engine.
    """
    rng = random.Random(seed)
    if len(h1) < 10:
        return []

    signals = []
    for _ in range(target_count):
        # Pick a random H1 bar (skip the first 10 to allow for indicators).
        bar_idx = rng.randint(10, len(h1) - 1)
        bar_ts = h1.index[bar_idx]
        bar = h1.iloc[bar_idx]

        # Find the next M3 bar after this H1 bar's open.
        m3_after = m3[m3.index > bar_ts]
        if len(m3_after) == 0:
            continue
        signal_ts = m3_after.index[0]
        signal_bar = m3_after.iloc[0]

        direction = rng.choice(["long", "short"])
        entry = float(signal_bar["mid_close"])
        risk = avg_risk * rng.uniform(0.7, 1.3)
        reward = risk * avg_reward_to_risk * rng.uniform(0.8, 1.2)

        if direction == "long":
            sl = entry - risk
            tp = entry + reward
        else:
            sl = entry + risk
            tp = entry - reward

        signals.append(RandomSignal(
            signal_ts=signal_ts,
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            risk=risk,
        ))

    return signals


def assert_random_baseline_loses(
    bt_engine: Callable[[list, pd.DataFrame, pd.DataFrame], dict],
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    *,
    real_signal_count: int,
    avg_risk: float,
    avg_reward_to_risk: float,
    bt_engine_name: str = "<bt_engine>",
) -> None:
    """Run the BT engine with random signals. Assert P&L is negative.

    A correct BT engine should never make money on random entries — slippage
    and commission make the expected return negative.

    If random_pnl >= 0, the BT engine has positive bias. This is the test
    that catches the kind of lookahead the assistant introduced today
    (intra-bar M3 search inside still-forming H1 bar).

    Args:
        bt_engine: function that takes (signals, h1, m3) and returns a dict
            with at least key 'total_pnl'.
        h1, m3: data to backtest on.
        real_signal_count: how many signals the real strategy produced. The
            random baseline matches this count for a fair comparison.
        avg_risk, avg_reward_to_risk: from the real strategy's distribution,
            so the random baseline trades have similar size.
        bt_engine_name: for the assertion message.

    Raises:
        AssertionError if random P&L >= 0.
    """
    random_signals = generate_random_signals(
        h1, m3,
        target_count=real_signal_count,
        avg_risk=avg_risk,
        avg_reward_to_risk=avg_reward_to_risk,
    )

    if len(random_signals) < real_signal_count * 0.5:
        pytest.skip(
            f"Random baseline could not generate enough signals "
            f"({len(random_signals)}/{real_signal_count})."
        )

    result = bt_engine(random_signals, h1, m3)
    random_pnl = result["total_pnl"]

    assert random_pnl < 0, (
        f"\n{bt_engine_name}: RANDOM BASELINE PRODUCED PROFIT.\n"
        f"  Random P&L: ${random_pnl:,.2f}\n"
        f"  This means the BT engine has POSITIVE BIAS.\n"
        f"  A correct BT on random entries should always lose money to "
        f"slippage + commission.\n"
        f"  Likely causes:\n"
        f"    1. Lookahead bug — fills / exits use future data\n"
        f"    2. Fill model error — entries fill too favorably\n"
        f"    3. Cost model missing — slippage / commission not applied\n"
        f"  DO NOT trust any positive strategy result from this BT engine "
        f"until this test passes."
    )


# ── Smoke test for the harness itself ─────────────────────────────────────


def test_harness_self_check_with_lossy_engine():
    """A correctly-pessimistic mock BT should pass."""
    def lossy_engine(signals, h1, m3):
        # Always lose ~$1 per trade — like real slippage + commission.
        return {"total_pnl": -len(signals) * 1.0}

    idx = pd.date_range("2020-01-01", periods=300, freq="h", tz="UTC")
    h1 = pd.DataFrame({
        "mid_open": [80.0] * 300,
        "mid_high": [80.5] * 300,
        "mid_low": [79.5] * 300,
        "mid_close": [80.0] * 300,
    }, index=idx)
    m3_idx = pd.date_range("2020-01-01", periods=10000, freq="3min", tz="UTC")
    m3 = pd.DataFrame({"mid_close": [80.0] * 10000}, index=m3_idx)

    assert_random_baseline_loses(
        lossy_engine, h1, m3,
        real_signal_count=50,
        avg_risk=0.5,
        avg_reward_to_risk=1.0,
        bt_engine_name="lossy_engine_mock",
    )


def test_harness_self_check_catches_biased_engine():
    """A buggy BT that pays $1 per trade should fail the test."""
    def biased_engine(signals, h1, m3):
        # Bug: always pays profit. Like a BT with lookahead.
        return {"total_pnl": +len(signals) * 1.0}

    idx = pd.date_range("2020-01-01", periods=300, freq="h", tz="UTC")
    h1 = pd.DataFrame({
        "mid_open": [80.0] * 300,
        "mid_high": [80.5] * 300,
        "mid_low": [79.5] * 300,
        "mid_close": [80.0] * 300,
    }, index=idx)
    m3_idx = pd.date_range("2020-01-01", periods=10000, freq="3min", tz="UTC")
    m3 = pd.DataFrame({"mid_close": [80.0] * 10000}, index=m3_idx)

    with pytest.raises(AssertionError, match="RANDOM BASELINE PRODUCED PROFIT"):
        assert_random_baseline_loses(
            biased_engine, h1, m3,
            real_signal_count=50,
            avg_risk=0.5,
            avg_reward_to_risk=1.0,
            bt_engine_name="biased_engine_mock",
        )
