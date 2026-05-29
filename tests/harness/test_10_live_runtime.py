"""TEST 10: Live Runtime Tests — Uses REAL MT5/DWX running locally.

These tests execute against the ACTUAL DWX bridge (market_data.json, open_orders.json).
Requires: MT5 running locally with DWX EA loaded.

Tests:
- Real price feed works
- Real candle fetch works
- Thread safety with actual file I/O
- Order placement + cancellation (REAL order on demo account)
- Full scheduler cycle with real data
"""
import sys
import os
import threading
import time
import json
import pytest
import numpy as np
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))

os.environ["EXECUTOR"] = "mt5"

DWX_DIR = os.path.expanduser(
    "~/Library/Application Support/net.metaquotes.wine.metatrader5/"
    "drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
)


def dwx_available():
    """Check if DWX is running locally."""
    market_file = os.path.join(DWX_DIR, "market_data.json")
    if not os.path.exists(market_file):
        return False
    # Check file is fresh (modified within last 60 seconds)
    age = time.time() - os.path.getmtime(market_file)
    return age < 60


skip_no_dwx = pytest.mark.skipif(
    not dwx_available(),
    reason="DWX/MT5 not running locally — skip live runtime tests"
)


@skip_no_dwx
class TestLivePriceFeed:
    """10a: Real price data from MT5."""

    def test_current_price_returns_valid(self):
        """get_current_price returns bid/ask/mid with reasonable values."""
        from backend.execution.mt5_executor import get_current_price
        price = get_current_price("XAU_USD")
        assert price is not None, "No price returned"
        assert price["bid"] > 1000, f"Gold bid={price['bid']} — too low"
        assert price["ask"] > price["bid"], "Ask must be > bid"
        assert price["spread"] < 5.0, f"Spread={price['spread']} — too wide"
        assert price["tradeable"] is True

    def test_oil_price_returns_valid(self):
        from backend.execution.mt5_executor import get_current_price
        price = get_current_price("BCO_USD")
        assert price is not None
        assert 30 < price["bid"] < 200, f"Oil bid={price['bid']} — out of range"


@skip_no_dwx
class TestLiveCandleFetch:
    """10b: Real candle data from MT5."""

    def test_h1_candles_returned(self):
        """get_candles returns H1 bars with bid/ask prices."""
        from backend.execution.mt5_executor import get_candles
        candles = get_candles("XAU_USD", "H1", 24, "BA")
        assert len(candles) >= 10, f"Only {len(candles)} H1 candles — expected 24"
        c = candles[-1]
        assert "bid_open" in c and "ask_close" in c
        assert c["bid_high"] >= c["bid_low"]
        assert c["ask_high"] >= c["ask_low"]

    def test_m3_candles_returned(self):
        from backend.execution.mt5_executor import get_candles
        candles = get_candles("XAU_USD", "M3", 50, "BA")
        assert len(candles) >= 20, f"Only {len(candles)} M3 candles"

    def test_daily_candles_returned(self):
        from backend.execution.mt5_executor import get_candles
        candles = get_candles("XAU_USD", "D", 5, "BA")
        assert len(candles) >= 2, "Need at least 2 daily candles for bias"

    def test_candle_timestamps_chronological(self):
        from backend.execution.mt5_executor import get_candles
        candles = get_candles("XAU_USD", "H1", 24, "BA")
        timestamps = [c["timestamp"] for c in candles]
        assert timestamps == sorted(timestamps), "Candles not in chronological order"


@skip_no_dwx
class TestLiveAccountInfo:
    """10c: Account data accessible."""

    def test_account_summary(self):
        from backend.execution.mt5_executor import get_account_summary
        acc = get_account_summary()
        assert acc is not None
        assert acc["balance"] > 0, "Balance must be positive"
        assert acc["currency"] == "USD"
        assert "nav_usd" in acc


@skip_no_dwx
class TestB4ThreadSafetyLive:
    """10d: REAL thread safety test with actual DWX file I/O."""

    def test_concurrent_price_reads_dont_corrupt(self):
        """Two threads reading market_data.json simultaneously — no corruption."""
        from backend.execution.mt5_executor import get_current_price

        results = {"t1": None, "t2": None, "errors": []}

        def read_price(key):
            try:
                p = get_current_price("XAU_USD")
                results[key] = p
            except Exception as e:
                results["errors"].append(str(e))

        t1 = threading.Thread(target=read_price, args=("t1",))
        t2 = threading.Thread(target=read_price, args=("t2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not results["errors"], f"Errors during concurrent read: {results['errors']}"
        assert results["t1"] is not None
        assert results["t2"] is not None
        # Both should get valid prices (no partial read / JSON corruption)
        assert results["t1"]["bid"] > 1000
        assert results["t2"]["bid"] > 1000

    def test_concurrent_candle_reads(self):
        """Two threads reading bars JSON simultaneously."""
        from backend.execution.mt5_executor import get_candles

        results = {"t1": None, "t2": None, "errors": []}

        def read_candles(key, granularity):
            try:
                c = get_candles("XAU_USD", granularity, 10, "BA")
                results[key] = len(c)
            except Exception as e:
                results["errors"].append(f"{key}: {str(e)}")

        t1 = threading.Thread(target=read_candles, args=("t1", "H1"))
        t2 = threading.Thread(target=read_candles, args=("t2", "M3"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not results["errors"], f"Errors: {results['errors']}"
        assert results["t1"] >= 5
        assert results["t2"] >= 5


@skip_no_dwx
class TestLiveSchedulerCycle:
    """10e: Run ONE scheduler cycle with real MT5 data (no order placement)."""

    def test_scan_produces_valid_windows(self):
        """Scheduler can detect active windows from real H1 data."""
        from backend.execution.mt5_executor import get_candles, get_current_price
        from config import MICRO_ALPHA_SWEEP as cfg

        h1 = get_candles("XAU_USD", "H1", 24, "BA")
        price = get_current_price("XAU_USD")
        assert len(h1) >= 10
        assert price is not None

        # Simulate window detection (same logic as scheduler)
        now = datetime.now(timezone.utc)
        consol_hours_val = cfg["consol_hours"]
        scan_gap = cfg.get("scan_gap_hours", 2)

        active_windows = 0
        for start_hour in range(0, 24, scan_gap):
            end_hour = (start_hour + consol_hours_val) % 24
            # Check if consolidation is done
            diff = (now.hour - end_hour) % 24
            if 0 < diff <= 12:
                active_windows += 1

        assert active_windows >= 1, "No active windows detected — scheduler would do nothing"
        assert active_windows <= 12, f"Too many windows ({active_windows}) — logic error"

    def test_scan_builds_valid_range(self):
        """Real H1 bars produce a valid consolidation range."""
        from backend.execution.mt5_executor import get_candles
        from config import MICRO_ALPHA_SWEEP as cfg

        h1 = get_candles("XAU_USD", "H1", 24, "BA")
        now = datetime.now(timezone.utc)

        # Pick a window that should be active
        for start_hour in range(0, 24, 2):
            end_hour = (start_hour + 4) % 24
            diff = (now.hour - end_hour) % 24
            if not (0 < diff <= 12):
                continue

            # Get consolidation bars for this window
            def hours_in_range(s, e):
                hrs = []
                h = s
                while h != e:
                    hrs.append(h % 24)
                    h = (h + 1) % 24
                return hrs

            consol_hrs = hours_in_range(start_hour, end_hour)
            consol_bars = [c for c in h1 if int(c["timestamp"][11:13]) in consol_hrs]

            if len(consol_bars) < 2:
                continue

            range_high = max((c["bid_high"] + c["ask_high"]) / 2 for c in consol_bars)
            range_low = min((c["bid_low"] + c["ask_low"]) / 2 for c in consol_bars)
            consol_range = range_high - range_low

            assert consol_range >= 0, "Negative range — impossible"
            if consol_range >= cfg.get("min_range", cfg.get("asia_min_range", 5.0)):
                # Valid tradeable range found
                assert range_high > range_low
                return

        # If no valid range found (very flat market), that's OK
        pytest.skip("No valid consolidation range in current market — flat day")


@skip_no_dwx
class TestLiveOrderExecution:
    """10f: Place and immediately cancel a REAL order on demo account.

    WARNING: This places a real order on the demo account.
    It uses a very small size (0.01 lots) with a tight SL to minimize risk.
    The order is cancelled within 2 seconds.
    """

    def test_place_and_close_order(self):
        """Place 0.01 lot order, verify fill, then close immediately."""
        from backend.execution.mt5_executor import (
            place_market_order, get_open_trades, close_trade, get_current_price
        )

        price = get_current_price("XAU_USD")
        if not price or not price.get("tradeable"):
            pytest.skip("Market closed — can't test order execution")

        # Place tiny SHORT order: 1 unit (0.01 lots), SL $50 away, TP $50 away
        # This won't trigger SL/TP in the 2 seconds before we close it
        entry_ask = price["ask"]
        sl = entry_ask + 50  # Very far SL
        tp = entry_ask - 50  # Very far TP

        result = place_market_order(
            instrument="XAU_USD",
            units=-1,  # 1 unit SHORT (0.01 lots)
            sl=sl,
            tp=tp,
            comment="harness_test_DO_NOT_KEEP"
        )

        if not result.get("success"):
            # Order might be rejected (market closed, insufficient margin, etc)
            pytest.skip(f"Order rejected: {result.get('error', 'unknown')}")

        trade_id = result["trade_id"]
        assert trade_id and str(trade_id) != "0", f"Invalid trade_id: {trade_id}"
        assert result["fill_price"] > 1000, f"Fill price too low: {result['fill_price']}"

        # Verify it appears in open_orders
        time.sleep(0.5)
        open_trades = get_open_trades()
        our_trade = [t for t in open_trades if str(t["id"]) == str(trade_id)]
        assert len(our_trade) == 1, f"Trade {trade_id} not in open_orders after fill"

        # CLOSE IT IMMEDIATELY
        close_result = close_trade(trade_id)
        assert close_result.get("success"), f"Failed to close: {close_result.get('error')}"

        # Verify it's gone
        time.sleep(0.5)
        open_trades_after = get_open_trades()
        remaining = [t for t in open_trades_after if str(t["id"]) == str(trade_id)]
        assert len(remaining) == 0, f"Trade {trade_id} still open after close"

    def test_modify_sl_works(self):
        """Place order, modify SL, verify SL changed, then close."""
        from backend.execution.mt5_executor import (
            place_market_order, modify_stop_loss, get_open_trades, close_trade, get_current_price
        )

        price = get_current_price("XAU_USD")
        if not price or not price.get("tradeable"):
            pytest.skip("Market closed")

        entry_ask = price["ask"]
        original_sl = entry_ask + 50
        tp = entry_ask - 50

        result = place_market_order("XAU_USD", -1, sl=original_sl, tp=tp,
                                   comment="harness_test_sl_modify")
        if not result.get("success"):
            pytest.skip(f"Order rejected: {result.get('error')}")

        trade_id = result["trade_id"]
        time.sleep(0.5)

        # Modify SL to a new value
        new_sl = entry_ask + 30
        mod_result = modify_stop_loss(trade_id, new_sl)
        assert mod_result.get("success"), f"SL modify failed: {mod_result.get('error')}"

        # Verify SL changed in open_orders
        time.sleep(0.5)
        open_trades = get_open_trades()
        our_trade = [t for t in open_trades if str(t["id"]) == str(trade_id)]
        if our_trade:
            actual_sl = our_trade[0].get("sl", 0)
            assert abs(actual_sl - new_sl) < 1.0, \
                f"SL not modified: expected {new_sl}, got {actual_sl}"

        # CLOSE
        close_trade(trade_id)
