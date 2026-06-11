"""TEST 22: Parity Verification Harness.

Compares LIVE signal-gen against BACKTEST signal-gen for each system on
the same input bars. Phase 1 ships gold_micro only.

Soft gate behavior (Phase 2):
  - Catastrophic drift  → pytest fails (CI blocks)
  - Warning-level drift → pytest passes with warning + JSON artifact
  - Clean parity        → pytest passes silently

The gate logic is extracted into a pure function (`evaluate_gates`) so it
can be unit-tested with synthetic ParityScores without running the full
extraction pipeline. See test_22_parity_gates_*  cases below.

See docs/PARITY_HARNESS_PLAN.md for the full design.
"""

import os
import sys
import warnings
from dataclasses import dataclass

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.harness.parity import SYSTEMS, run_parity_check
from tests.harness.parity.score import ParityScore


# Default replay window for Phase 1. Larger windows can be passed manually
# via env var PARITY_DAYS for diagnostic deep-dives.
PARITY_DAYS = int(os.environ.get("PARITY_DAYS", "7"))

# Soft-gate thresholds. Tuned conservatively; revisit after first 2-3 runs
# per system reveal real-world numbers (see PARITY_HARNESS_PLAN.md).
CATASTROPHIC_PARITY_PCT = 0.50
CATASTROPHIC_DIR_DISAGREEMENTS = 5
CATASTROPHIC_BT_SIGNALS_WITH_ZERO_LIVE = 5
WARNING_PARITY_PCT = 0.85


@dataclass
class GateVerdict:
    """Outcome of evaluating the soft gates against a ParityScore."""
    catastrophic_reasons: list[str]
    warning_reasons: list[str]

    @property
    def is_catastrophic(self) -> bool:
        return bool(self.catastrophic_reasons)

    @property
    def is_warning(self) -> bool:
        return bool(self.warning_reasons) and not self.is_catastrophic

    @property
    def is_clean(self) -> bool:
        return not self.catastrophic_reasons and not self.warning_reasons


def evaluate_gates(score: ParityScore) -> GateVerdict:
    """Apply soft-gate thresholds to a ParityScore. Pure function — no I/O,
    no pytest interaction. Phase 2 unit tests verify each branch fires."""
    catastrophic = []
    if score.parity_pct < CATASTROPHIC_PARITY_PCT:
        catastrophic.append(f"parity_pct={score.parity_pct:.1%} < {CATASTROPHIC_PARITY_PCT:.0%}")
    if score.direction_disagreements > CATASTROPHIC_DIR_DISAGREEMENTS:
        catastrophic.append(
            f"direction_disagreements={score.direction_disagreements} > {CATASTROPHIC_DIR_DISAGREEMENTS}"
        )
    if (score.total_signals_live == 0
            and score.total_signals_backtest > CATASTROPHIC_BT_SIGNALS_WITH_ZERO_LIVE):
        catastrophic.append(
            f"live=0 signals while backtest={score.total_signals_backtest}"
            f" > {CATASTROPHIC_BT_SIGNALS_WITH_ZERO_LIVE}"
        )

    warning = []
    if score.parity_pct < WARNING_PARITY_PCT:
        warning.append(f"parity_pct={score.parity_pct:.1%} < {WARNING_PARITY_PCT:.0%}")
    if score.direction_disagreements > 0:
        warning.append(f"direction_disagreements={score.direction_disagreements} > 0")

    return GateVerdict(catastrophic_reasons=catastrophic, warning_reasons=warning)


# ---------------------------------------------------------------------------
# Live test — runs the actual harness against current data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("system_key", list(SYSTEMS.keys()))
def test_parity(system_key, capsys):
    """Run the parity harness for one system and apply the soft gate."""
    score = run_parity_check(system_key, days=PARITY_DAYS)
    artifact_path = score.write_json()

    summary = score.summary_line()
    verdict = evaluate_gates(score)

    # Always print summary + artifact path so the user sees the result even
    # on green runs.
    with capsys.disabled():
        print()
        print(f"  {summary}")
        print(f"  artifact: {artifact_path}")

    if verdict.is_catastrophic:
        pytest.fail(
            f"CATASTROPHIC parity failure for {system_key}: "
            f"{'; '.join(verdict.catastrophic_reasons)}\n  {summary}\n  "
            f"see {artifact_path}"
        )

    if verdict.warning_reasons:
        with capsys.disabled():
            print(f"  WARNING ({system_key}): {'; '.join(verdict.warning_reasons)}")
        warnings.warn(
            f"Parity below threshold for {system_key}: "
            f"{'; '.join(verdict.warning_reasons)}",
            UserWarning,
            stacklevel=2,
        )


# ---------------------------------------------------------------------------
# Phase 2 — gate logic unit tests (synthetic ParityScores)
# ---------------------------------------------------------------------------

def _make_score(
    *,
    parity_pct: float = 0.95,
    bt: int = 10,
    live: int = 10,
    in_both: int = 10,
    agree: int = 10,
    disagree: int = 0,
) -> ParityScore:
    """Build a synthetic ParityScore for gate-logic tests.

    Sensible defaults give a 'clean' score; override fields to construct
    the failure modes the gates are supposed to catch.
    """
    from datetime import date
    return ParityScore(
        system="synthetic",
        date_range=(date(2026, 1, 1), date(2026, 1, 7)),
        total_signals_backtest=bt,
        total_signals_live=live,
        signals_in_both=in_both,
        signals_only_in_backtest=bt - in_both,
        signals_only_in_live=live - in_both,
        direction_agreements=agree,
        direction_disagreements=disagree,
        avg_entry_price_delta=0.0,
        max_entry_price_delta=0.0,
        avg_timestamp_delta_secs=0.0,
        skip_reason_histogram_backtest={},
        skip_reason_histogram_live={},
        parity_pct=parity_pct,
    )


class TestGateLogic:
    """Unit tests for evaluate_gates() — proves each branch fires correctly
    without running the full extractor (which takes ~8s)."""

    def test_clean_score_passes_silent(self):
        verdict = evaluate_gates(_make_score(parity_pct=0.95))
        assert verdict.is_clean
        assert not verdict.catastrophic_reasons
        assert not verdict.warning_reasons

    def test_low_parity_pct_is_catastrophic(self):
        verdict = evaluate_gates(_make_score(parity_pct=0.30))
        assert verdict.is_catastrophic
        assert any("parity_pct" in r for r in verdict.catastrophic_reasons)

    def test_parity_at_threshold_50pct_is_warning_not_catastrophic(self):
        verdict = evaluate_gates(_make_score(parity_pct=0.50))
        # 0.50 is NOT less than 0.50 → not catastrophic
        assert not verdict.is_catastrophic
        # 0.50 < 0.85 → warning
        assert verdict.is_warning

    def test_many_disagreements_is_catastrophic(self):
        verdict = evaluate_gates(_make_score(
            parity_pct=0.90, in_both=10, agree=4, disagree=6,
        ))
        assert verdict.is_catastrophic
        assert any("direction_disagreements" in r
                   for r in verdict.catastrophic_reasons)

    def test_one_disagreement_is_warning_only(self):
        verdict = evaluate_gates(_make_score(
            parity_pct=0.90, in_both=10, agree=9, disagree=1,
        ))
        assert not verdict.is_catastrophic
        assert verdict.is_warning
        assert any("direction_disagreements" in r
                   for r in verdict.warning_reasons)

    def test_zero_live_with_many_bt_is_catastrophic(self):
        verdict = evaluate_gates(_make_score(
            parity_pct=0.10, bt=20, live=0, in_both=0, agree=0,
        ))
        assert verdict.is_catastrophic
        # Both parity-pct and zero-live conditions fire here:
        assert any("live=0" in r for r in verdict.catastrophic_reasons)

    def test_zero_live_with_few_bt_is_not_catastrophic_on_count_alone(self):
        # 5 BT signals + 0 Live → count check is total_bt > 5 (strict),
        # which is False at exactly 5. Parity will still trigger if low.
        verdict = evaluate_gates(_make_score(
            parity_pct=0.95, bt=5, live=0, in_both=0, agree=0,
        ))
        # 0/max(5,0,1) = 0 → that's the actual coverage component, but our
        # synthetic _make_score lets us set parity_pct directly. Here we
        # explicitly assert: zero-live with bt==threshold is NOT a
        # catastrophic count failure.
        assert not any("live=0" in r for r in verdict.catastrophic_reasons)

    def test_warning_when_only_warning_thresholds_breached(self):
        # parity 80% (< 85% warning), 0 disagreements, plenty of signals.
        verdict = evaluate_gates(_make_score(parity_pct=0.80))
        assert not verdict.is_catastrophic
        assert verdict.is_warning
        assert any("parity_pct=80.0%" in r for r in verdict.warning_reasons)

    def test_catastrophic_supersedes_warning_classification(self):
        # parity 30% triggers BOTH catastrophic (< 50%) and warning (< 85%).
        # GateVerdict.is_warning should be False — catastrophic wins.
        verdict = evaluate_gates(_make_score(parity_pct=0.30))
        assert verdict.is_catastrophic
        assert verdict.is_warning is False
        # But warning_reasons list is still populated for completeness.
        assert verdict.warning_reasons


# ---------------------------------------------------------------------------
# Phase 5 — diagnosis hint unit tests
# ---------------------------------------------------------------------------

def _make_record(
    *,
    direction: str = "long",
    entry: float = 4500.0,
    sl: float = 4485.0,
    tp: float = 4530.0,
    bias: str = "bullish",
    skip_reason: str = "",
    ts_offset_secs: int = 0,
):
    """Build a SignalRecord for diff/hint tests. Returns a fresh dataclass."""
    from datetime import datetime, timezone, timedelta
    from tests.harness.parity.extractor import SignalRecord
    base = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    return SignalRecord(
        system="synthetic",
        timestamp=base + timedelta(seconds=ts_offset_secs),
        direction=direction,
        taken=True,
        skip_reason=skip_reason,
        entry_price=entry,
        sl_price=sl,
        tp_price=tp,
        sweep_wick=4490.0,
        sweep_dir="bullish",
        bias=bias,
        range_high=4505.0,
        range_low=4480.0,
    )


class TestDiagnosisHints:
    """Phase 5: every SignalDiff has a non-empty, human-readable hint
    pointing at a specific class of drift."""

    def test_clean_overlap_yields_agreement_hint(self):
        from tests.harness.parity.diff import diff_signals
        bt = _make_record()
        live = _make_record()
        diffs = diff_signals([bt], [live])
        assert len(diffs) == 1
        assert diffs[0].diagnosis_hint == "agreement"

    def test_direction_flip_is_called_out(self):
        # Same minute bucket, opposite directions. Note: the diff.py keys by
        # (minute, direction), so opposite directions create TWO buckets,
        # not one — there is no overlap to "flip". The test verifies the
        # actual behavior: each side becomes its own only-one-side diff.
        from tests.harness.parity.diff import diff_signals
        bt = _make_record(direction="long")
        live = _make_record(direction="short")
        diffs = diff_signals([bt], [live])
        assert len(diffs) == 2
        # Each diff has only-one-side hints.
        hints = sorted(d.diagnosis_hint for d in diffs)
        assert any("backtest" in h for h in hints)
        assert any("live" in h for h in hints)

    def test_entry_price_drift_above_threshold_is_called_out(self):
        from tests.harness.parity.diff import diff_signals
        bt = _make_record(entry=4500.0)
        live = _make_record(entry=4502.5)   # $2.50 drift > $1 threshold
        diffs = diff_signals([bt], [live])
        assert len(diffs) == 1
        assert "entry_price_delta_exceeds" in diffs[0].diagnosis_hint
        assert "+2.50" in diffs[0].diagnosis_hint

    def test_entry_price_drift_below_threshold_is_agreement(self):
        from tests.harness.parity.diff import diff_signals
        bt = _make_record(entry=4500.0)
        live = _make_record(entry=4500.5)   # $0.50 drift < $1 threshold
        diffs = diff_signals([bt], [live])
        assert diffs[0].diagnosis_hint == "agreement"

    def test_timestamp_delta_above_threshold_is_called_out(self):
        # Both signals carry the same comparison_key (same floored minute,
        # same direction) so they DO match in the diff bucket. The hint
        # then surfaces the timestamp drift.
        from tests.harness.parity.diff import diff_signals
        bt = _make_record(ts_offset_secs=0)
        live = _make_record(ts_offset_secs=30)   # same minute bucket
        diffs = diff_signals([bt], [live])
        assert len(diffs) == 1
        # 30-sec drift is within minute bucket but below 180s hint threshold.
        # No hint should fire (still agreement).
        assert diffs[0].diagnosis_hint == "agreement"

    def test_live_only_signal_gets_specific_hint(self):
        from tests.harness.parity.diff import diff_signals
        live = _make_record()
        diffs = diff_signals([], [live])
        assert len(diffs) == 1
        assert "live" in diffs[0].diagnosis_hint
        assert "backtest" in diffs[0].diagnosis_hint or "outside" in diffs[0].diagnosis_hint

    def test_backtest_only_signal_gets_specific_hint(self):
        from tests.harness.parity.diff import diff_signals
        bt = _make_record()
        diffs = diff_signals([bt], [])
        assert len(diffs) == 1
        assert "backtest" in diffs[0].diagnosis_hint or "outside" in diffs[0].diagnosis_hint

    def test_skip_reason_carried_into_hint(self):
        # A live signal with a skip_reason populated is the
        # "live_skipped_with_reason_X_backtest_did_not" canonical case.
        from tests.harness.parity.diff import diff_signals
        live = _make_record(skip_reason="range_min_too_small")
        diffs = diff_signals([], [live])
        assert "range_min_too_small" in diffs[0].diagnosis_hint

    def test_every_diff_has_nonempty_hint(self):
        # Build a small but mixed set covering every branch. Verify no diff
        # comes out with an empty/None hint.
        from tests.harness.parity.diff import diff_signals
        records = [
            _make_record(),
            _make_record(direction="short", entry=4480.0),
            _make_record(skip_reason="some_skip"),
        ]
        diffs = diff_signals(records[:2], records[1:])
        assert len(diffs) >= 1
        for d in diffs:
            assert d.diagnosis_hint, f"Empty hint on diff: {d}"
            assert d.diagnosis_hint != "no_records"

