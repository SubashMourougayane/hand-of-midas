"""One-shot smoke test for DWX OnTradeTransaction handler.

Places a 0.01 lot XAUUSD trade with magic=200000, waits 5s, closes it.
If OnTradeTransaction is live, closed_orders.json will appear/grow within
seconds of the close.

USAGE on VPS:
    cd C:\\hand-of-midas
    python scripts\\smoke_test_dwx_close.py

This is throwaway — runs the public mt5_executor functions, places a
real (small) trade on the live demo account. Will lose ~spread cost
($0.10 × 0.01 lot = ~$0.10).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.execution.mt5_executor import (
    place_market_order,
    close_trade,
    get_current_price,
    DWX_DIR,
)

INSTRUMENT = "XAU_USD"
UNITS = 1  # 0.01 lot for XAU (1 oz / 100 oz/lot)


def main():
    print(f"DWX_DIR: {DWX_DIR}")
    closed_path = os.path.join(DWX_DIR, "closed_orders.json")
    print(f"closed_orders.json before: exists={os.path.exists(closed_path)}, "
          f"size={os.path.getsize(closed_path) if os.path.exists(closed_path) else 0}")

    print("\nFetching live price...")
    price = get_current_price(INSTRUMENT)
    print(f"  price={price}")

    print(f"\nPlacing market BUY {UNITS} units of {INSTRUMENT} (no SL/TP)...")
    result = place_market_order(INSTRUMENT, units=UNITS, sl=0, tp=0, comment="dwx_smoke_test")
    print(f"  result: {result}")

    if not result.get("success"):
        print(f"\nFAILED to place trade: {result.get('error')}")
        sys.exit(1)

    trade_id = result["trade_id"]
    print(f"\n✅ Trade placed: ticket={trade_id}, fill={result.get('fill_price')}")

    print("\nSleeping 3s before close...")
    time.sleep(3)

    print(f"Closing ticket {trade_id}...")
    close_result = close_trade(trade_id)
    print(f"  result: {close_result}")

    if not close_result.get("success"):
        print(f"\nFAILED to close trade: {close_result.get('error')}")
        sys.exit(2)

    print(f"\n✅ Trade closed: close_price={close_result.get('close_price')}, "
          f"profit={close_result.get('realized_pl')}")

    # Wait briefly for OnTradeTransaction to fire and write the file
    print("\nWaiting 3s for OnTradeTransaction to write closed_orders.json...")
    time.sleep(3)

    print(f"\nclosed_orders.json after: exists={os.path.exists(closed_path)}, "
          f"size={os.path.getsize(closed_path) if os.path.exists(closed_path) else 0}")

    if os.path.exists(closed_path):
        size = os.path.getsize(closed_path)
        print(f"\n✅ closed_orders.json EXISTS ({size} bytes)")
        print("\nLast 1KB of file:")
        with open(closed_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        print(content[-1024:])
        if trade_id in content:
            print(f"\n🎯 SUCCESS: trade_id {trade_id} found in closed_orders.json — "
                  f"OnTradeTransaction is LIVE")
        else:
            print(f"\n⚠️  closed_orders.json exists but doesn't contain trade_id {trade_id}")
    else:
        print(f"\n❌ closed_orders.json STILL MISSING after EA-magic close — "
              f"OnTradeTransaction is NOT firing. Recompile didn't take effect.")


if __name__ == "__main__":
    main()
