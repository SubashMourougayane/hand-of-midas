"""Diagnose why orphan reconciler keeps re-firing for the same broker_id."""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

QUERIES = [
    ("Rows in gd_trades for broker_id 2036391922",
     "SELECT id, trade_ref, oanda_trade_id, side, entry_price, sl_price, tp_price, "
     "entry_time, exit_time, exit_reason, pnl_usd, mode "
     "FROM gd_trades WHERE oanda_trade_id = '2036391922' OR trade_ref LIKE '%36391922%' "
     "ORDER BY id;"),
    ("Type of oanda_trade_id (string vs int — for ON CONFLICT match)",
     "SELECT oanda_trade_id, pg_typeof(oanda_trade_id) AS db_type "
     "FROM gd_trades WHERE oanda_trade_id = '2036391922' LIMIT 3;"),
    ("All open Oil Micro positions in DB",
     "SELECT trade_ref, oanda_trade_id, entry_time, exit_time "
     "FROM gd_trades WHERE trade_ref LIKE 'OIL-MI-%' AND exit_time IS NULL;"),
    ("All ORPHAN_ADOPTED events for 2036391922 today",
     "SELECT timestamp, event_type, trade_ref, context->>'broker_id' AS bid "
     "FROM gd_journal "
     "WHERE event_type='ORPHAN_ADOPTED' "
     "  AND context->>'broker_id'='2036391922' "
     "ORDER BY timestamp;"),
]


def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(db_url)
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
