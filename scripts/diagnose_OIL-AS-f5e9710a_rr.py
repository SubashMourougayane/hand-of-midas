"""Diagnose why OIL-AS-f5e9710a was taken despite R:R 0.69:1 (below the
0.8 gate at backend-oil/scanner/scheduler.py:259).

The gate code:
    if tp - entry < risk * 0.8:
        continue  # skip signal

For OIL-AS-f5e9710a (per /api/oil/state):
    entry=92.95, sl=90.96, tp=94.32
    risk = 1.99,  reward = 1.37,  reward / (risk * 0.8) = 0.86 → fails gate

Possible explanations the diagnostic distinguishes:
  (a) The signal-time entry was DIFFERENT (slippage adjusted). The gate
      ran on a tighter "tp - entry" and PASSED, then the actual fill
      executed at a worse price. We'd see this in gd_signals or
      gd_journal where the original entry pre-slippage is logged.
  (b) The gate is bypassed somewhere — bug.
  (c) An ENTRY_FILLED journal context shows the actual computed values
      that went into the gate at signal-fire time.

This script pulls everything available:
- The gd_signals row(s) for this trade window
- The ENTRY_FILLED journal event for this trade_ref
- All journal events from the entry minute (signal-time logs)
"""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

QUERIES = [
    ("gd_trades current row",
     "SELECT id, trade_ref, oanda_trade_id, side, entry_price, sl_price, "
     "tp_price, units, entry_time, exit_time, exit_price, exit_reason, pnl_usd "
     "FROM gd_trades WHERE trade_ref = 'OIL-AS-f5e9710a';"),

    ("gd_signals around entry minute (14:45 server / 12:45 UTC)",
     "SELECT timestamp, strategy, direction, entry_price, sl_price, tp_price, "
     "taken, skip_reason, trade_ref "
     "FROM gd_signals "
     "WHERE strategy = 'alpha_sweep_oil' "
     "  AND timestamp >= '2026-06-11 14:40:00+02' "
     "  AND timestamp <= '2026-06-11 14:50:00+02' "
     "ORDER BY timestamp;"),

    ("gd_journal — every event for this trade_ref",
     "SELECT timestamp, event_type, price, context "
     "FROM gd_journal "
     "WHERE trade_ref = 'OIL-AS-f5e9710a' "
     "ORDER BY timestamp;"),

    ("gd_journal — sweep/engulf detection logs around entry",
     "SELECT timestamp, event_type, trade_ref, price, context "
     "FROM gd_journal "
     "WHERE strategy = 'alpha_sweep_oil' "
     "  AND timestamp >= '2026-06-11 14:40:00+02' "
     "  AND timestamp <= '2026-06-11 14:50:00+02' "
     "ORDER BY timestamp;"),
]


def main():
    load_dotenv()
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for label, sql in QUERIES:
                print()
                print("=" * 70)
                print(label)
                print("=" * 70)
                cur.execute(sql)
                rows = cur.fetchall()
                if not rows:
                    print("(no rows)")
                    continue
                for r in rows:
                    for k, v in r.items():
                        print(f"  {k}: {v}")
                    print("  ---")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
