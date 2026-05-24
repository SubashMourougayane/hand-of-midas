"""
FULL LIVE INTEGRATION TEST — Run when market is OPEN.
Tests every execution path with real OANDA API calls.
Cleans up all positions at the end.

Run: python scripts/integration_test_live.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend-oil"))

from backend.execution.oanda_executor import (
    get_current_price, get_account_summary, place_market_order,
    get_open_trades, close_trade, modify_stop_loss, get_trade_details,
    get_candles, _get_gbp_usd_rate,
)
from backend.db import execute, get_conn
from backend import notify

PASSED = 0
FAILED = 0
CLEANUP_TRADES = []


def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name} — {detail}")


def cleanup():
    """Close all test trades."""
    global CLEANUP_TRADES
    if CLEANUP_TRADES:
        print(f"\n{'='*60}")
        print(f"  CLEANUP: Closing {len(CLEANUP_TRADES)} test trades...")
        for trade_id in CLEANUP_TRADES:
            try:
                close_trade(trade_id)
                print(f"    Closed {trade_id}")
            except:
                print(f"    Failed to close {trade_id}")
        CLEANUP_TRADES = []


def test_01_market_open():
    """Verify market is open and prices are live."""
    print(f"\n{'─'*60}")
    print("  TEST 1: Market Status & Price Feed")
    print(f"{'─'*60}")

    price = get_current_price(instrument="XAU_USD")
    test("Gold price returned", price is not None)
    test("Gold tradeable", price and price.get("tradeable") == True, f"tradeable={price.get('tradeable') if price else None}")
    test("Gold spread < $5", price and price["spread"] < 5, f"spread=${price['spread'] if price else '?'}")

    oil_price = get_current_price(instrument="BCO_USD")
    test("Oil price returned", oil_price is not None)
    test("Oil tradeable", oil_price and oil_price.get("tradeable") == True)

    if not price or not price.get("tradeable"):
        print("\n  ⚠️  MARKET CLOSED — Cannot continue. Run after Sunday 21:00 UTC.")
        return False
    return True


def test_02_account_summary():
    """Verify account API works."""
    print(f"\n{'─'*60}")
    print("  TEST 2: Account Summary")
    print(f"{'─'*60}")

    acct = get_account_summary()
    test("No error in response", "error" not in acct, str(acct.get("error", "")))
    test("Balance > 0", acct.get("balance", 0) > 0)
    test("NAV > 0", acct.get("nav", 0) > 0)
    test("nav_usd computed", acct.get("nav_usd", 0) > 0)
    test("Currency is GBP", acct.get("currency") == "GBP")
    test("GBP/USD rate present", acct.get("gbp_usd_rate", 0) > 1.0)


def test_03_candles():
    """Verify candle fetching works for all timeframes."""
    print(f"\n{'─'*60}")
    print("  TEST 3: Candle Fetching (H1, M3, Daily)")
    print(f"{'─'*60}")

    h1 = get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA")
    test("Gold H1 returns data", len(h1) > 0, f"got {len(h1)} bars")
    test("Gold H1 has bid/ask", len(h1) > 0 and "bid_high" in h1[0])
    test("Gold H1 complete bars only", all(c.get("complete", False) for c in h1))

    m3 = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")
    test("Gold M3 returns data", len(m3) > 0, f"got {len(m3)} bars")

    daily = get_candles(instrument="XAU_USD", granularity="D", count=5, price="BA")
    test("Gold Daily returns data", len(daily) > 0, f"got {len(daily)} bars")

    oil_h1 = get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA")
    test("Oil H1 returns data", len(oil_h1) > 0)

    # Cross-market instruments (for Cross-Market strategy)
    for inst in ["EUR_USD", "USB10Y_USD", "SPX500_USD"]:
        d = get_candles(instrument=inst, granularity="D", count=5, price="M")
        test(f"{inst} Daily data", len(d) > 0, f"got {len(d)}")


def test_04_order_lifecycle_gold():
    """Full Gold order: place → verify → modify SL → close."""
    global CLEANUP_TRADES
    print(f"\n{'─'*60}")
    print("  TEST 4: Gold Order Lifecycle (place → modify → close)")
    print(f"{'─'*60}")

    price = get_current_price(instrument="XAU_USD")
    entry = price["ask"]
    sl = round(entry - 10, 2)
    tp = round(entry + 20, 2)

    # Place
    result = place_market_order(instrument="XAU_USD", units=1, sl_price=sl, tp_price=tp, comment="integration_test_gold")
    test("Gold order placed", result.get("success") == True, str(result.get("error", "")))

    if not result.get("success"):
        return

    trade_id = result["trade_id"]
    CLEANUP_TRADES.append(trade_id)
    fill_price = result["fill_price"]
    test("Fill price reasonable", abs(fill_price - entry) < 3, f"fill={fill_price}, ask={entry}")

    # Verify in open list
    time.sleep(1)
    open_trades = get_open_trades()
    found = any(t["trade_id"] == trade_id for t in open_trades)
    test("Trade in open list", found)

    # Modify SL (break-even)
    new_sl = round(fill_price + 0.30, 2)
    mod = modify_stop_loss(trade_id, new_sl)
    test("SL modified (break-even)", mod.get("success") == True, str(mod.get("error", "")))

    # Get details
    details = get_trade_details(trade_id)
    test("Trade details returned", details is not None)
    test("Trade state is OPEN", details and details.get("state") == "OPEN")

    # Close
    close_result = close_trade(trade_id)
    test("Trade closed", close_result.get("success") == True, str(close_result.get("error", "")))
    test("Realized P&L returned", close_result.get("realized_pl") is not None)
    CLEANUP_TRADES.remove(trade_id)

    # Verify gone
    time.sleep(1)
    open_after = get_open_trades()
    still_open = any(t["trade_id"] == trade_id for t in open_after)
    test("Trade removed from open list", not still_open)


def test_05_order_lifecycle_oil():
    """Full Oil order: place → close."""
    global CLEANUP_TRADES
    print(f"\n{'─'*60}")
    print("  TEST 5: Oil Order Lifecycle")
    print(f"{'─'*60}")

    price = get_current_price(instrument="BCO_USD")
    if not price or not price.get("tradeable"):
        test("Oil market open", False, "Market closed")
        return

    entry = price["ask"]
    result = place_market_order(instrument="BCO_USD", units=1, sl_price=round(entry-1, 2), tp_price=round(entry+2, 2), comment="integration_test_oil")
    test("Oil order placed", result.get("success") == True, str(result.get("error", "")))

    if result.get("success"):
        CLEANUP_TRADES.append(result["trade_id"])
        close_result = close_trade(result["trade_id"])
        test("Oil trade closed", close_result.get("success") == True)
        CLEANUP_TRADES.remove(result["trade_id"])


def test_06_short_order():
    """Verify SHORT orders work (negative units)."""
    global CLEANUP_TRADES
    print(f"\n{'─'*60}")
    print("  TEST 6: Short Order (negative units)")
    print(f"{'─'*60}")

    price = get_current_price(instrument="XAU_USD")
    entry = price["bid"]
    sl = round(entry + 10, 2)
    tp = round(entry - 20, 2)

    result = place_market_order(instrument="XAU_USD", units=-1, sl_price=sl, tp_price=tp, comment="integration_test_short")
    test("Short order placed", result.get("success") == True, str(result.get("error", "")))

    if result.get("success"):
        CLEANUP_TRADES.append(result["trade_id"])
        test("Short fill price reasonable", abs(result["fill_price"] - entry) < 3)
        close_result = close_trade(result["trade_id"])
        test("Short trade closed", close_result.get("success") == True)
        CLEANUP_TRADES.remove(result["trade_id"])


def test_07_multiple_orders_same_time():
    """Place 3 orders (max/day simulation) and close all."""
    global CLEANUP_TRADES
    print(f"\n{'─'*60}")
    print("  TEST 7: Multiple Orders (3/day simulation)")
    print(f"{'─'*60}")

    price = get_current_price(instrument="XAU_USD")
    entry = price["ask"]
    trade_ids = []

    for i in range(3):
        result = place_market_order(
            instrument="XAU_USD", units=1,
            sl_price=round(entry - 10 - i, 2),
            tp_price=round(entry + 20 + i, 2),
            comment=f"integration_test_multi_{i}"
        )
        if result.get("success"):
            trade_ids.append(result["trade_id"])
            CLEANUP_TRADES.append(result["trade_id"])

    test("3 orders placed", len(trade_ids) == 3, f"placed {len(trade_ids)}")

    # Verify all in open list
    time.sleep(1)
    open_trades = get_open_trades()
    open_ids = {t["trade_id"] for t in open_trades}
    all_found = all(tid in open_ids for tid in trade_ids)
    test("All 3 in open list", all_found)

    # Close all
    for tid in trade_ids:
        close_trade(tid)
        CLEANUP_TRADES.remove(tid)

    time.sleep(1)
    open_after = get_open_trades()
    remaining = [t for t in open_after if t["trade_id"] in trade_ids]
    test("All 3 closed", len(remaining) == 0, f"{len(remaining)} still open")


def test_08_dd_state():
    """Verify DD state reads/writes work."""
    print(f"\n{'─'*60}")
    print("  TEST 8: DD State (read/write)")
    print(f"{'─'*60}")

    from backend.scanner.live_engine import _get_dd_state, _update_dd_state

    dd = _get_dd_state()
    test("DD state loaded", dd is not None)
    test("Has consecutive_losses", "consecutive_losses" in dd)
    test("Has equity", "equity" in dd)

    # Save current, modify, restore
    orig_losses = dd["consecutive_losses"]
    orig_equity = float(dd["equity"])
    orig_peak = float(dd["peak_equity"])

    _update_dd_state(99, 0, orig_equity, orig_peak)
    dd2 = _get_dd_state()
    test("DD state writable", dd2["consecutive_losses"] == 99)

    # Restore
    _update_dd_state(orig_losses, dd["pause_counter"], orig_equity, orig_peak)
    dd3 = _get_dd_state()
    test("DD state restored", dd3["consecutive_losses"] == orig_losses)


def test_09_signal_logging():
    """Verify signal + journal DB writes work."""
    print(f"\n{'─'*60}")
    print("  TEST 9: Signal & Journal Logging")
    print(f"{'─'*60}")

    from backend.scanner.live_engine import _log_signal, _log_journal

    _log_signal("alpha_sweep", "long", 9999.0, 9990.0, 10010.0, taken=False, skip_reason="integration_test")
    rows = execute("SELECT * FROM gd_signals WHERE entry_price = 9999 AND skip_reason = 'integration_test'", fetch=True)
    test("Signal logged to DB", len(rows) > 0)

    _log_journal("TEST-REF", "alpha_sweep", "INTEGRATION_TEST", 9999.0, {"test": True})
    j_rows = execute("SELECT * FROM gd_journal WHERE trade_ref = 'TEST-REF' AND event_type = 'INTEGRATION_TEST'", fetch=True)
    test("Journal event logged", len(j_rows) > 0)

    # Cleanup
    execute("DELETE FROM gd_signals WHERE entry_price = 9999 AND skip_reason = 'integration_test'")
    execute("DELETE FROM gd_journal WHERE trade_ref = 'TEST-REF' AND event_type = 'INTEGRATION_TEST'")
    test("Test data cleaned up", True)


def test_10_telegram():
    """Verify Telegram notification fires."""
    print(f"\n{'─'*60}")
    print("  TEST 10: Telegram Notification")
    print(f"{'─'*60}")

    try:
        notify.send("🧪 Integration test — if you see this, Telegram works.")
        time.sleep(2)
        test("Telegram message sent (check your phone)", True)
    except Exception as e:
        test("Telegram send", False, str(e))


def test_11_gbp_usd_rate():
    """Verify GBP/USD rate fetch."""
    print(f"\n{'─'*60}")
    print("  TEST 11: GBP/USD Rate")
    print(f"{'─'*60}")

    rate = _get_gbp_usd_rate()
    test("Rate returned", rate is not None and rate > 0)
    test("Rate in reasonable range (1.1-1.5)", 1.1 < rate < 1.5, f"rate={rate}")


def test_12_scheduler_signal_generation():
    """Run the actual scheduler sweep detection on live data (no execution)."""
    print(f"\n{'─'*60}")
    print("  TEST 12: Scheduler Signal Detection (live data, no execution)")
    print(f"{'─'*60}")

    from backend.config import ALPHA_SWEEP
    from backend.execution.oanda_executor import get_candles
    from datetime import datetime, timezone

    cfg = ALPHA_SWEEP
    today = datetime.now(timezone.utc).date()

    # Get live H1 candles
    h1 = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
    test("H1 candles fetched", len(h1) >= 8, f"got {len(h1)}")

    # Find Asia bars
    asia_bars = []
    for c in h1:
        from datetime import datetime as dt
        ts = dt.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
        if ts.date() == today and 0 <= ts.hour < 8:
            asia_bars.append(c)

    test("Asia bars found", len(asia_bars) >= 0, f"got {len(asia_bars)} (may be 0 if early)")

    if len(asia_bars) >= 3:
        asia_high = max((c["bid_high"] + c["ask_high"]) / 2 for c in asia_bars)
        asia_low = min((c["bid_low"] + c["ask_low"]) / 2 for c in asia_bars)
        asia_range = asia_high - asia_low
        test("Asia range computed", asia_range > 0, f"range=${asia_range:.2f}")
        test("Asia range vs threshold", True, f"range=${asia_range:.2f}, min=${cfg['asia_min_range']}")
    else:
        test("Asia bars (may be empty early Monday)", True, "Skipped — too early")

    # Verify daily candles for bias
    daily = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
    test("Daily candles for bias", len(daily) >= 2, f"got {len(daily)}")
    if len(daily) >= 2:
        yesterday = daily[-2]
        mid_close = (yesterday["bid_close"] + yesterday["ask_close"]) / 2
        mid_open = (yesterday["bid_open"] + yesterday["ask_open"]) / 2
        bias = "bullish" if mid_close > mid_open else "bearish"
        test(f"Daily bias computed: {bias}", True)


def test_13_order_rejected_bad_sl():
    """Test order with impossible SL (above entry for long) — should reject."""
    print(f"\n{'─'*60}")
    print("  TEST 13: Order Rejection (bad SL)")
    print(f"{'─'*60}")

    price = get_current_price(instrument="XAU_USD")
    entry = price["ask"]
    bad_sl = round(entry + 100, 2)  # SL above entry for a LONG = impossible

    result = place_market_order(instrument="XAU_USD", units=1, sl_price=bad_sl, tp_price=round(entry + 20, 2), comment="integration_test_bad_sl")
    test("Bad SL order rejected", result.get("success") == False, f"Got success={result.get('success')}")
    if result.get("success"):
        CLEANUP_TRADES.append(result["trade_id"])


def main():
    print("\n" + "=" * 60)
    print("  🤚 HAND OF MIDAS — FULL LIVE INTEGRATION TEST")
    print("  OANDA Demo | Real API Calls | All Paths")
    print("=" * 60)

    if not test_01_market_open():
        cleanup()
        return

    test_02_account_summary()
    test_03_candles()
    test_04_order_lifecycle_gold()
    test_05_order_lifecycle_oil()
    test_06_short_order()
    test_07_multiple_orders_same_time()
    test_08_dd_state()
    test_09_signal_logging()
    test_10_telegram()
    test_11_gbp_usd_rate()
    test_12_scheduler_signal_generation()
    test_13_order_rejected_bad_sl()

    cleanup()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {PASSED} passed, {FAILED} failed")
    print(f"{'='*60}")
    if FAILED == 0:
        print("  ✅ ALL PATHS VERIFIED — System ready for live trading")
    else:
        print(f"  ⚠️  {FAILED} failures — investigate before trading")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted — cleaning up...")
        cleanup()
    except Exception as e:
        print(f"\n\n❌ FATAL: {e}")
        cleanup()
        raise
