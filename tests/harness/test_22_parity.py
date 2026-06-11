"""TEST 22: Parity Verification Harness.

Compares LIVE signal-gen against BACKTEST signal-gen for each system on
the same input bars. Phase 1 ships gold_micro only.

Soft gate behavior:
  - Catastrophic drift  → pytest fails (CI blocks)
  - Warning-level drift → pytest passes with warning + JSON artifact
  - Clean parity        → pytest passes silently

See docs/PARITY_HARNESS_PLAN.md for the full design.
"""

import os
import sys
import warnings

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.harness.parity import SYSTEMS, run_parity_check


# Default replay window for Phase 1. Larger windows can be passed manually
# via env var PARITY_DAYS for diagnostic deep-dives.
PARITY_DAYS = int(os.environ.get("PARITY_DAYS", "7"))


@pytest.mark.parametrize("system_key", list(SYSTEMS.keys()))
def test_parity(system_key, capsys):
    """Run the parity harness for one system and apply the soft gate."""
    score = run_parity_check(system_key, days=PARITY_DAYS)
    artifact_path = score.write_json()

    summary = score.summary_line()

    # Always print summary + artifact path so the user sees the result even
    # on green runs.
    with capsys.disabled():
        print()
        print(f"  {summary}")
        print(f"  artifact: {artifact_path}")

    # ---------------- Catastrophic gate -----------------
    catastrophic_reasons = []
    if score.parity_pct < 0.50:
        catastrophic_reasons.append(f"parity_pct={score.parity_pct:.1%} < 50%")
    if score.direction_disagreements > 5:
        catastrophic_reasons.append(
            f"direction_disagreements={score.direction_disagreements} > 5"
        )
    if score.total_signals_live == 0 and score.total_signals_backtest > 5:
        catastrophic_reasons.append(
            f"live=0 signals while backtest={score.total_signals_backtest}"
        )

    if catastrophic_reasons:
        pytest.fail(
            f"CATASTROPHIC parity failure for {system_key}: "
            f"{'; '.join(catastrophic_reasons)}\n  {summary}\n  "
            f"see {artifact_path}"
        )

    # ---------------- Warning gate -----------------
    warning_reasons = []
    if score.parity_pct < 0.85:
        warning_reasons.append(f"parity_pct={score.parity_pct:.1%} < 85%")
    if score.direction_disagreements > 0:
        warning_reasons.append(
            f"direction_disagreements={score.direction_disagreements} > 0"
        )

    if warning_reasons:
        with capsys.disabled():
            print(f"  WARNING ({system_key}): {'; '.join(warning_reasons)}")
        warnings.warn(
            f"Parity below threshold for {system_key}: {'; '.join(warning_reasons)}",
            UserWarning,
            stacklevel=2,
        )
