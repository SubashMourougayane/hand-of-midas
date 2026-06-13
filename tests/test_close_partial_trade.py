"""Unit tests for close_partial_trade — the Filter #7 live-side wrapper.

These tests stub _send_command (no real EA, no real MT5) and exercise:
  - unit→lot conversion across all 3 instrument families (XAU, BCO, FX-fallback)
  - command string format (CLOSE_PARTIAL|TICKET|LOTS) the EA will parse
  - response parsing for success / failure / timeout
  - lot-rounding edge cases (min 0.01, 2-decimal step)
  - lots→units round-trip (closed_volume + remaining_volume → closed_units + remaining_units)

This DOES NOT verify:
  - actual EA processing of the command (requires MT5 + recompiled EA)
  - MT5 broker actually nets the partial against the position
  - OnTradeTransaction writes closed_orders.json correctly
  - Any side effects in the live engine (DB UPDATE, Telegram, journal)

Those are runtime tests — covered by the Monday smoke trade, not here.
"""
import pytest
from unittest.mock import MagicMock

from backend.execution import mt5_executor


@pytest.fixture
def stub_send(monkeypatch):
    """Replace _send_command with a stub that captures the command string and
    returns a configurable response. Returns the stub so the test can:
      - read stub.calls (list of command strings sent)
      - set stub.response (dict the next call will return)
    """
    class _Stub:
        def __init__(self):
            self.calls = []
            self.response = {"success": True, "close_price": 0, "closed_volume": 0, "remaining_volume": 0}

        def __call__(self, cmd, timeout=10):
            self.calls.append(cmd)
            return self.response

    stub = _Stub()
    monkeypatch.setattr(mt5_executor, "_send_command", stub)
    return stub


# =============================================================================
# Unit→lot conversion
# =============================================================================

class TestUnitToLotConversion:
    """The conversion math must match place_market_order exactly — same
    units/lot ratios per instrument family. If these drift the partial close
    will close the wrong volume."""

    def test_xau_units_divide_by_100(self, stub_send):
        # 23 oz of gold → 0.23 lots
        stub_send.response = {"success": True, "close_price": 4080.50,
                              "closed_volume": 0.23, "remaining_volume": 0.23}
        result = mt5_executor.close_partial_trade("12345", 23, instrument="XAU_USD")
        # Sent command should encode 0.23 lots
        assert "CLOSE_PARTIAL|12345|0.23" in stub_send.calls[0], stub_send.calls[0]
        assert result["success"] is True

    def test_bco_units_divide_by_1000(self, stub_send):
        # 230 barrels of oil → 0.23 lots
        stub_send.response = {"success": True, "close_price": 75.50,
                              "closed_volume": 0.23, "remaining_volume": 0.23}
        result = mt5_executor.close_partial_trade("99999", 230, instrument="BCO_USD")
        assert "CLOSE_PARTIAL|99999|0.23" in stub_send.calls[0], stub_send.calls[0]
        assert result["success"] is True

    def test_fx_fallback_divide_by_100000(self, stub_send):
        # 50000 units of EUR_USD → 0.50 lots (fallback path)
        stub_send.response = {"success": True, "close_price": 1.0850,
                              "closed_volume": 0.50, "remaining_volume": 0.50}
        result = mt5_executor.close_partial_trade("88888", 50000, instrument="EUR_USD")
        assert "CLOSE_PARTIAL|88888|0.5" in stub_send.calls[0], stub_send.calls[0]


# =============================================================================
# Lot rounding (the floor that protects the broker from sub-min-lot rejects)
# =============================================================================

class TestLotRounding:
    """The XAU_USD floor of 0.01 lots is the broker's minimum tradeable size.
    Anything smaller than that gets clamped UP to 0.01 — which means closing
    1 oz of gold actually closes 0.01 lots = 1 oz (no clamp). But closing
    e.g. 0 oz would still send 0.01 lots — the live engine has its own
    guard `units < 2` to prevent that case from ever reaching here."""

    def test_minimum_lot_floor_001(self, stub_send):
        # 1 oz of gold → 0.01 lots (already at min, no rounding)
        stub_send.response = {"success": True, "close_price": 4080,
                              "closed_volume": 0.01, "remaining_volume": 0.01}
        mt5_executor.close_partial_trade("1", 1, instrument="XAU_USD")
        assert "CLOSE_PARTIAL|1|0.01" in stub_send.calls[0]

    def test_two_decimal_rounding(self, stub_send):
        # 33 oz of gold → 33/100 = 0.33 lots (no rounding needed)
        stub_send.response = {"success": True, "close_price": 4080,
                              "closed_volume": 0.33, "remaining_volume": 0.33}
        mt5_executor.close_partial_trade("1", 33, instrument="XAU_USD")
        assert "CLOSE_PARTIAL|1|0.33" in stub_send.calls[0]

    def test_rounding_drops_third_decimal(self, stub_send):
        # 27 barrels of oil → 0.027 lots → rounded to 0.03 lots
        # (real Oil Macro never sends fractional like this — paranoia coverage)
        stub_send.response = {"success": True, "close_price": 75,
                              "closed_volume": 0.03, "remaining_volume": 0.03}
        mt5_executor.close_partial_trade("1", 27, instrument="BCO_USD")
        assert "CLOSE_PARTIAL|1|0.03" in stub_send.calls[0]


# =============================================================================
# Response parsing — success path
# =============================================================================

class TestSuccessResponseParsing:
    def test_returns_close_price_from_response(self, stub_send):
        stub_send.response = {
            "success": True, "close_price": 4079.55,
            "closed_volume": 0.11, "remaining_volume": 0.12,
        }
        result = mt5_executor.close_partial_trade("12345", 11, instrument="XAU_USD")
        assert result["success"] is True
        assert result["close_price"] == 4079.55
        assert result["error"] is None

    def test_lots_to_units_round_trip_xau(self, stub_send):
        # EA reports 0.11 closed + 0.12 remaining → expect 11 + 12 units back
        stub_send.response = {
            "success": True, "close_price": 4079.55,
            "closed_volume": 0.11, "remaining_volume": 0.12,
        }
        result = mt5_executor.close_partial_trade("12345", 11, instrument="XAU_USD")
        assert result["closed_units"] == 11
        assert result["remaining_units"] == 12

    def test_lots_to_units_round_trip_bco(self, stub_send):
        # 0.05 closed + 0.07 remaining → 50 + 70 barrels
        stub_send.response = {
            "success": True, "close_price": 75.32,
            "closed_volume": 0.05, "remaining_volume": 0.07,
        }
        result = mt5_executor.close_partial_trade("12345", 50, instrument="BCO_USD")
        assert result["closed_units"] == 50
        assert result["remaining_units"] == 70

    def test_floating_point_safe_round_to_int(self, stub_send):
        # MT5 may return 0.1099999 due to float — round() must yield 11 not 10
        stub_send.response = {
            "success": True, "close_price": 4080.0,
            "closed_volume": 0.10999999, "remaining_volume": 0.11000001,
        }
        result = mt5_executor.close_partial_trade("1", 11, instrument="XAU_USD")
        assert result["closed_units"] == 11
        assert result["remaining_units"] == 11

    def test_missing_close_price_defaults_to_zero(self, stub_send):
        # If EA somehow omits close_price (malformed JSON), we still return success
        # but close_price=0; live engine has its own fallback to partial_target
        stub_send.response = {"success": True, "closed_volume": 0.11, "remaining_volume": 0.12}
        result = mt5_executor.close_partial_trade("1", 11, instrument="XAU_USD")
        assert result["success"] is True
        assert result["close_price"] == 0

    def test_missing_volumes_falls_back_to_input_lots(self, stub_send):
        # If EA omits closed_volume entirely, fall back to the requested lots
        stub_send.response = {"success": True, "close_price": 4080}
        result = mt5_executor.close_partial_trade("1", 23, instrument="XAU_USD")
        assert result["success"] is True
        # We requested 23 oz = 0.23 lots; closed_volume defaulted to that
        assert result["closed_units"] == 23
        # remaining_volume defaulted to 0
        assert result["remaining_units"] == 0


# =============================================================================
# Response parsing — failure paths
# =============================================================================

class TestFailureResponseParsing:
    def test_success_false_returns_error(self, stub_send):
        stub_send.response = {
            "success": False,
            "error": "Position 12345 not found",
        }
        result = mt5_executor.close_partial_trade("12345", 23, instrument="XAU_USD")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_success_false_uses_comment_if_no_error(self, stub_send):
        # OPEN/MODIFY/CLOSE responses use "comment" field; CLOSE_PARTIAL uses
        # "error". Be liberal: prefer "error", fall back to "comment".
        stub_send.response = {
            "success": False,
            "comment": "TRADE_RETCODE_INVALID_VOLUME",
            "retcode": 10014,
        }
        result = mt5_executor.close_partial_trade("12345", 23, instrument="XAU_USD")
        assert result["success"] is False
        assert "INVALID_VOLUME" in result["error"]
        assert result["retcode"] == 10014

    def test_success_false_unknown_when_no_error_or_comment(self, stub_send):
        stub_send.response = {"success": False}
        result = mt5_executor.close_partial_trade("12345", 23, instrument="XAU_USD")
        assert result["success"] is False
        assert result["error"] == "Unknown"

    def test_timeout_returns_error(self, stub_send):
        stub_send.response = None  # _send_command returns None on timeout
        result = mt5_executor.close_partial_trade("12345", 23, instrument="XAU_USD")
        assert result["success"] is False
        assert "Timeout" in result["error"]


# =============================================================================
# Real-world scenarios from the live engines
# =============================================================================

class TestLiveScenarios:
    """End-to-end against scenarios the live engine would actually send."""

    def test_gold_macro_partial_typical_trade(self, stub_send):
        # Gold Macro typical Alpha-Sweep: 23 oz position, partial 50% = 11 oz
        # halfway price 4080.50. EA reports 0.11 closed @ 4080.50, 0.12 remaining.
        stub_send.response = {
            "success": True, "close_price": 4080.50, "closed_volume": 0.11,
            "remaining_volume": 0.12, "partial": True,
        }
        result = mt5_executor.close_partial_trade("12345678", 11, instrument="XAU_USD")
        assert result["success"]
        assert result["close_price"] == 4080.50
        assert result["closed_units"] == 11
        assert result["remaining_units"] == 12
        # Sent command must be parseable by the EA's `n >= 3` branch
        sent = stub_send.calls[0]
        parts = sent.split("|")
        assert parts[0] == "CLOSE_PARTIAL"
        assert parts[1] == "12345678"
        assert float(parts[2]) == 0.11

    def test_oil_macro_partial_typical_trade(self, stub_send):
        # Oil Macro typical: 1000 barrels (1.00 lots), partial 50% = 500 barrels (0.50 lots)
        stub_send.response = {
            "success": True, "close_price": 75.42, "closed_volume": 0.50,
            "remaining_volume": 0.50, "partial": True,
        }
        result = mt5_executor.close_partial_trade("99999999", 500, instrument="BCO_USD")
        assert result["success"]
        assert result["closed_units"] == 500
        assert result["remaining_units"] == 500
        sent = stub_send.calls[0]
        assert sent == "CLOSE_PARTIAL|99999999|0.5"

    def test_oil_macro_min_lot_dust_rejection_passes_through(self, stub_send):
        # If the live engine sent `units_to_close=1` for an Oil position
        # (1 barrel = 0.001 lots, clamps to 0.01 = 10 barrels) the EA would
        # likely reject for "Remaining < min lot" if the position was tiny.
        # Test that the executor correctly relays that error.
        stub_send.response = {
            "success": False,
            "error": "Remaining 0.0050 < min lot 0.0100 after partial — would orphan dust",
        }
        result = mt5_executor.close_partial_trade("12345", 1, instrument="BCO_USD")
        assert result["success"] is False
        assert "orphan dust" in result["error"]
