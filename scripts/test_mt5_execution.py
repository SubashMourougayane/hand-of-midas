"""
Test MT5 execution layer — place, modify, and close a small order.
Run on VPS where DWX EA is active.

Usage:
    python scripts/test_mt5_execution.py
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.execution import (
    get_current_price, get_account_summary, get_open_trades,
    place_market_order, modify_stop_loss, close_trade, is_connected,
)

print("=" * 60)
print("  MT5 EXECUTION TEST")
print("=" * 60)

# Step 1: Check connectivity
print("\n[1/6] Checking DWX connection...")
connected = is_connected()
print(f"  Connected: {connected}")
if not connected:
    print("  FAIL: DWX not connected. Is the EA running?")
    sys.exit(1)

# Step 2: Get price
print("\n[2/6] Getting current XAU_USD price...")
price = get_current_price(instrument="XAU_USD")
if not price:
    print("  FAIL: No price data")
    sys.exit(1)
print(f"  Bid: {price['bid']}, Ask: {price['ask']}, Spread: {price['spread']:.2f}")

# Step 3: Get account
print("\n[3/6] Getting account summary...")
acct = get_account_summary()
if not acct:
    print("  FAIL: No account data")
    sys.exit(1)
print(f"  Balance: ${acct['balance']}, Equity: ${acct['nav']}, Currency: {acct['currency']}")

# Step 4: Place a TINY order (1 unit = 0.01 lot)
print("\n[4/6] Placing BUY 1 unit XAU_USD (minimum size)...")
sl_price = round(price['bid'] - 50, 2)  # $50 below = wide SL (won't hit)
tp_price = round(price['ask'] + 50, 2)  # $50 above = wide TP (won't hit)
print(f"  Entry: market, SL: {sl_price}, TP: {tp_price}")

result = place_market_order(
    instrument="XAU_USD",
    units=1,  # Minimum: 1 unit = 0.01 lot
    sl=sl_price,
    tp=tp_price,
    comment="TEST_ORDER_DELETE_ME",
)

if not result.get("success"):
    print(f"  FAIL: {result.get('error', 'Unknown error')}")
    print(f"  Full result: {result}")
    sys.exit(1)

trade_id = result["trade_id"]
fill_price = result["fill_price"]
print(f"  SUCCESS! Trade ID: {trade_id}, Fill: ${fill_price}")

# Step 5: Modify SL (move closer)
print("\n[5/6] Modifying SL to entry - $10...")
time.sleep(2)  # Give EA time to process
new_sl = round(fill_price - 10, 2)
print(f"  New SL: {new_sl}")

mod_result = modify_stop_loss(trade_id, new_sl)
if mod_result.get("success"):
    print(f"  SUCCESS! SL modified to {new_sl}")
else:
    print(f"  FAIL: {mod_result.get('error', 'Unknown')}")
    print("  (Continuing to close test...)")

# Step 6: Close the trade
print("\n[6/6] Closing test trade...")
time.sleep(5)  # Wait longer for EA to process modify first

# Verify trade still exists before closing
print(f"  Checking if trade {trade_id} is still open...")
open_trades = get_open_trades()
open_ids = [t.get("id") or t.get("trade_id") for t in open_trades] if open_trades else []
print(f"  Open trade IDs: {open_ids}")

if str(trade_id) not in [str(x) for x in open_ids]:
    print(f"  Trade {trade_id} NOT in open trades list!")
    print(f"  Possible reasons:")
    print(f"    - SL was hit immediately after modification (SL={new_sl}, current bid ~{price['bid']})")
    print(f"    - Trade was closed by broker (margin/overnight)")
    print(f"    - DWX EA lost track of the position")
    close_result = {"success": False, "error": "Position not in open_trades"}
else:
    print(f"  Trade confirmed open. Clearing stale response + waiting...")
    # Delete stale last_response.json so close reads fresh
    import os as _os
    resp_path = _os.path.join(_os.getenv("DWX_DIR", _os.path.expanduser("~/Documents/DWX/DWX_Server_MT5")), "last_response.json")
    if _os.path.exists(resp_path):
        _os.remove(resp_path)
        print(f"  Cleared {resp_path}")
    time.sleep(3)
    print(f"  Sending close command...")
    close_result = close_trade(trade_id)
    if close_result.get("success"):
        print(f"  SUCCESS! Closed at ${close_result.get('close_price', '?')}, P&L: {close_result.get('realized_pl', '?')}")
    else:
        print(f"  FAIL: {close_result.get('error', 'Unknown')}")
        print(f"  Full response: {close_result}")
        print("  WARNING: Trade may still be open! Check MT5 manually.")

# Summary
print("\n" + "=" * 60)
print("  TEST COMPLETE")
print("=" * 60)
print(f"  Place order:  {'PASS' if result.get('success') else 'FAIL'}")
print(f"  Modify SL:    {'PASS' if mod_result.get('success') else 'FAIL'}")
print(f"  Close trade:  {'PASS' if close_result.get('success') else 'FAIL'}")

all_pass = result.get("success") and mod_result.get("success") and close_result.get("success")
print(f"\n  {'ALL TESTS PASSED — execution layer working!' if all_pass else 'SOME TESTS FAILED — check above'}")
