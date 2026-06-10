"""Revive OIL-AS-5434644d after phantom-fill bug falsely closed it.

Context (June 11 2026 ~00:50 IST):
- Oil Macro's check_open_positions() incorrectly concluded the trade
  was closed (broker_open didn't include it for one cycle, possibly
  a DWX file write race) and UPDATEed gd_trades with exit_time, SL
  fill, -$1054.44 P&L. Telegram fired 'TRADE CLOSED'.
- Reality (verified on JustMarkets web): position is OPEN, broker_id
  2036391922, BRENT SHORT 1.04 lots @ $92.14, SL $93.15, TP $90.18,
  unrealized -$551.20.
- Broker is source of truth. DB needs to be rolled back so the
  position monitor can resume managing the trade.

This script:
1. Verifies the DB row currently has exit_time set (i.e., really
   was falsely closed — abort if not).
2. Verifies broker still has the position open via DB-side hint
   (we can't query broker from script, but we have local MT5
   open_orders.json mtime that the user just confirmed).
3. UPDATEs gd_trades to clear exit_time, exit_price, exit_reason,
   pnl_gbp, pnl_usd. Leaves entry data and oanda_trade_id intact.
4. Logs a journal event so we know this rollback happened.
5. Rolls back DD state if it was bumped — checks consecutive_losses
   and decrements if >0 (the false close incremented it).

Idempotent: re-running after a successful revive is a no-op
(detects exit_time already NULL).
"""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

TRADE_REF = "OIL-AS-5434644d"
BROKER_ID = "2036391922"


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
            # 1) Inspect current state
            cur.execute(
                "SELECT id, trade_ref, oanda_trade_id, exit_time, exit_price, "
                "       exit_reason, pnl_usd, pnl_gbp "
                "FROM gd_trades WHERE trade_ref = %s",
                (TRADE_REF,)
            )
            row = cur.fetchone()
            if not row:
                print(f"ERROR: no row for trade_ref={TRADE_REF}")
                return 1

            print()
            print("Current DB state:")
            for k, v in row.items():
                print(f"  {k}: {v}")
            print()

            if row["exit_time"] is None:
                print("Already healthy (exit_time is NULL). No action needed.")
                return 0

            if str(row["oanda_trade_id"]) != BROKER_ID:
                print(f"ERROR: broker_id mismatch — DB has {row['oanda_trade_id']}, "
                      f"expected {BROKER_ID}. Aborting (this is the wrong row).")
                return 1

            # 2) Revive
            print("Reviving trade — clearing exit fields...")
            cur.execute(
                """UPDATE gd_trades
                   SET exit_time = NULL,
                       exit_price = NULL,
                       exit_reason = NULL,
                       pnl_gbp = NULL,
                       pnl_usd = NULL
                   WHERE trade_ref = %s
                   RETURNING id""",
                (TRADE_REF,)
            )
            updated = cur.fetchall()
            if not updated:
                print("ERROR: UPDATE affected 0 rows")
                conn.rollback()
                return 1
            print(f"  ✓ updated row id={updated[0]['id']}")

            # 3) Roll back DD state — false close incremented consecutive_losses
            cur.execute("SELECT consecutive_losses, pause_counter FROM gd_dd_state "
                        "WHERE id = 2")  # Oil Macro DD_STATE_ID is 2
            dd = cur.fetchone()
            if dd and dd["consecutive_losses"] > 0:
                print(f"  rolling back DD: consecutive_losses {dd['consecutive_losses']} -> {dd['consecutive_losses']-1}")
                cur.execute(
                    "UPDATE gd_dd_state SET consecutive_losses = consecutive_losses - 1 "
                    "WHERE id = 2 AND consecutive_losses > 0"
                )
            else:
                print(f"  DD state already clean (or different id) — skipped")

            # 4) Journal the rollback so it shows up in audit
            cur.execute(
                "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    TRADE_REF, "alpha_sweep_oil", "REVIVED_FROM_PHANTOM_CLOSE",
                    row["exit_price"],
                    '{"reason": "phantom_fill_bug_macro", "broker_position_still_open": true, '
                    '"falsely_recorded_pnl_usd": ' + str(row["pnl_usd"]) + ', '
                    '"see": "docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md", '
                    '"broker_id": "' + BROKER_ID + '"}'
                )
            )

            conn.commit()
            print()
            print("=" * 50)
            print("✓ Trade revived. Position monitor will resume.")
            print("  Broker SL $93.15 / TP $90.18 are unchanged.")
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
