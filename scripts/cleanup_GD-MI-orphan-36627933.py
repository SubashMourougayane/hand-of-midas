"""Cleanup the ghost orphan row GD-MI-orphan-36627933 created by the
reconciler at 22:10 server time on 2026-06-10.

Context:
- Harness test_10_live_runtime.py / test_11_full_lifecycle.py placed real
  XAUUSD orders against the shared JustMarkets demo account.
- Reconciler saw broker_id 2036627933 (a 0.01-lot harness Sell) in
  open_orders.json before the harness closed it.
- Reconciler adopted with units=0 (because int(-0.01) truncates to 0).
- Harness closed the position seconds later, but EA never wrote a
  closed_orders.json entry for it (filter likely missed it because the
  trade was Client-closed, not magic-200000-flagged).
- Position monitor logs EXIT_AMBIGUOUS every minute since.

Fix going forward (deployed in this session):
- Reconciler skips positions with comment starting with 'harness' (case-
  insensitive) so future harness runs won't pollute.
- Reconciler also skips positions with units<1 (rounded), so any
  sub-lot adoption attempt is rejected regardless of source.

This script marks the existing ghost row as ORPHAN_CLEANUP so the
position monitor stops spamming EXIT_AMBIGUOUS. Idempotent.
"""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

TRADE_REF = "GD-MI-orphan-36627933"
BROKER_ID = "2036627933"


def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return 1

    print(f"Connecting to: {db_url.split('@')[-1] if '@' in db_url else 'localhost'}")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, trade_ref, oanda_trade_id, units, exit_time, exit_reason, pnl_usd "
                "FROM gd_trades WHERE trade_ref = %s",
                (TRADE_REF,)
            )
            row = cur.fetchone()
            if not row:
                print(f"No row for {TRADE_REF} — already cleaned up.")
                return 0

            print()
            print("Current state:")
            for k, v in row.items():
                print(f"  {k}: {v}")
            print()

            if str(row["oanda_trade_id"]) != BROKER_ID:
                print(f"ERROR: broker_id mismatch — DB has {row['oanda_trade_id']}, "
                      f"expected {BROKER_ID}. Aborting.")
                return 1

            if row["exit_time"] is not None:
                print(f"Already cleaned up (exit_time={row['exit_time']}, "
                      f"exit_reason={row['exit_reason']}). No action.")
                return 0

            if row["units"] != 0:
                print(f"WARNING: units={row['units']} (expected 0 for ghost row). "
                      f"Aborting — this script only handles the units=0 ghost case.")
                return 1

            print(f"Marking ghost row as ORPHAN_CLEANUP...")
            cur.execute(
                """UPDATE gd_trades
                   SET exit_time = NOW(),
                       exit_price = entry_price,
                       exit_reason = 'ORPHAN_CLEANUP',
                       pnl_gbp = 0,
                       pnl_usd = 0
                   WHERE trade_ref = %s
                   RETURNING id""",
                (TRADE_REF,)
            )
            updated = cur.fetchall()
            if not updated:
                print("ERROR: UPDATE affected 0 rows")
                conn.rollback()
                return 1

            cur.execute(
                "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    TRADE_REF, "micro_alpha_sweep", "ORPHAN_CLEANUP",
                    None,
                    '{"reason": "ghost_row_units_0_no_broker_match", '
                    '"see": "scripts/cleanup_GD-MI-orphan-36627933.py", '
                    '"broker_id": "' + BROKER_ID + '"}'
                )
            )

            conn.commit()
            print()
            print("=" * 50)
            print("✓ Ghost row marked closed. Position monitor will stop")
            print("  spamming EXIT_AMBIGUOUS for this trade.")
            print("=" * 50)
            return 0

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
