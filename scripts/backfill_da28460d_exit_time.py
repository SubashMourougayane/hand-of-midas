"""One-shot: correct the exit_time on GD-MI-da28460d.

Bug: mt5_executor.get_trade_details() line 379 stored the EA's GMT+3 server
time as if it were UTC, making DB exit_time 3h ahead of reality. Fixed in
the same commit that runs this script. This backfills the one row that
was corrupted by the bug between the DWX OnTradeTransaction recompile
(2026-06-12 ~12:42 UTC) and the bug fix.

Verification before update:
- broker (closed_orders.json): close_time '2026.06.12 16:43:15' (server GMT+3)
- broker (real UTC):           '2026-06-12 13:43:15Z'
- DB exit_time (buggy):        '2026-06-12 18:43:15+02:00' (= 16:43:15 UTC, off by +3h)
- DB exit_time (corrected):    '2026-06-12 13:43:15+00:00'

Usage on VPS:
    python scripts\\backfill_da28460d_exit_time.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db import execute

TRADE_REF = "GD-MI-da28460d"

before = execute(
    "SELECT trade_ref, exit_time FROM gd_trades WHERE trade_ref = %s",
    (TRADE_REF,), fetch=True,
)
print(f"BEFORE: {before}")

if not before:
    print(f"FATAL: trade {TRADE_REF} not found")
    sys.exit(1)

# Subtract exactly 3 hours — the JustMarkets server-offset.
result = execute(
    "UPDATE gd_trades SET exit_time = exit_time - INTERVAL '3 hours' "
    "WHERE trade_ref = %s",
    (TRADE_REF,),
)
print(f"UPDATE result: {result}")

after = execute(
    "SELECT trade_ref, exit_time, "
    "EXTRACT(EPOCH FROM (exit_time - entry_time))/60 AS dur_min "
    "FROM gd_trades WHERE trade_ref = %s",
    (TRADE_REF,), fetch=True,
)
print(f"AFTER:  {after}")
print()
print("Sanity check: dur_min should be ~7.2 (was ~187 before fix)")
