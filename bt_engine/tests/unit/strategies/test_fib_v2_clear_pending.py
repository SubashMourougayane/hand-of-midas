"""F5: clear_pending_entries must recurse into a COMPOSITE state's per-leg states.

The live runner clears warmup-queued pending entries after replay. A bare
`state.pending_entries = []` only touches the top object; the composite A+D
state holds none of its own (it nests a_state / d_state), so warmup entries would
stay armed on both legs = duplicate order on the first live bar. The fix exposes
clear_pending_entries() on both the leaf and the composite (recursing).
"""
from __future__ import annotations

from bt_engine.strategies.fib_v2.state import FibV2State
from bt_engine.strategies.fib_v2_intraday.combined import FibV2IntradayADState


def test_leaf_clear_pending_entries_empties_list() -> None:
    s = FibV2State()
    s.pending_entries = [("intraday_a_long", object())]  # type: ignore[list-item]
    assert s.pending_entries
    s.clear_pending_entries()
    assert s.pending_entries == []


def test_composite_clear_recurses_into_both_legs() -> None:
    a, d = FibV2State(), FibV2State()
    a.pending_entries = [("intraday_a_long", object())]  # type: ignore[list-item]
    d.pending_entries = [("intraday_d_short", object())]  # type: ignore[list-item]
    comp = FibV2IntradayADState(a_state=a, d_state=d)
    comp.clear_pending_entries()
    assert a.pending_entries == []
    assert d.pending_entries == []


def test_composite_clear_tolerates_missing_leg_states() -> None:
    # Defensive: a composite constructed without leg states must not raise.
    comp = FibV2IntradayADState(a_state=None, d_state=None)
    comp.clear_pending_entries()  # no exception


def test_runner_style_dispatch_prefers_method_over_attr() -> None:
    """Mirrors the live runner's hasattr dispatch: method wins, recurses."""
    a, d = FibV2State(), FibV2State()
    a.pending_entries = [("intraday_a_long", object())]  # type: ignore[list-item]
    d.pending_entries = [("intraday_d_short", object())]  # type: ignore[list-item]
    comp = FibV2IntradayADState(a_state=a, d_state=d)

    # replicate live.py dispatch
    if hasattr(comp, "clear_pending_entries"):
        comp.clear_pending_entries()
    elif hasattr(comp, "pending_entries"):
        comp.pending_entries = []  # would NOT clear legs — the bug path

    assert a.pending_entries == [] and d.pending_entries == []
