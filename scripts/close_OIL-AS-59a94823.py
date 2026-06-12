"""Manually close OIL-AS-59a94823 in DB after the DWX EA failed to write
closed_orders.json (DWX OnTradeTransaction dual-instance bug).

Broker truth (from JustMarkets web History panel, screenshot 2026-06-12):

  Symbol:      BRENT
  Direction:   Buy (LONG)
  Lots:        0.56 (= 560 barrels)
  Entry:       $91.51
  TP:          $94.32
  SL:          $91.08
  Exit (SL):   $91.08
  Open time:   2026-06-11 15:48 IST = 10:18 UTC
  Close time:  2026-06-11 15:56 IST = 10:26 UTC
  Hold:        ~8 minutes
  Trade P&L:   -$240.80
  Commission:  -$3.36
  Net P&L:     -$244.16
  Broker ID:   2039109519

Note on side discrepancy: DB has side="SHORT" for this row, but the broker
records a LONG (TP > entry > SL = LONG geometry). This is a separate bug —
likely the engine wrote the wrong side at order placement. We're not fixing
that retroactively (the trade was actually a LONG that hit SL); just
recording the exit data.

DB pnl_usd reflects strategy-level P&L (no commission), matching the
in-engine calculation. Broker net (-$244.16) includes the $3.36 commission
which is tracked separately by the broker.

Idempotent: if exit_time is already set, exits without changing anything.

Why manual close was needed: same DWX OnTradeTransaction dual-instance bug
+ price-extremes-cleared-on-restart issue documented in
scripts/close_GD-MI-09314bdd.py.
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
                "SELECT exit_time, pnl_usd, side FROM gd_trades WHERE trade_ref = %s",
                ("OIL-AS-59a94823",)
            )
            row = cur.fetchone()
            if not row:
                print("No row found — nothing to close.")
                return 0
            if row["exit_time"] is not None:
                print(f"Already closed at {row['exit_time']}, pnl_usd={row['pnl_usd']}. No action.")
                return 0

            print(f"DB side = {row['side']!r} (broker recorded as LONG; ignoring this discrepancy)")
            close_time = datetime(2026, 6, 11, 10, 26, 0, tzinfo=timezone.utc)
            print("Closing OIL-AS-59a94823 at SL $91.08, pnl_usd=-240.80 ...")
            cur.execute(
                """UPDATE gd_trades
                   SET exit_time = %s,
                       exit_price = 91.08,
                       exit_reason = 'SL',
                       pnl_gbp = -240.80,
                       pnl_usd = -240.80
                   WHERE trade_ref = 'OIL-AS-59a94823'
                   RETURNING id""",
                (close_time,)
            )
            updated = cur.fetchall()
            print(f"  ✓ updated row id={updated[0]['id']}")

            # Oil Macro DD state — DD_STATE_ID per backend-oil/config.py
            # (Oil Macro has its own DD row; same pattern as Gold Macro)
            cur.execute(
                """UPDATE gd_dd_state
                   SET consecutive_losses = consecutive_losses + 1,
                       equity = equity - 240.80
                   WHERE id = 2
                   RETURNING consecutive_losses, equity""",
            )
            dd = cur.fetchone()
            if dd:
                print(f"  ✓ Oil Macro DD: consecutive_losses={dd['consecutive_losses']}, equity={dd['equity']}")
            else:
                print("  ⚠️ No DD state row for id=2 (Oil Macro). Skipping DD update.")

            cur.execute(
                "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    "OIL-AS-59a94823", "alpha_sweep_oil", "EXIT_FILLED", 91.08,
                    '{"reason": "SL", "pnl_gbp": -240.80, "pnl_usd": -240.80, '
                    '"oanda_id": "2039109519", "instrument": "BCO_USD", '
                    '"source": "manual_close_dwx_handler_failed", '
                    '"see": "scripts/close_OIL-AS-59a94823.py", '
                    '"note": "broker_recorded_as_LONG_db_has_SHORT_side_field_unchanged"}'
                )
            )
            print("  ✓ EXIT_FILLED journal event logged")

            conn.commit()
            print()
            print("=" * 60)
            print("✓ OIL-AS-59a94823 closed in DB. Position monitor will stop")
            print("  alarming on next cycle (was at EXIT_AMBIGUOUS streak ~250+).")
            print("=" * 60)
            return 0
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
