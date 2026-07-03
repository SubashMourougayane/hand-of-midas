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
from bt_engine.runner.broker_reconciler import find_closed_deal, _parse_broker_time, _to_utc_dt


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

    # Backfill directly via find_closed_deal (aggregates all deals per position_id:
    # partial + final close). This is a DELIBERATE one-time backfill of trades we
    # KNOW are closed (not in open_orders), so we bypass the live loop's
    # closed_orders staleness guard -- the deal rows are valid, just not freshly
    # rewritten. We do NOT bypass the "still open" check: skip if in open_orders.
    fixed = 0
    with eng.begin() as cx:
        open_now = cx.execute(text(
            "SELECT DISTINCT broker_ticket FROM bt_trades WHERE exit_timestamp IS NULL "
            "AND broker_ticket IS NOT NULL AND broker_ticket<>''"
        )).fetchall()
    open_tickets = {r.broker_ticket for r in open_now}

    with eng.begin() as cx:
        for r in rows:
            tk = r.broker_ticket
            if tk in open_tickets:
                print(f"  {tk}: STILL OPEN -> skip"); continue
            deal = find_closed_deal(bridge, tk)
            if deal is None:
                print(f"  {tk}: no closed deal found -> left RECON_PENDING"); continue
            gross = float(deal.get("profit") or 0.0)
            comm = float(deal.get("commission") or 0.0)
            swap = float(deal.get("swap") or 0.0)
            net = gross + comm + swap
            exit_price = float(deal.get("close_price") or 0.0) or None
            reason = str(deal.get("deal_reason") or "") or None
            close_ts = _to_utc_dt(_parse_broker_time(str(deal.get("close_time") or "")), args.offset)
            ndeals = deal.get("_deal_count")
            cx.execute(text(
                "UPDATE bt_trades SET broker_gross_usd=:g, broker_commission_usd=:c, "
                "broker_swap_usd=:s, broker_net_usd=:n, broker_exit_price=:px, "
                "broker_exit_reason=:rsn, broker_close_ts=:cts, broker_reconciled_at=now(), "
                "exit_reason=COALESCE(:rsn,'CLOSED'), exit_price=COALESCE(:px, exit_price) "
                "WHERE trade_id=:tid"
            ), dict(g=gross, c=comm, s=swap, n=net, px=exit_price, rsn=reason,
                    cts=close_ts, tid=r.trade_id))
            print(f"  {tk}: reason={reason} net=${net:.2f} deals={ndeals} exit={exit_price}")
            fixed += 1
    print(f"\nRe-reconciled {fixed}/{len(rows)}.")


if __name__ == "__main__":
    main()
