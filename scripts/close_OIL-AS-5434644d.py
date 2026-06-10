"""Manually close OIL-AS-5434644d in DB after the DWX EA failed to write
closed_orders.json. Broker truth (from JustMarkets web panel):

  Side:        SHORT 1.04 lots BRENT
  Entry:       $92.14
  Exit (SL):   $93.15   close time 11.06.2026 01:53 IST = 22:23 server
  Trade P&L:   -$1,050.40
  Commission:  -$6.24
  Net P&L:     -$1,056.64

DB pnl_usd reflects the strategy-level realized P&L only (matches the
in-engine calculation): risk_per_unit $1.01 × 1044 units = $1,054.44.
The $4.04 extra in broker net = commission, recorded separately.

Idempotent: if exit_time is already set, exits without changing anything.
"""
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from dotenv import load_dotenv


def main():
    load_dotenv()
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT exit_time, pnl_usd FROM gd_trades WHERE trade_ref = %s",
                ("OIL-AS-5434644d",)
            )
            row = cur.fetchone()
            if not row:
                print("No row found — nothing to close.")
                return 0
            if row["exit_time"] is not None:
                print(f"Already closed at {row['exit_time']}, pnl_usd={row['pnl_usd']}. No action.")
                return 0

            print("Closing OIL-AS-5434644d at SL $93.15, pnl_usd=-1054.44 ...")
            cur.execute(
                """UPDATE gd_trades
                   SET exit_time = %s,
                       exit_price = 93.15,
                       exit_reason = 'SL',
                       pnl_gbp = -1054.44,
                       pnl_usd = -1054.44
                   WHERE trade_ref = 'OIL-AS-5434644d'
                   RETURNING id""",
                (datetime(2026, 6, 10, 22, 23, 0, tzinfo=timezone.utc),)  # broker close time
            )
            updated = cur.fetchall()
            print(f"  ✓ updated row id={updated[0]['id']}")

            cur.execute(
                """UPDATE gd_dd_state
                   SET consecutive_losses = consecutive_losses + 1,
                       equity = equity - 1054.44
                   WHERE id = 2
                   RETURNING consecutive_losses, equity""",
            )
            dd = cur.fetchone()
            if dd:
                print(f"  ✓ Oil Macro DD: consecutive_losses={dd['consecutive_losses']}, equity={dd['equity']}")

            cur.execute(
                "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    "OIL-AS-5434644d", "alpha_sweep_oil", "EXIT_FILLED", 93.15,
                    '{"reason": "SL", "pnl_gbp": -1054.44, "pnl_usd": -1054.44, '
                    '"oanda_id": "2036391922", "instrument": "BCO_USD", '
                    '"source": "manual_close_dwx_handler_failed", '
                    '"see": "docs/trades/OIL-AS-5434644d.md"}'
                )
            )
            print("  ✓ EXIT_FILLED journal event logged")

            conn.commit()
            print()
            print("=" * 50)
            print("✓ OIL-AS-5434644d closed in DB. Position monitor will stop")
            print("  alarming on next cycle.")
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
