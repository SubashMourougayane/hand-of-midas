"""Re-reconcile closed trades with the PROPER broker_reconciler (aggregates deals
per position_id, reads real deal_reason TP/SL, includes partial-close deals).

My cutover shortcut (reconcile_db_to_broker.py) wrote a single deal's profit +
a generic 'RECONCILED_BROKER_CLOSED' reason. This:
  1. Clears the crude broker_* values + broker_reconciled_at + exit_reason on
     closed rows that carry a real broker_ticket.
  2. Runs reconcile_trade() from broker_reconciler.py for each -> correct
     aggregated broker_net_usd + TP/SL exit_reason + partial deals summed.

Run ONLY on the VPS (has the live DWX closed_orders). DRY-RUN default.
"""
from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from sqlalchemy import text

from bt_engine.db.engine import get_engine, get_session_factory
from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.runner.broker_reconciler import reconcile_trade


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offset", type=int, default=3, help="server UTC offset hours (JM=3)")
    args = ap.parse_args()

    bridge = DwxBridge()  # DWX_DIR from env
    eng = get_engine()

    with eng.begin() as cx:
        rows = cx.execute(text(
            "SELECT trade_id, broker_ticket, exit_reason, broker_net_usd "
            "FROM bt_trades "
            "WHERE exit_timestamp IS NOT NULL "
            "AND broker_ticket IS NOT NULL AND broker_ticket <> '' "
            "AND exit_reason = 'RECONCILED_BROKER_CLOSED'"
        )).fetchall()
        print(f"Crude-reconciled rows to fix: {len(rows)}")
        for r in rows:
            print(f"  ticket={r.broker_ticket} old_reason={r.exit_reason} old_usd={r.broker_net_usd}")
        if not rows:
            print("Nothing to fix.")
            return
        if not args.apply:
            print("\nDRY-RUN. --apply to clear + re-reconcile.")
            return
        # Clear crude values so the proper reconciler re-processes them.
        ids = [r.trade_id for r in rows]
        cx.execute(text(
            "UPDATE bt_trades SET broker_reconciled_at=NULL, broker_net_usd=NULL, "
            "broker_gross_usd=NULL, broker_swap_usd=NULL, broker_commission_usd=NULL, "
            "broker_exit_reason=NULL, exit_reason='RECON_PENDING' "
            "WHERE trade_id = ANY(:ids)"
        ), {"ids": ids})

    # Now run the proper reconciler per row (its own sessions/txns).
    Session = get_session_factory()
    fixed = 0
    for r in rows:
        with Session() as s:
            res = reconcile_trade(
                bridge=bridge, session=s,
                trade_id=r.trade_id, ticket=r.broker_ticket,
                server_utc_offset_hours=args.offset,
                max_retries=3, backoff_s=0.2,
            )
            s.commit()
            print(f"  {r.broker_ticket}: matched={res.matched} reason={res.broker_exit_reason} net=${res.broker_net_usd}")
            if res.matched:
                fixed += 1
    print(f"\nRe-reconciled {fixed}/{len(rows)}.")
    # Any that still failed keep exit_reason='RECON_PENDING' -> visible, not silently wrong.


if __name__ == "__main__":
    main()
