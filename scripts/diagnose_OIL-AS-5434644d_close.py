"""Diagnose what happened to OIL-AS-5434644d at the broker close."""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

QUERIES = [
    ("Current gd_trades row",
     "SELECT id, trade_ref, strategy, oanda_trade_id, side, entry_price, sl_price, "
     "tp_price, units, entry_time, exit_time, exit_price, exit_reason, pnl_usd "
     "FROM gd_trades WHERE trade_ref = 'OIL-AS-5434644d';"),
    ("Latest 30 journal events for this trade or oanda_id",
     "SELECT timestamp, event_type, trade_ref, price, context "
     "FROM gd_journal "
     "WHERE trade_ref = 'OIL-AS-5434644d' "
     "   OR context->>'oanda_id' = '2036391922' "
     "ORDER BY timestamp DESC LIMIT 30;"),
    ("Latest 15 journal events for alpha_sweep_oil strategy",
     "SELECT timestamp, event_type, trade_ref "
     "FROM gd_journal "
     "WHERE strategy = 'alpha_sweep_oil' "
     "ORDER BY timestamp DESC LIMIT 15;"),
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
