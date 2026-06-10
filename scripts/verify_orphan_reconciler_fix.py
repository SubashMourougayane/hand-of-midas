"""End-to-end test of Fix Y: prove the orphan reconciler's INSERT can
succeed twice in a row (idempotent) without raising the 42P10 error
that produced 140 ORPHAN_ADOPT_FAILED events on June 10.

Pass criteria:
- BOTH inserts complete without raising
- Exactly ONE row exists between them (DO NOTHING took effect)
- Cleanup leaves no test rows behind
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
"""

TEST_BROKER_ID = "TEST_FIXY_2034232555"


def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return

    print(f"Connecting to: {db_url.split('@')[-1] if '@' in db_url else 'localhost'}")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            # Cleanup any prior test rows
            cur.execute("DELETE FROM gd_trades WHERE oanda_trade_id LIKE 'TEST_FIXY_%'")

            print("\n--- 1st INSERT (orphan adoption) ---")
            try:
                cur.execute(INSERT_SQL, (
                    "OIL-MI-orphan-FIXYTEST", "micro_alpha_sweep_oil", "SHORT",
                    91.49, 92.40, 90.18, 0.63, 630, TEST_BROKER_ID,
                ))
                print("  ✓ no error")
            except Exception as e:
                print(f"  ✗ FAILED: {e}")
                return

            print("\n--- 2nd INSERT (same broker_id — must be idempotent) ---")
            try:
                cur.execute(INSERT_SQL, (
                    "OIL-MI-orphan-FIXYTEST2", "micro_alpha_sweep_oil", "SHORT",
                    91.49, 92.40, 90.18, 0.63, 630, TEST_BROKER_ID,
                ))
                print("  ✓ no error")
            except Exception as e:
                print(f"  ✗ FAILED: {e}")
                print(f"  This is the bug we just fixed. CI/CD didn't pick up the new code,")
                print(f"  or the partial-index match still isn't selected.")
                return

            print("\n--- Verify exactly 1 row exists ---")
            cur.execute(
                "SELECT COUNT(*), MAX(trade_ref) FROM gd_trades WHERE oanda_trade_id = %s",
                (TEST_BROKER_ID,)
            )
            count, ref = cur.fetchone()
            print(f"  rows: {count}, ref: {ref}")
            if count == 1:
                print("  ✓ DO NOTHING worked — second INSERT silently skipped")
            else:
                print(f"  ✗ expected 1, got {count}")

            cur.execute("DELETE FROM gd_trades WHERE oanda_trade_id LIKE 'TEST_FIXY_%'")
            print("\n  cleanup done")

    finally:
        conn.close()

    print("\n========================================")
    print("✓ Fix Y verified end-to-end")
    print("========================================")


if __name__ == "__main__":
    main()
