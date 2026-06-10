"""Print results of orphan-index diagnostic queries.

Unlike run_sql.py (which only commits, doesn't fetch), this script
runs each SELECT and prints rows so we can see whether the partial
unique index exists, whether constraints are in place, and whether
the orphan broker ticket from June 10 has any DB row.
"""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


QUERIES = [
    ("Indexes on gd_trades matching 'oanda'",
     "SELECT indexname, indexdef FROM pg_indexes "
     "WHERE tablename='gd_trades' AND indexname LIKE '%oanda%';"),
    ("All indexes on gd_trades",
     "SELECT indexname, indexdef FROM pg_indexes "
     "WHERE tablename='gd_trades' ORDER BY indexname;"),
    ("Unique / PK constraints on gd_trades",
     "SELECT conname, pg_get_constraintdef(oid) AS definition "
     "FROM pg_constraint "
     "WHERE conrelid='gd_trades'::regclass AND contype IN ('u','p');"),
    ("Column widths for strategy / oanda_trade_id / trade_ref",
     "SELECT column_name, data_type, character_maximum_length "
     "FROM information_schema.columns "
     "WHERE table_name='gd_trades' "
     "AND column_name IN ('strategy','oanda_trade_id','trade_ref');"),
    ("Does orphan broker ticket 2034232555 have a DB row?",
     "SELECT trade_ref, strategy, oanda_trade_id, entry_time, exit_time, "
     "exit_reason, pnl_usd FROM gd_trades WHERE oanda_trade_id='2034232555';"),
]


def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set in .env")
        return

    print(f"Connecting to: {db_url.split('@')[-1] if '@' in db_url else 'localhost'}")
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
