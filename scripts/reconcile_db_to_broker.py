"""Reconcile the bt_trades DB to broker truth (run ONLY when live runners are stopped).

Broker `open_orders.json` is authoritative. Any DB row with exit_timestamp IS NULL
whose broker_ticket is NOT in the broker's current open set is a phantom (closed at
broker, or never really filled) and gets marked closed:
  - if found in closed_orders.json -> use real close_price / profit / reason
  - else (empty-ticket / never-filled adoption artifact) -> close flat at entry
    (0 R, reason RECONCILED_FLAT)

Rows whose ticket IS in the broker open set are left untouched (real live positions).

DRY-RUN by default. Pass --apply to write.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from bt_engine.db.engine import get_engine

DWX = Path(os.environ.get(
    "DWX_DIR",
    str(Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5"
        "/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"),
))


def load_broker():
    openo = json.loads((DWX / "open_orders.json").read_text())
    open_tickets = set(openo.keys()) if isinstance(openo, dict) else set()
    closed_raw = json.loads((DWX / "closed_orders.json").read_text())
    closed = {}
    if isinstance(closed_raw, list):
        for d in closed_raw:
            t = str(d.get("ticket"))
            closed[t] = d
    return open_tickets, closed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    open_tickets, closed = load_broker()
    print(f"Broker OPEN tickets (KEEP): {sorted(open_tickets)}")
    print(f"Broker closed_orders records: {len(closed)}")

    eng = get_engine()
    with eng.begin() as cx:
        rows = cx.execute(text(
            "SELECT trade_id, broker_ticket, leg, side, entry_price, entry_timestamp "
            "FROM bt_trades WHERE exit_timestamp IS NULL ORDER BY entry_timestamp"
        )).fetchall()

        keep, close_real, close_flat = [], [], []
        for r in rows:
            tk = (r.broker_ticket or "").strip()
            if tk and tk in open_tickets:
                keep.append(r)
            elif tk and tk in closed:
                close_real.append((r, closed[tk]))
            else:
                close_flat.append(r)

        print(f"\nOpen DB rows: {len(rows)}")
        print(f"  KEEP (real live position):     {len(keep)}")
        print(f"  CLOSE from broker closed_orders:{len(close_real)}")
        print(f"  CLOSE flat (no broker record):  {len(close_flat)}")

        print("\n-- KEEP --")
        for r in keep:
            print(f"   {r.broker_ticket}  {r.leg}  entry={r.entry_price}  {r.trade_id}")
        print("\n-- CLOSE (broker closed) --")
        for r, c in close_real:
            print(f"   {r.broker_ticket}  {r.leg}  close={c.get('close_price')} profit={c.get('profit')} reason={c.get('deal_reason')}")
        print("\n-- CLOSE flat (phantom / never-filled) --")
        for r in close_flat:
            print(f"   ticket='{r.broker_ticket}'  {r.leg}  entry={r.entry_price}  ts={r.entry_timestamp}  {r.trade_id}")

        if not args.apply:
            print("\nDRY-RUN. Re-run with --apply to write.")
            return

        now = datetime.now(timezone.utc)
        # Close broker-closed rows with real fills.
        for r, c in close_real:
            close_px = float(c.get("close_price") or r.entry_price)
            profit = float(c.get("profit") or 0.0)
            ct = c.get("close_time")  # "2026.06.29 10:31:42"
            try:
                exit_ts = datetime.strptime(ct, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                exit_ts = now
            cx.execute(text(
                "UPDATE bt_trades SET exit_timestamp=:ts, exit_price=:px, "
                "exit_reason='RECONCILED_BROKER_CLOSED', broker_net_usd=:pnl, "
                "broker_close_ts=:ts, broker_reconciled_at=:now "
                "WHERE trade_id=:tid AND exit_timestamp IS NULL"
            ), dict(ts=exit_ts, px=close_px, pnl=profit, now=now, tid=r.trade_id))

        # Close phantom / never-filled rows flat.
        for r in close_flat:
            cx.execute(text(
                "UPDATE bt_trades SET exit_timestamp=:ts, exit_price=:px, "
                "exit_reason='RECONCILED_FLAT', net_r=0, gross_r=0, "
                "broker_reconciled_at=:now "
                "WHERE trade_id=:tid AND exit_timestamp IS NULL"
            ), dict(ts=now, px=float(r.entry_price or 0), now=now, tid=r.trade_id))

        remaining = cx.execute(text(
            "SELECT count(*) FROM bt_trades WHERE exit_timestamp IS NULL"
        )).scalar()
        print(f"\nAPPLIED. Open rows now: {remaining} (expect {len(keep)})")


if __name__ == "__main__":
    main()
