"""End-to-end test of the orphan-reconciler dedup fix.

Verifies two behaviors:

1. INSERT … ON CONFLICT … DO NOTHING RETURNING id returns a row on
   first insert and an empty result on subsequent re-attempts. This
   is what the new `if not inserted: continue` branch relies on to
   suppress duplicate Telegram notifications.

2. The broadened pre-check (no trade_ref filter) sees ANY system's
   open position. If Oil Macro inserted broker_id X, Oil Micro's
   reconciler should now find X in db_open_ids and skip the INSERT
   entirely on its first cycle.

Pass criteria: each scenario prints `✓` and the script exits 0.
"""
import os
import psycopg2
from dotenv import load_dotenv


INSERT_SQL = """
INSERT INTO gd_trades (
    trade_ref, strategy, side, entry_time, entry_price,
    sl_price, tp_price, lot_size, units, mode, oanda_trade_id
)
VALUES (
    %s, %s, %s, NOW(),
    %s, %s, %s, %s, %s, 'live', %s
)
ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING
RETURNING id
"""

PRE_CHECK_SQL = """
SELECT oanda_trade_id FROM gd_trades
WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL
"""

TEST_BROKER_ID = "TEST_DEDUP_999999999"


def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return 1

    print(f"Connecting to: {db_url.split('@')[-1] if '@' in db_url else 'localhost'}")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM gd_trades WHERE oanda_trade_id LIKE 'TEST_DEDUP_%'"
            )

            # --- Scenario 1: RETURNING id distinguishes insert vs conflict ---
            print("\n--- Scenario 1: RETURNING id on insert + conflict ---")

            cur.execute(INSERT_SQL, (
                "OIL-AS-DEDUP-1", "alpha_sweep_oil", "SHORT",
                91.49, 92.40, 90.18, 0.63, 630, TEST_BROKER_ID,
            ))
            first = cur.fetchall()
            if len(first) != 1:
                print(f"  ✗ first INSERT expected 1 row, got {len(first)}")
                return 1
            print(f"  ✓ first INSERT returned {len(first)} row (id={first[0][0]})")

            cur.execute(INSERT_SQL, (
                "OIL-AS-DEDUP-2", "alpha_sweep_oil", "SHORT",
                91.49, 92.40, 90.18, 0.63, 630, TEST_BROKER_ID,
            ))
            second = cur.fetchall()
            if second:
                print(f"  ✗ second INSERT expected 0 rows, got {len(second)}")
                return 1
            print(f"  ✓ second INSERT returned 0 rows (ON CONFLICT triggered)")

            # --- Scenario 2: cross-system pre-check sees ALL open positions ---
            print("\n--- Scenario 2: pre-check sees cross-system positions ---")
            cur.execute(PRE_CHECK_SQL)
            db_ids = {str(row[0]) for row in cur.fetchall()}
            if TEST_BROKER_ID not in db_ids:
                print(f"  ✗ pre-check did NOT see {TEST_BROKER_ID}")
                print(f"     db_ids sample: {list(db_ids)[:5]}")
                return 1
            print(f"  ✓ pre-check sees {TEST_BROKER_ID} (would skip INSERT)")

            # Cleanup
            cur.execute(
                "DELETE FROM gd_trades WHERE oanda_trade_id LIKE 'TEST_DEDUP_%'"
            )
            print("\n  cleanup done")

    finally:
        conn.close()

    print("\n" + "=" * 50)
    print("✓ Orphan-reconciler dedup fix verified")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
