"""Unit tests for backend/scanner/production_gates.py.

Each gate tested in isolation. State is built fresh per test. Mock signals
and callbacks. No DB, no broker, no scheduler.

Goal: prove apply_gates is a pure function of (signal, state, cfg, callbacks).
Both BT and live can call it. Same inputs = same skip_reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from backend.scanner.production_gates import (
    GateState,
    apply_gates,
    compute_risk_multiplier,
    make_sweep_key,
    update_state_after_fire,
    update_state_after_exit,
    reset_for_new_day,
    cooldown_arms_on_skip,
    compute_broker_costs,
)


OIL_COSTS = {
    "lot_size": 100,
    "commission_per_lot_rt": 7.0,
    "swap_long_per_lot_per_night": -3.0,
    "swap_short_per_lot_per_night": -1.0,
}

GOLD_COSTS = {
    "lot_size": 100,
    "commission_per_lot_rt": 6.0,
    "swap_long_per_lot_per_night": -2.0,
    "swap_short_per_lot_per_night": -1.0,
}


# ─── Test fixtures ──────────────────────────────────────────


@dataclass
class FakeSignal:
    """Minimal Signal-like dataclass for tests."""
    date: datetime
    direction: str = "long"
    metadata: Optional[dict] = None


def _sig(at: str, *, direction="long", sweep_time=None, start_hour=0, sweep_dir="bullish") -> FakeSignal:
    """Helper: build a FakeSignal with full metadata."""
    return FakeSignal(
        date=datetime.fromisoformat(at).replace(tzinfo=timezone.utc),
        direction=direction,
        metadata={
            "sweep_time": sweep_time or at,
            "start_hour": start_hour,
            "sweep_dir": sweep_dir,
        },
    )


CFG = {"max_trades_per_day": 3}


# ─── Gate-by-gate tests ─────────────────────────────────────


def test_no_gates_no_state_passes():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    assert apply_gates(sig, s, cfg=CFG) is None


def test_daily_cap_reached_blocks():
    s = GateState(day_filled_trades=3)
    sig = _sig("2026-06-17T10:00:00")
    assert apply_gates(sig, s, cfg=CFG) == "daily_cap_reached"


def test_daily_cap_below_passes():
    s = GateState(day_filled_trades=2)
    sig = _sig("2026-06-17T10:00:00")
    assert apply_gates(sig, s, cfg=CFG) is None


def test_dd_pause_counter_decrements_and_blocks():
    s = GateState(pause_counter=2)
    sig = _sig("2026-06-17T10:00:00")
    assert apply_gates(sig, s, cfg=CFG) == "dd_pause"
    assert s.pause_counter == 1
    # Next call decrements again
    assert apply_gates(sig, s, cfg=CFG) == "dd_pause"
    assert s.pause_counter == 0
    # Next call passes (counter exhausted)
    assert apply_gates(sig, s, cfg=CFG) is None


def test_one_at_a_time_blocker():
    """Signal whose date is BEFORE position_exit_time is blocked."""
    s = GateState(position_exit_time=datetime(2026, 6, 17, 10, 30, tzinfo=timezone.utc))
    sig_early = _sig("2026-06-17T10:15:00")
    assert apply_gates(sig_early, s, cfg=CFG) == "open_position"
    sig_after = _sig("2026-06-17T10:31:00")
    assert apply_gates(sig_after, s, cfg=CFG) is None


def test_5min_cooldown_blocks_within_window():
    s = GateState(last_signal_time=datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc))
    # 4 minutes later = blocked
    sig_in_cooldown = _sig("2026-06-17T10:04:00")
    assert apply_gates(sig_in_cooldown, s, cfg=CFG) == "cooldown_5min"
    # Exactly 5 minutes later — boundary, should fire (>= 5min)
    sig_at_boundary = _sig("2026-06-17T10:05:00")
    assert apply_gates(sig_at_boundary, s, cfg=CFG) is None
    # 6 minutes later = pass
    sig_after = _sig("2026-06-17T10:06:00")
    assert apply_gates(sig_after, s, cfg=CFG) is None


def test_sweep_blacklist_blocks_repeat():
    sig = _sig("2026-06-17T10:00:00", sweep_time="2026-06-17T09:00:00", start_hour=8, sweep_dir="bearish")
    s = GateState()
    s.consumed_sweeps.add(make_sweep_key(sig))
    assert apply_gates(sig, s, cfg=CFG) == "sweep_already_traded"


def test_make_sweep_key_deterministic():
    """Same metadata → same key. Different sweep_time/dir/start_hour → different key."""
    sig1 = _sig("2026-06-17T10:00:00", sweep_time="2026-06-17T09:00:00", start_hour=8, sweep_dir="bearish")
    sig2 = _sig("2026-06-17T10:00:00", sweep_time="2026-06-17T09:00:00", start_hour=8, sweep_dir="bearish")
    assert make_sweep_key(sig1) == make_sweep_key(sig2)
    sig3 = _sig("2026-06-17T10:00:00", sweep_time="2026-06-17T09:00:00", start_hour=10, sweep_dir="bearish")
    assert make_sweep_key(sig3) != make_sweep_key(sig1)


def test_make_sweep_key_legacy_fallback():
    """Signal without metadata falls back to date+direction."""
    sig = FakeSignal(date=datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc), direction="short", metadata=None)
    key = make_sweep_key(sig)
    assert "2026-06-17" in key
    assert "short" in key


# ─── Live-only callback gates ────────────────────────────────


def test_db_open_position_callback_blocks():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    cbs = {"check_db_open_positions": lambda: 1}
    assert apply_gates(sig, s, cfg=CFG, callbacks=cbs) == "open_position_db"


def test_db_open_position_callback_passes_when_zero():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    cbs = {"check_db_open_positions": lambda: 0}
    assert apply_gates(sig, s, cfg=CFG, callbacks=cbs) is None


def test_mt5_lock_callback_blocks():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    cbs = {"check_mt5_open_positions": lambda: 1}
    assert apply_gates(sig, s, cfg=CFG, callbacks=cbs) == "open_position_mt5"


def test_startup_cooldown_callback_blocks():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    cbs = {"check_startup_cooldown": lambda now: True}
    assert apply_gates(sig, s, cfg=CFG, callbacks=cbs) == "startup_cooldown"


def test_no_callbacks_means_no_live_gates():
    """BT path: passes empty callbacks → no live-only gates apply."""
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    assert apply_gates(sig, s, cfg=CFG, callbacks={}) is None
    assert apply_gates(sig, s, cfg=CFG) is None  # default callbacks=None → same


# ─── Gate ordering / precedence ──────────────────────────────


def test_daily_cap_checked_before_one_at_a_time():
    """Cap reached → don't even check position_exit_time."""
    s = GateState(
        day_filled_trades=3,
        position_exit_time=datetime(2026, 6, 17, 11, 0, tzinfo=timezone.utc),
    )
    sig = _sig("2026-06-17T10:00:00")
    # Both gates would fire. Cap takes precedence.
    assert apply_gates(sig, s, cfg=CFG) == "daily_cap_reached"


def test_cooldown_checked_before_blacklist():
    """Cooldown is gate 4; blacklist is gate 5. Cooldown wins on dual fail."""
    sig = _sig("2026-06-17T10:00:00")
    s = GateState(last_signal_time=datetime(2026, 6, 17, 9, 58, tzinfo=timezone.utc))
    s.consumed_sweeps.add(make_sweep_key(sig))
    # Both gates fail. Cooldown checked first (5-min)
    assert apply_gates(sig, s, cfg=CFG) == "cooldown_5min"


# ─── Risk multiplier ─────────────────────────────────────────


def test_risk_mult_default_full():
    assert compute_risk_multiplier(GateState()) == 1.0


def test_risk_mult_3_consec_losses_halves():
    s = GateState(consecutive_losses=3)
    assert compute_risk_multiplier(s) == 0.5


def test_risk_mult_equity_below_ma_halves():
    s = GateState(equity=900.0, equity_history=[1000.0] * 20)
    # eq_ma = 1000, equity 900 < 1000 → half
    assert compute_risk_multiplier(s) == 0.5


def test_risk_mult_both_conditions_quarter():
    s = GateState(consecutive_losses=5, equity=900.0, equity_history=[1000.0] * 20)
    assert compute_risk_multiplier(s) == 0.25


def test_risk_mult_few_history_no_equity_check():
    """Equity-MA only kicks in with 20+ history."""
    s = GateState(consecutive_losses=0, equity=500.0, equity_history=[1000.0] * 10)
    assert compute_risk_multiplier(s) == 1.0


# ─── State mutation helpers ──────────────────────────────────


def test_update_state_after_fire_sets_cooldown_and_blacklist():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00", sweep_time="2026-06-17T09:00:00", start_hour=8, sweep_dir="bearish")
    update_state_after_fire(s, sig, expected_exit_seconds=240 * 3 * 60)  # 240 M3 bars
    assert s.last_signal_time == sig.date
    assert s.position_exit_time == sig.date + timedelta(seconds=240 * 3 * 60)
    assert make_sweep_key(sig) in s.consumed_sweeps


def test_update_state_after_exit_loss_increments_streak():
    s = GateState(consecutive_losses=2)
    update_state_after_exit(s, pnl_dollar=-100.0, equity_after=900.0)
    assert s.consecutive_losses == 3
    assert s.equity == 900.0
    assert s.equity_history == [900.0]


def test_update_state_after_exit_5_losses_arms_pause():
    s = GateState(consecutive_losses=4)
    update_state_after_exit(s, pnl_dollar=-100.0, equity_after=900.0)
    assert s.consecutive_losses == 5
    assert s.pause_counter == 2


def test_update_state_after_exit_win_resets_streak():
    s = GateState(consecutive_losses=4)
    update_state_after_exit(s, pnl_dollar=100.0, equity_after=1100.0)
    assert s.consecutive_losses == 0
    assert s.pause_counter == 0  # NOT armed


def test_reset_for_new_day_clears_day_state_keeps_cross_day():
    s = GateState(
        consumed_sweeps={"key1", "key2"},
        day_filled_trades=2,
        day_pnl=100.0,
        consecutive_losses=3,  # cross-day, kept
        equity=1000.0,
        equity_history=[900, 950, 1000],  # cross-day, kept
    )
    new_date = datetime(2026, 6, 18, tzinfo=timezone.utc).date()
    reset_for_new_day(s, new_date)
    assert s.consumed_sweeps == set()
    assert s.day_filled_trades == 0
    assert s.day_pnl == 0.0
    assert s.consecutive_losses == 3   # preserved
    assert s.equity == 1000.0           # preserved
    assert len(s.equity_history) == 3   # preserved


# ─── BT no-callbacks path: gates that should be live-only stay silent ────


def test_bt_path_no_db_no_mt5_no_startup_callbacks_means_those_gates_skip():
    """BT (no callbacks) — live-only gates are no-ops."""
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    # No callbacks dict → all 3 live-only checks skipped
    assert apply_gates(sig, s, cfg=CFG) is None


# ─── Live path: callbacks fire when state says ─────────────────


def test_live_path_all_callbacks_independently_blocking():
    s = GateState()
    sig = _sig("2026-06-17T10:00:00")
    # Each in isolation
    assert apply_gates(sig, s, cfg=CFG, callbacks={"check_db_open_positions": lambda: 1}) == "open_position_db"
    assert apply_gates(sig, s, cfg=CFG, callbacks={"check_mt5_open_positions": lambda: 5}) == "open_position_mt5"
    assert apply_gates(sig, s, cfg=CFG, callbacks={"check_startup_cooldown": lambda now: True}) == "startup_cooldown"


# ─── Determinism: same input = same output ──────────────────


def test_apply_gates_is_pure_for_same_input():
    """Calling twice with same state should give same result. (DD pause is the
    one stateful exception — it mutates pause_counter. Test for that elsewhere.)"""
    s1 = GateState(day_filled_trades=2)
    s2 = GateState(day_filled_trades=2)
    sig = _sig("2026-06-17T10:00:00")
    assert apply_gates(sig, s1, cfg=CFG) == apply_gates(sig, s2, cfg=CFG)


# ─── Cooldown-arming-skip semantics (matches live Issue #19) ────


def test_cooldown_arms_on_fire_implicitly():
    """update_state_after_fire ALWAYS sets last_signal_time. That's the FIRE path."""
    s = GateState()
    sig = _sig("2026-06-17T10:00:00", sweep_time="2026-06-17T09:00:00", start_hour=8)
    update_state_after_fire(s, sig, expected_exit_seconds=240)
    assert s.last_signal_time == sig.date


def test_cooldown_arms_on_sl_too_close():
    """Per Issue #19: sl_too_close_to_price arms cooldown."""
    assert cooldown_arms_on_skip("sl_too_close_to_price") is True


def test_cooldown_arms_on_order_error():
    """Per Issue #19: any 'order_error*' skip arms cooldown."""
    assert cooldown_arms_on_skip("order_error_5004") is True
    assert cooldown_arms_on_skip("order_error_timeout") is True


def test_cooldown_arms_on_oanda_error():
    """Per Issue #19: any 'oanda_error*' skip arms cooldown."""
    assert cooldown_arms_on_skip("oanda_error_522") is True


def test_cooldown_does_not_arm_on_bias_block():
    """Bias filter blocks are 'didn't even try' — no cooldown."""
    assert cooldown_arms_on_skip("bias_block") is False


def test_cooldown_does_not_arm_on_range_too_small():
    assert cooldown_arms_on_skip("range_too_small") is False


def test_cooldown_does_not_arm_on_tp_too_close():
    assert cooldown_arms_on_skip("tp_too_close") is False


def test_cooldown_does_not_arm_on_none():
    assert cooldown_arms_on_skip(None) is False
    assert cooldown_arms_on_skip("") is False


# ─── Broker costs (Phase 6 #10) ───────────────────────────


def test_oil_commission_220_units_short_3min_trade():
    """Typical Oil Micro trade — 220 units (~2.2 lots), short, 3min hold."""
    costs = compute_broker_costs(
        units=220.0, direction="short", bars_held=1,
        broker_costs=OIL_COSTS,
    )
    # 2.2 lots × $7/lot RT = $15.40
    assert costs["lots"] == pytest.approx(2.2)
    assert costs["commission"] == pytest.approx(15.4)
    # bars_held=1 = 3min — no overnight crossing
    assert costs["nights_crossed"] == 0
    assert costs["swap"] == 0.0
    assert costs["total"] == pytest.approx(15.4)


def test_gold_commission_500_units_long():
    """Gold Micro typical 500-unit (5-lot) trade."""
    costs = compute_broker_costs(
        units=500.0, direction="long", bars_held=5,
        broker_costs=GOLD_COSTS,
    )
    # 5 lots × $6/lot RT = $30
    assert costs["lots"] == pytest.approx(5.0)
    assert costs["commission"] == pytest.approx(30.0)
    assert costs["swap"] == 0.0


def test_swap_overnight_long_oil():
    """Trade held >24hr with entry at 12:00 — crosses 1 rollover."""
    costs = compute_broker_costs(
        units=200.0, direction="long",
        bars_held=480,  # 480 × 3min = 1440min = 24hr
        broker_costs=OIL_COSTS,
        entry_hour_utc=12,
    )
    # 24hr at entry 12:00 → ends at 12:00 next day → crosses 1 rollover
    # Lots = 2, swap_long = -$3/lot/night, 1 night crossed → cost = $6
    assert costs["nights_crossed"] >= 1
    assert costs["swap"] == pytest.approx(2.0 * 3.0 * costs["nights_crossed"])
    assert costs["total"] == pytest.approx(costs["commission"] + costs["swap"])


def test_swap_short_smaller_than_long():
    """Short oil swap is cheaper than long oil swap."""
    long_cost = compute_broker_costs(
        units=200.0, direction="long", bars_held=480,
        broker_costs=OIL_COSTS, entry_hour_utc=12,
    )
    short_cost = compute_broker_costs(
        units=200.0, direction="short", bars_held=480,
        broker_costs=OIL_COSTS, entry_hour_utc=12,
    )
    assert short_cost["swap"] < long_cost["swap"]


def test_intraday_no_swap():
    """Trade held 4 hours mid-day (entry 10am, hold 4hr) → no rollover."""
    costs = compute_broker_costs(
        units=200.0, direction="long", bars_held=80,  # 4hr
        broker_costs=OIL_COSTS, entry_hour_utc=10,
    )
    assert costs["nights_crossed"] == 0
    assert costs["swap"] == 0.0


def test_late_day_entry_short_hold_no_swap():
    """Entry at 22:00 UTC, 1hr hold → ends 23:00, no rollover crossed."""
    costs = compute_broker_costs(
        units=200.0, direction="long", bars_held=20,  # 1hr
        broker_costs=OIL_COSTS, entry_hour_utc=22,
    )
    # Entry 22:00, end 23:00 — rollover at 00:00 NOT crossed
    assert costs["nights_crossed"] == 0


def test_late_day_entry_long_hold_crosses_rollover():
    """Entry at 22:00 UTC, 4hr hold → crosses 00:00 rollover."""
    costs = compute_broker_costs(
        units=200.0, direction="long", bars_held=80,  # 4hr
        broker_costs=OIL_COSTS, entry_hour_utc=22,
    )
    # Entry 22:00 + 4hr = 02:00 next day → 1 rollover crossed
    assert costs["nights_crossed"] == 1
    assert costs["swap"] == pytest.approx(2.0 * 3.0)  # 2 lots × $3 × 1 night


def test_zero_bars_held_only_commission():
    """Edge case: bars_held=0 (DATA_END or instant fill+exit) — commission only."""
    costs = compute_broker_costs(
        units=200.0, direction="long", bars_held=0,
        broker_costs=OIL_COSTS,
    )
    assert costs["nights_crossed"] == 0
    assert costs["swap"] == 0.0
    assert costs["commission"] == pytest.approx(2.0 * 7.0)  # 2 lots × $7
    assert costs["total"] == pytest.approx(14.0)


def test_fractional_lots_handled():
    """Position size may be fractional lots (e.g. 50 units = 0.5 lots)."""
    costs = compute_broker_costs(
        units=50.0, direction="long", bars_held=1,
        broker_costs=OIL_COSTS,
    )
    assert costs["lots"] == pytest.approx(0.5)
    assert costs["commission"] == pytest.approx(0.5 * 7.0)


def test_total_equals_commission_plus_swap():
    """Sanity: total = commission + swap, always."""
    for direction in ["long", "short"]:
        for bars in [1, 80, 480, 1000]:
            costs = compute_broker_costs(
                units=200.0, direction=direction, bars_held=bars,
                broker_costs=OIL_COSTS, entry_hour_utc=12,
            )
            assert costs["total"] == pytest.approx(costs["commission"] + costs["swap"]), \
                f"direction={direction} bars={bars}: total mismatch"
