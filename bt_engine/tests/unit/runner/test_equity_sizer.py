"""Unit tests for Model B 1.5% asymmetric monthly equity sizer.

Causality + bug-defense tests:
  - Equity only changes on closed trade pnl (no mark-to-market)
  - Month rolls when ts crosses boundary, NEVER preemptively
  - Skim only on positive month-end equity (asymmetric)
  - Loss months carry equity forward (eat losses)
  - Wipe-out at equity <= 0 blocks further orders
  - lot_size = risk_dollar / (stop_distance × contract)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bt_engine.runner.equity_sizer import (
    EquitySizer, EquitySizerConfig, CONTRACT_SIZE,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_initial_state():
    s = EquitySizer()
    assert s.equity() == 5000.0
    assert s.lifetime_skim() == 0.0
    assert s.state.current_month is None  # seeded on first action


def test_size_order_xau_basic():
    """$5,000 × 1.5% = $75 risk. XAU 1 lot = 100oz. Stop $1.50 → lot = 75/(1.5*100) = 0.50."""
    s = EquitySizer()
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=1.50, ts=_ts("2026-07-01 12:00:00+00:00"))
    assert lot == 0.50


def test_size_order_xau_tight_stop():
    """Stop $3.00 → lot = 75/(3*100) = 0.25."""
    s = EquitySizer()
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=3.00, ts=_ts("2026-07-01 12:00:00+00:00"))
    assert lot == 0.25


def test_size_order_rejects_below_min_risk_xau():
    """XAU stop < $0.50 → rejected (broker un-tradeable)."""
    s = EquitySizer()
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=0.30, ts=_ts("2026-07-01 12:00:00+00:00"))
    assert lot == 0.0


def test_size_order_rejects_below_min_lot():
    """If computed lot < 0.01, reject."""
    s = EquitySizer(EquitySizerConfig(start_balance=5000.0, risk_pct=0.015))
    # risk_$ = $75, stop = $1000 → lot = 75/(1000*100) = 0.00075 < 0.01
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=1000.0, ts=_ts("2026-07-01 12:00:00+00:00"))
    assert lot == 0.0


def test_size_order_eur_basic():
    """EUR 1 lot = 100,000 units. $5k * 1.5% = $75. Stop 0.001 (10 pips at 0.0001) → lot = 75/(0.001*100000) = 0.75."""
    s = EquitySizer()
    lot = s.size_order(symbol="EURUSD.ecn", stop_distance=0.001, ts=_ts("2026-07-01 12:00:00+00:00"))
    assert lot == 0.75


def test_size_uses_current_equity_not_start():
    """Risk should track CURRENT equity, not start balance."""
    s = EquitySizer()
    # Simulate a winning trade: +$1,000 → equity = $6,000
    s.on_trade_closed(pnl_dollars=1000.0, close_ts=_ts("2026-07-05 12:00:00+00:00"))
    assert s.equity() == 6000.0
    # Now sizing should use $6,000 → risk = $90 → lot = 90/(1.5*100) = 0.60
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=1.50, ts=_ts("2026-07-06 12:00:00+00:00"))
    assert lot == 0.60


def test_month_skim_on_positive_close():
    """Profitable month-end → skim back to $5k, record skim."""
    s = EquitySizer()
    s.on_trade_closed(pnl_dollars=2500.0, close_ts=_ts("2026-07-15 12:00:00+00:00"))
    assert s.equity() == 7500.0
    # Cross into August → month roll, skim $2500
    s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-08-01 09:00:00+00:00"))
    assert s.equity() == 5000.0  # skimmed
    assert s.lifetime_skim() == 2500.0
    assert len(s.state.skim_history) == 1
    assert s.state.skim_history[0]["skim_amount"] == 2500.0
    assert s.state.skim_history[0]["month_closed"][:7] == "2026-07"


def test_month_eat_losses_no_skim():
    """Loss month-end → KEEP equity, NO skim, trade smaller next month."""
    s = EquitySizer()
    s.on_trade_closed(pnl_dollars=-2000.0, close_ts=_ts("2026-07-15 12:00:00+00:00"))
    assert s.equity() == 3000.0
    # Cross into August → equity stays at $3,000
    s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-08-01 09:00:00+00:00"))
    assert s.equity() == 3000.0  # NOT reset
    assert s.lifetime_skim() == 0.0
    # Now risk = $3000 * 0.015 = $45. lot = 45/(1*100) = 0.45 (rounded down to 0.45)
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-08-02 09:00:00+00:00"))
    assert abs(lot - 0.45) < 0.001


def test_wipe_out_blocks_orders():
    """If equity hits 0, no further orders."""
    s = EquitySizer()
    s.on_trade_closed(pnl_dollars=-5000.0, close_ts=_ts("2026-07-15 12:00:00+00:00"))
    assert s.equity() == 0.0
    # Order in same month should detect wipe AT size_order time when equity <= 0
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-07-16 09:00:00+00:00"))
    assert lot == 0.0
    assert s.state.wiped is True


def test_no_month_roll_within_month():
    """Multiple ts within same month → no roll, no skim."""
    s = EquitySizer()
    s.on_trade_closed(pnl_dollars=500.0, close_ts=_ts("2026-07-10 12:00:00+00:00"))
    s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-07-20 12:00:00+00:00"))
    assert s.equity() == 5500.0
    assert s.lifetime_skim() == 0.0
    assert len(s.state.skim_history) == 0


def test_month_roll_only_on_first_action_in_new_month():
    """Roll triggered by either size_order OR on_trade_closed when crossing boundary."""
    s = EquitySizer()
    s.on_trade_closed(pnl_dollars=1000.0, close_ts=_ts("2026-07-29 18:00:00+00:00"))
    assert s.equity() == 6000.0  # mid-July
    # Trade closed in August → triggers roll on on_trade_closed
    s.on_trade_closed(pnl_dollars=200.0, close_ts=_ts("2026-08-02 10:00:00+00:00"))
    # After roll: skim $1000 (July profit), then apply +$200 August trade
    assert s.equity() == 5200.0
    assert s.lifetime_skim() == 1000.0


def test_timezone_handling():
    """ts MUST be UTC. Non-UTC tz gets converted; naive gets localized to UTC."""
    s = EquitySizer()
    # Naive ts → assumed UTC
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0,
                          ts=datetime(2026, 7, 1, 12, 0, 0))  # naive
    assert lot > 0  # ran without error


def test_unknown_symbol_raises():
    s = EquitySizer()
    with pytest.raises(ValueError, match="Unknown contract size"):
        s.size_order(symbol="UNKNOWN.fx", stop_distance=1.0,
                       ts=_ts("2026-07-01 12:00:00+00:00"))


def test_negative_stop_rejected():
    s = EquitySizer()
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=-1.0,
                          ts=_ts("2026-07-01 12:00:00+00:00"))
    assert lot == 0.0


def test_contract_size_xau_100():
    assert CONTRACT_SIZE["XAUUSD.ecn"] == 100.0


def test_contract_size_eur_100k():
    assert CONTRACT_SIZE["EURUSD.ecn"] == 100_000.0


def test_lifetime_skim_aggregates_across_months():
    """Multiple skim events accumulate."""
    s = EquitySizer()
    # Month 1: profitable
    s.on_trade_closed(pnl_dollars=1500.0, close_ts=_ts("2026-07-15 12:00:00+00:00"))
    s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-08-01 09:00:00+00:00"))
    # Month 2: profitable
    s.on_trade_closed(pnl_dollars=2000.0, close_ts=_ts("2026-08-20 12:00:00+00:00"))
    s.size_order(symbol="XAUUSD.ecn", stop_distance=1.0, ts=_ts("2026-09-01 09:00:00+00:00"))
    assert s.lifetime_skim() == 3500.0
    assert len(s.state.skim_history) == 2


# ---------------- F2: restart equity hydration ----------------

def test_hydrate_equity_resets_to_broker_balance():
    """F2: a restart must size off the live broker balance, not the fixed seed."""
    s = EquitySizer(EquitySizerConfig(start_balance=10000.0))
    assert s.equity() == 10000.0            # seeded to config on init
    ok = s.hydrate_equity(10526.77, source="mt5_account_info")
    assert ok is True
    assert s.equity() == pytest.approx(10526.77)
    assert s.state.month_start_equity == pytest.approx(10526.77)


def test_hydrate_then_size_uses_hydrated_equity():
    """1.5% risk must be computed off the hydrated balance, not the seed."""
    s = EquitySizer(EquitySizerConfig(start_balance=10000.0, risk_pct=0.015))
    s.hydrate_equity(20000.0)
    # risk_$ = 20000 * 0.015 = 300; lot = 300 / (10 * 100) = 0.30
    lot = s.size_order(symbol="XAUUSD.ecn", stop_distance=10.0,
                       ts=_ts("2026-07-05 12:00:00+00:00"))
    assert lot == pytest.approx(0.30)


def test_hydrate_rejects_nonpositive_and_nan():
    s = EquitySizer(EquitySizerConfig(start_balance=10000.0))
    assert s.hydrate_equity(0.0) is False
    assert s.hydrate_equity(-50.0) is False
    assert s.hydrate_equity(float("nan")) is False
    assert s.hydrate_equity(float("inf")) is False
    assert s.equity() == 10000.0            # untouched on bad input


def test_hydrate_does_not_disturb_month_or_skim_history():
    s = EquitySizer(EquitySizerConfig(start_balance=10000.0))
    s.on_trade_closed(pnl_dollars=500.0, close_ts=_ts("2026-07-15 12:00:00+00:00"))
    before_month = s.state.current_month
    before_hist = list(s.state.skim_history)
    s.hydrate_equity(12345.0)
    assert s.state.current_month == before_month
    assert s.state.skim_history == before_hist
