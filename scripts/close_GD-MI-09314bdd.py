"""Manually close GD-MI-09314bdd in DB after the DWX EA failed to write
closed_orders.json (DWX OnTradeTransaction dual-instance bug).

Broker truth (from JustMarkets web History panel, screenshotted 2026-06-12):

  Side:        SHORT 0.38 lots XAUUSD = 38 oz
  Entry:       $4083.11
  TP:          $4059.55
  SL:          $4109.68
  Exit (SL):   $4109.68
  Open time:   2026-06-11 22:18 server time (broker is GMT+3)
  Close time:  2026-06-11 23:00 server time = 20:00 UTC
  Trade P&L:   -$1,009.66
  Commission:  -$2.66
  Net P&L:     -$1,012.32

DB pnl_usd reflects the strategy-level P&L only (matches in-engine calc):
  (4083.11 - 4109.68) * 38 = -$1,009.66

Idempotent: if exit_time is already set, exits without changing anything.

Why manual close was needed (analyzed 2026-06-12):
  Path 1 (closed_orders.json) — DWX EA OnTradeTransaction handler did not fire
  on VPS. Likely cause: Mac MT5 + VPS MT5 sharing the same JustMarkets account
  caused MT5 to deliver the close event to the Mac instance instead. Mac EA
  either has older code OR writes to a Mac-local closed_orders.json file path.
  Either way, VPS closed_orders.json never got the record.

  Path 2 (heuristic price-extremes fallback) — _price_extremes dict in
  backend-micro/scanner/live_engine.py was empty for oanda_id 2041264362.
  This is in-process Python state that does NOT persist across service
  restarts. The Filter #11 deploy on 2026-06-12 ~01:35 UTC restarted services,
  clearing all in-flight extremes. Position monitor falls back to AMBIGUOUS
  branch (sl_reached=False, tp_reached=False) → skip → log EXIT_AMBIGUOUS →
  retry next cycle → infinite loop.

  Fix to make next time automatic:
    - Persist _price_extremes to DB (or read current price as fallback when
      extremes are empty AND price is well past SL or TP)
    - Address DWX OnTradeTransaction dual-instance issue (sync Mac EA version
      with VPS, or shut down Mac MT5 entirely)
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
                ("GD-MI-09314bdd",)
            )
            row = cur.fetchone()
            if not row:
                print("No row found — nothing to close.")
                return 0
            if row["exit_time"] is not None:
                print(f"Already closed at {row['exit_time']}, pnl_usd={row['pnl_usd']}. No action.")
                return 0

            close_time = datetime(2026, 6, 11, 20, 0, 0, tzinfo=timezone.utc)
            print("Closing GD-MI-09314bdd at SL $4109.68, pnl_usd=-1009.66 ...")
            cur.execute(
                """UPDATE gd_trades
                   SET exit_time = %s,
                       exit_price = 4109.68,
                       exit_reason = 'SL',
                       pnl_gbp = -1009.66,
                       pnl_usd = -1009.66
                   WHERE trade_ref = 'GD-MI-09314bdd'
                   RETURNING id""",
                (close_time,)
            )
            updated = cur.fetchall()
            print(f"  ✓ updated row id={updated[0]['id']}")

            # Gold Micro DD state is id=3 (per backend-micro/config.py:DD_STATE_ID)
            cur.execute(
                """UPDATE gd_dd_state
                   SET consecutive_losses = consecutive_losses + 1,
                       equity = equity - 1009.66
                   WHERE id = 3
                   RETURNING consecutive_losses, equity""",
            )
            dd = cur.fetchone()
            if dd:
                print(f"  ✓ Gold Micro DD: consecutive_losses={dd['consecutive_losses']}, equity={dd['equity']}")
            else:
                print("  ⚠️ No DD state row for id=3 (Gold Micro). Skipping DD update.")

            cur.execute(
                "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    "GD-MI-09314bdd", "micro_alpha_sweep", "EXIT_FILLED", 4109.68,
                    '{"reason": "SL", "pnl_gbp": -1009.66, "pnl_usd": -1009.66, '
                    '"oanda_id": "2041264362", "instrument": "XAU_USD", '
                    '"source": "manual_close_dwx_handler_failed", '
                    '"see": "scripts/close_GD-MI-09314bdd.py"}'
                )
            )
            print("  ✓ EXIT_FILLED journal event logged")

            conn.commit()
            print()
            print("=" * 60)
            print("✓ GD-MI-09314bdd closed in DB. Position monitor will stop")
            print("  alarming on next cycle.")
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
