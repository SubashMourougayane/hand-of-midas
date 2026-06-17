"""Filter #27 — unit tests for the compute_limit_price helper.

These tests lock in the exact mapping between (variant, direction, inputs) and
limit_price output. The same helper is called by BT engines AND the live
scheduler — these tests are the parity guarantee.

If you change compute_limit_price, you must update the BT inline tests too,
re-run the Filter #27 sweep, and confirm the BT cell P&L numbers haven't moved.
"""
import pytest

from backend.execution.limit_price import compute_limit_price


# ----- Variant A: offset = 0.0 → return signal_entry verbatim -----

def test_variant_a_long_returns_signal_entry():
    p = compute_limit_price(
        direction="long",
        signal_entry=4318.68,
        signal_risk=8.95,
        engulf_close_ask=4318.50,  # ignored
        engulf_close_bid=4318.40,  # ignored
        limit_offset_pct=0.0,
    )
    assert p == 4318.68


def test_variant_a_short_returns_signal_entry():
    p = compute_limit_price(
        direction="short",
        signal_entry=4322.81,
        signal_risk=11.41,
        engulf_close_ask=4323.0,  # ignored
        engulf_close_bid=4322.9,  # ignored
        limit_offset_pct=0.0,
    )
    assert p == 4322.81


# ----- Variant B: "engulf_close" → ask_close for LONG, bid_close for SHORT -----

def test_variant_b_long_uses_ask_close():
    p = compute_limit_price(
        direction="long",
        signal_entry=4318.68,  # ignored
        signal_risk=8.95,       # ignored
        engulf_close_ask=4318.50,
        engulf_close_bid=4318.40,
        limit_offset_pct="engulf_close",
    )
    assert p == 4318.50


def test_variant_b_short_uses_bid_close():
    p = compute_limit_price(
        direction="short",
        signal_entry=4322.81,   # ignored
        signal_risk=11.41,       # ignored
        engulf_close_ask=4322.95,
        engulf_close_bid=4322.85,
        limit_offset_pct="engulf_close",
    )
    assert p == 4322.85


# ----- Variant C: pullback into structure by offset × risk -----
# Sign convention: offset_pct is negative for the swept variants.
# LONG  → entry + offset×risk     (offset negative → limit below entry)
# SHORT → entry - offset×risk     (offset negative → limit above entry)

def test_variant_c10_long_pulls_back_below_entry():
    # entry $4318.68, risk $8.95, -10% pullback → entry - $0.895 = $4317.785
    p = compute_limit_price(
        direction="long",
        signal_entry=4318.68,
        signal_risk=8.95,
        engulf_close_ask=4318.50,  # ignored
        engulf_close_bid=4318.40,  # ignored
        limit_offset_pct=-0.10,
    )
    assert p == pytest.approx(4317.785, abs=1e-9)


def test_variant_c10_short_pulls_back_above_entry():
    # entry $4322.81, risk $11.41, -10% offset for SHORT → entry + $1.141 = $4323.951
    # Sign-flip on SHORT is the explicit BT engine convention.
    p = compute_limit_price(
        direction="short",
        signal_entry=4322.81,
        signal_risk=11.41,
        engulf_close_ask=4322.95,  # ignored
        engulf_close_bid=4322.85,  # ignored
        limit_offset_pct=-0.10,
    )
    assert p == pytest.approx(4323.951, abs=1e-9)


def test_variant_c20_long():
    # -20% pullback × $10 risk = $2 below entry
    p = compute_limit_price(
        direction="long",
        signal_entry=100.0,
        signal_risk=10.0,
        engulf_close_ask=99.5,
        engulf_close_bid=99.4,
        limit_offset_pct=-0.20,
    )
    assert p == pytest.approx(98.0, abs=1e-9)


def test_variant_c30_short():
    # -30% × $5 risk → SHORT limit at entry + $1.50
    p = compute_limit_price(
        direction="short",
        signal_entry=80.50,
        signal_risk=5.0,
        engulf_close_ask=80.55,
        engulf_close_bid=80.45,
        limit_offset_pct=-0.30,
    )
    assert p == pytest.approx(82.0, abs=1e-9)


# ----- Error cases -----

def test_unknown_direction_raises():
    with pytest.raises(ValueError, match="direction"):
        compute_limit_price(
            direction="hold",
            signal_entry=100.0, signal_risk=1.0,
            engulf_close_ask=100.0, engulf_close_bid=100.0,
            limit_offset_pct=0.0,
        )


def test_unknown_offset_string_raises():
    with pytest.raises(ValueError, match="limit_offset_pct"):
        compute_limit_price(
            direction="long",
            signal_entry=100.0, signal_risk=1.0,
            engulf_close_ask=100.0, engulf_close_bid=100.0,
            limit_offset_pct="some_other_string",
        )


def test_unknown_offset_dict_raises():
    with pytest.raises(ValueError, match="limit_offset_pct"):
        compute_limit_price(
            direction="long",
            signal_entry=100.0, signal_risk=1.0,
            engulf_close_ask=100.0, engulf_close_bid=100.0,
            limit_offset_pct={"foo": 1},
        )


# ----- M1: non-positive result guard -----

def test_m1_negative_result_long_raises():
    """M1: LONG with offset that drives limit <= 0 must raise, not return junk.
    Scenario: tiny entry + huge offset × risk."""
    with pytest.raises(ValueError, match="non-positive"):
        compute_limit_price(
            direction="long",
            signal_entry=0.5, signal_risk=10.0,
            engulf_close_ask=0.5, engulf_close_bid=0.4,
            limit_offset_pct=-0.10,  # 0.5 + (-0.10 × 10) = -0.5
        )


def test_m1_negative_result_short_raises():
    """M1: SHORT mirror with absurd offset producing negative result."""
    with pytest.raises(ValueError, match="non-positive"):
        compute_limit_price(
            direction="short",
            signal_entry=0.5, signal_risk=10.0,
            engulf_close_ask=0.6, engulf_close_bid=0.5,
            limit_offset_pct=10.0,  # 0.5 - (10.0 × 10) = -99.5
        )


def test_m1_zero_result_raises():
    """M1: result == 0 also raises (not just negative). Broker would reject.
    Edge case: signal_entry exactly cancels offset×risk."""
    with pytest.raises(ValueError, match="non-positive"):
        compute_limit_price(
            direction="long",
            signal_entry=10.0, signal_risk=100.0,
            engulf_close_ask=10.0, engulf_close_bid=10.0,
            limit_offset_pct=-0.10,  # 10 + (-0.10 × 100) = 0.0
        )


def test_m1_normal_positive_unchanged():
    """M1 regression: realistic positive result must still return cleanly.
    XAU at $4000 with offset=-0.10 and risk=$5: 4000 - 0.5 = $3999.5"""
    result = compute_limit_price(
        direction="long",
        signal_entry=4000.0, signal_risk=5.0,
        engulf_close_ask=4000.0, engulf_close_bid=3999.9,
        limit_offset_pct=-0.10,
    )
    assert result == 3999.5


# ----- BT-engine parity probes -----
# These mirror the exact inline code that exists today in the 4 BT engines.
# If they ever drift, the unit test fails BEFORE the BT does — the cheap
# guard against the parity-drift bug class.

def test_bt_inline_long_a_parity():
    """Mirror backend/backtest/engine.py:283-285 LONG variant A."""
    signal_entry = 4318.68
    expected = signal_entry  # signal.entry verbatim
    got = compute_limit_price(
        direction="long",
        signal_entry=signal_entry,
        signal_risk=8.95,
        engulf_close_ask=4318.50, engulf_close_bid=4318.40,
        limit_offset_pct=0.0,
    )
    assert got == expected


def test_bt_inline_short_b_parity():
    """Mirror backend/backtest/engine.py:277-282 SHORT variant B (bid_close)."""
    bid_close = 4322.85
    expected = bid_close
    got = compute_limit_price(
        direction="short",
        signal_entry=4322.81,
        signal_risk=11.41,
        engulf_close_ask=4322.95,
        engulf_close_bid=bid_close,
        limit_offset_pct="engulf_close",
    )
    assert got == expected


def test_bt_inline_long_c_parity():
    """Mirror backend/backtest/engine.py:289-290 LONG variant C."""
    signal_entry = 4318.68
    signal_risk = 8.95
    offset = -0.10
    expected = signal_entry + offset * signal_risk
    got = compute_limit_price(
        direction="long",
        signal_entry=signal_entry,
        signal_risk=signal_risk,
        engulf_close_ask=4318.50,
        engulf_close_bid=4318.40,
        limit_offset_pct=offset,
    )
    assert got == expected


def test_bt_inline_short_c_parity():
    """Mirror backend/backtest/engine.py:291-292 SHORT variant C."""
    signal_entry = 4322.81
    signal_risk = 11.41
    offset = -0.10
    expected = signal_entry - offset * signal_risk  # SHORT sign-flip
    got = compute_limit_price(
        direction="short",
        signal_entry=signal_entry,
        signal_risk=signal_risk,
        engulf_close_ask=4322.95,
        engulf_close_bid=4322.85,
        limit_offset_pct=offset,
    )
    assert got == expected
