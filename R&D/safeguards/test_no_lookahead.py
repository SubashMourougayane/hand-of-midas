"""Safeguard 3 — Automated lookahead audit.

Every signal-generation function written in Phase 1+ must pass this test.

The test proves: for any timestamp T, the function's output for signals at
or before T must be identical whether we feed it the FULL data or only
data truncated at T.

If they differ, the function is reading future-relative-to-T data — that
is a lookahead bug.

Usage in Phase 1:

    from R&D.phase_1_detection.consolidation import detect_consolidations
    from R&D.safeguards.test_no_lookahead import assert_no_lookahead

    @pytest.mark.parametrize("instrument", ["BCO_USD"])
    def test_consolidation_no_lookahead(instrument):
        d1, h1, m3 = get_data(Phase.DEVELOPMENT, instrument)
        assert_no_lookahead(detect_consolidations, h1, m3,
                            sample_count=20, fn_name="detect_consolidations")

The test is intentionally slow (20 truncated re-runs per signal function).
Run it as part of the phase audit, not on every save.

Phase 0 status: this file is the framework. The actual signal functions
don't exist yet, so the test currently has nothing to test against. The
file lives here so the discipline is in place BEFORE Phase 1 starts
writing signal code.
"""
from __future__ import annotations

import random
from typing import Any, Callable

import pandas as pd
import pytest


# Bring in the sealed data gateway. R&D code uses ONLY this path to read data.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def assert_no_lookahead(
    fn: Callable[..., list[Any]],
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    *,
    extra_inputs: dict | None = None,
    sample_count: int = 20,
    fn_name: str = "<anonymous>",
    seed: int = 42,
) -> None:
    """Prove that `fn(h1, m3, **extra_inputs)` does not use future data.

    Strategy:
        1. Run fn with the FULL data → full_output
        2. Sample N timestamps T uniformly from h1
        3. For each T:
             a. Compute full_at_T = [s for s in full_output if s.signal_ts <= T]
             b. Run fn with data truncated at T → trunc_output
             c. trunc_at_T = [s for s in trunc_output if s.signal_ts <= T]
             d. Assert full_at_T == trunc_at_T (signal-by-signal equality)

    If full_at_T differs from trunc_at_T at any sampled T, the function
    is reading data > T at decision time T — that is lookahead.

    Args:
        fn: signal-generation function under test. Must accept (h1, m3, ...)
            and return a list of signal dataclasses with a `signal_ts` attribute.
        h1: full H1 DataFrame (UTC-indexed).
        m3: full M3 DataFrame (UTC-indexed).
        extra_inputs: additional kwargs to pass to fn (e.g. daily_bias dict).
        sample_count: how many timestamps to test. 20 is enough to catch
            most lookaheads cheaply.
        fn_name: for clearer assertion messages.
        seed: deterministic timestamp sampling for reproducibility.

    Raises:
        AssertionError if any sampled T shows divergence between full and
        truncated runs. Message names the timestamp + signal counts.
    """
    if extra_inputs is None:
        extra_inputs = {}

    # 1. Full run
    full_output = fn(h1, m3, **extra_inputs)
    full_output = sorted(full_output, key=lambda s: s.signal_ts)

    if not full_output:
        pytest.skip(f"{fn_name}: full run produced 0 signals; cannot test lookahead.")

    # 2. Pick sample timestamps. Bias toward timestamps near actual signals
    #    so we test the parts of the data that matter.
    rng = random.Random(seed)
    signal_times = [s.signal_ts for s in full_output]
    sampled = rng.sample(signal_times, min(sample_count, len(signal_times)))

    # 3. For each T: truncate, re-run, compare.
    failures = []
    for T in sampled:
        full_at_T = [s for s in full_output if s.signal_ts <= T]

        h1_trunc = h1[h1.index <= T]
        m3_trunc = m3[m3.index <= T]
        trunc_output = fn(h1_trunc, m3_trunc, **extra_inputs)
        trunc_at_T = sorted(
            [s for s in trunc_output if s.signal_ts <= T],
            key=lambda s: s.signal_ts,
        )

        # Compare. Use signal-tuple equality so the assertion is structural.
        full_keys = [_signal_key(s) for s in full_at_T]
        trunc_keys = [_signal_key(s) for s in trunc_at_T]

        if full_keys != trunc_keys:
            # Find what differs.
            full_set = set(full_keys)
            trunc_set = set(trunc_keys)
            missing_in_trunc = full_set - trunc_set
            extra_in_trunc = trunc_set - full_set
            failures.append({
                "T": T,
                "full_count": len(full_at_T),
                "trunc_count": len(trunc_at_T),
                "missing_in_trunc": list(missing_in_trunc)[:3],
                "extra_in_trunc": list(extra_in_trunc)[:3],
            })

    if failures:
        msg_lines = [
            f"\n{fn_name}: LOOKAHEAD DETECTED in {len(failures)}/{len(sampled)} sampled timestamps.",
            "",
            "When the function is given less data (only data ≤ T), it produces a",
            "different signal list at time T than it does given the full data.",
            "This means the function is reading data > T to make decisions at T.",
            "",
            "First failures:",
        ]
        for f in failures[:3]:
            msg_lines.extend([
                f"  T = {f['T']}",
                f"    full run produced {f['full_count']} signals at-or-before T",
                f"    truncated run produced {f['trunc_count']} signals at-or-before T",
                f"    missing in truncated (= present in full but not truncated): {f['missing_in_trunc']}",
                f"    extra in truncated (= present in truncated but not full): {f['extra_in_trunc']}",
                "",
            ])
        raise AssertionError("\n".join(msg_lines))


def _signal_key(s: Any) -> tuple:
    """Convert a signal-like object to a hashable comparison key.

    Falls back gracefully for different signal dataclass shapes. Required
    fields: signal_ts, direction, entry, sl, tp.
    """
    return (
        getattr(s, "signal_ts", None),
        getattr(s, "direction", None),
        round(getattr(s, "entry", 0.0), 6) if hasattr(s, "entry") else
            round(getattr(s, "entry_ref", 0.0), 6),
        round(getattr(s, "sl", 0.0), 6),
        round(getattr(s, "tp", 0.0), 6),
    )


# ── Smoke tests for the harness itself ────────────────────────────────────


def test_harness_self_check_with_clean_function():
    """Sanity check: a no-lookahead function should pass."""
    from dataclasses import dataclass

    @dataclass
    class _Sig:
        signal_ts: pd.Timestamp
        direction: str
        entry: float
        sl: float
        tp: float

    def clean_fn(h1, m3):
        # Generate a signal at every 100th H1 bar, using only that bar's data.
        out = []
        for i, (ts, row) in enumerate(h1.iterrows()):
            if i % 100 == 0:
                out.append(_Sig(ts, "long", row["mid_close"], row["mid_close"] - 1, row["mid_close"] + 1))
        return out

    # Build minimal fake data.
    idx = pd.date_range("2020-01-01", periods=300, freq="h", tz="UTC")
    h1 = pd.DataFrame({"mid_close": range(300)}, index=idx)
    m3 = pd.DataFrame({"mid_close": [0]}, index=[idx[0]])

    assert_no_lookahead(clean_fn, h1, m3, sample_count=5, fn_name="clean_fn")


def test_harness_self_check_catches_lookahead():
    """Sanity check: a deliberately lookahead-buggy function should fail."""
    from dataclasses import dataclass

    @dataclass
    class _Sig:
        signal_ts: pd.Timestamp
        direction: str
        entry: float
        sl: float
        tp: float

    def buggy_fn(h1, m3):
        # Lookahead: signal at bar i uses data from bar i+5 (future).
        out = []
        for i in range(len(h1) - 10):
            ts = h1.index[i]
            future_close = h1["mid_close"].iat[i + 5]   # ← LOOKAHEAD
            out.append(_Sig(ts, "long", future_close, future_close - 1, future_close + 1))
        return out

    idx = pd.date_range("2020-01-01", periods=300, freq="h", tz="UTC")
    # Make mid_close vary so future leakage produces different values when truncated.
    h1 = pd.DataFrame({"mid_close": [float(i) for i in range(300)]}, index=idx)
    m3 = pd.DataFrame({"mid_close": [0]}, index=[idx[0]])

    with pytest.raises(AssertionError, match="LOOKAHEAD DETECTED"):
        assert_no_lookahead(buggy_fn, h1, m3, sample_count=10, fn_name="buggy_fn")
