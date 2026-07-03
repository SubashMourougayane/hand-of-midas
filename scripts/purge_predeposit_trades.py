"""Purge LIVE trades entered before the 10K-era deposit, to baseline the track
record from the deposit forward. DRY-RUN default.

Deposit (MT5 History, JM-Demo2): 2026-07-01 16:37 server (UTC+3) = 13:37 UTC.
Everything before = old micro_alpha_sweep / dwx_smoke experiments.

Only touches LIVE trades (mode='live' runs). BT history untouched.
"""
from __future__ import annotations
import argparse
from sqlalchemy import text
from bt_engine.db.engine import get_engine

CUTOFF_UTC = "2026-07-01 13:37:00+00"  # deposit instant


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    ap.add_argument("--cutoff", default=CUTOFF_UTC)
    args = ap.parse_args()
    eng = get_engine()
    with eng.begin() as cx:
        # Live trades split by cutoff.
        before = cx.execute(text(
            "SELECT count(*) FROM bt_trades t JOIN bt_runs r ON r.run_id=t.run_id "
            "WHERE r.mode='live' AND t.entry_timestamp < :c"
        ), {"c": args.cutoff}).scalar()
        after = cx.execute(text(
            "SELECT count(*) FROM bt_trades t JOIN bt_runs r ON r.run_id=t.run_id "
            "WHERE r.mode='live' AND t.entry_timestamp >= :c"
        ), {"c": args.cutoff}).scalar()
        print(f"Cutoff (UTC): {args.cutoff}")
        print(f"LIVE trades BEFORE cutoff (DELETE): {before}")
        print(f"LIVE trades AFTER  cutoff (KEEP):   {after}")
        # Show the survivors so you can eyeball.
        rows = cx.execute(text(
            "SELECT t.entry_timestamp, t.broker_ticket, t.leg, t.exit_reason, t.broker_net_usd "
            "FROM bt_trades t JOIN bt_runs r ON r.run_id=t.run_id "
            "WHERE r.mode='live' AND t.entry_timestamp >= :c ORDER BY t.entry_timestamp"
        ), {"c": args.cutoff}).fetchall()
        print("\n-- KEEPING --")
        for r in rows:
            print(f"  {r.entry_timestamp}  {r.broker_ticket or '(none)'}  {r.leg}  {r.exit_reason}  ${r.broker_net_usd}")

        if not args.apply:
            print("\nDRY-RUN. --apply to delete the BEFORE-cutoff live trades.")
            return

        # Delete child rows first (FK): bar_walk, journal_events reference trade_id.
        ids = [r[0] for r in cx.execute(text(
            "SELECT t.trade_id FROM bt_trades t JOIN bt_runs r ON r.run_id=t.run_id "
            "WHERE r.mode='live' AND t.entry_timestamp < :c"
        ), {"c": args.cutoff}).fetchall()]
        if ids:
            cx.execute(text("DELETE FROM bt_bar_walk WHERE trade_id = ANY(:ids)"), {"ids": ids})
            cx.execute(text("DELETE FROM bt_journal_events WHERE trade_id = ANY(:ids)"), {"ids": ids})
            cx.execute(text("DELETE FROM bt_trades WHERE trade_id = ANY(:ids)"), {"ids": ids})
        print(f"\nAPPLIED. Deleted {len(ids)} pre-deposit live trades (+ their bar_walk/journal rows).")


if __name__ == "__main__":
    main()
