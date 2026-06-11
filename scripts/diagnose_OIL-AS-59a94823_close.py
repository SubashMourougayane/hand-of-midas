"""Diagnose the closure (or not) of OIL-AS-59a94823 — the Oil Macro LONG
that fired at 12:18 UTC on 2026-06-11 with entry $91.51, SL $91.08, TP $94.32.

Mirrors scripts/diagnose_OIL-AS-5434644d_close.py from earlier today.
"""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

QUERIES = [
    ("Current gd_trades row",
     "SELECT id, trade_ref, strategy, oanda_trade_id, side, entry_price, sl_price, "
     "tp_price, units, entry_time, exit_time, exit_price, exit_reason, pnl_usd "
     "FROM gd_trades WHERE trade_ref = 'OIL-AS-59a94823';"),
    ("Latest 30 journal events for this trade or its oanda_id",
     "SELECT timestamp, event_type, trade_ref, price, context "
     "FROM gd_journal "
     "WHERE trade_ref = 'OIL-AS-59a94823' "
     "   OR (context->>'oanda_id' IS NOT NULL "
     "       AND trade_ref LIKE 'OIL-AS-%') "
     "ORDER BY timestamp DESC LIMIT 30;"),
    ("Latest 15 journal events for alpha_sweep_oil since 12:00 UTC today",
     "SELECT timestamp, event_type, trade_ref "
     "FROM gd_journal "
     "WHERE strategy = 'alpha_sweep_oil' "
     "  AND timestamp >= '2026-06-11 12:00:00+00' "
     "ORDER BY timestamp DESC LIMIT 15;"),
    ("All Oil Macro open trades right now",
     "SELECT id, trade_ref, oanda_trade_id, entry_time, exit_time, exit_reason "
     "FROM gd_trades "
     "WHERE strategy = 'alpha_sweep_oil' AND exit_time IS NULL;"),
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
                else:
                    for r in rows:
                        for k, v in r.items():
                            print(f"  {k}: {v}")
                        print("  ---")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
