"""Backfill broker P&L + exit reason from KNOWN MT5 History values for the
cutover-era closed trades whose deals have since rolled off the DWX
closed_orders.json buffer (so the live reconciler can no longer aggregate them).

Values are the authoritative full-position figures read from the MT5 History tab
(sum of all partial + final deals per position_id). This is a one-time manual
backfill of pre-VPS-cutover trades. DRY-RUN default.
"""
from __future__ import annotations

import argparse
from sqlalchemy import text
from bt_engine.db.engine import get_engine

# ticket -> (exit_reason, broker_net_usd, exit_price)  [MT5 History, full position]
KNOWN = {
    "2121027691": ("TP", 823.64, 4149.17),
    "2116651769": ("SL", -500.52, 4034.23),
    "2123464608": ("SL", -108.42, 4132.13),
    "2123659696": ("SL", -117.76, 4132.02),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    eng = get_engine()
    with eng.begin() as cx:
        for tk, (reason, net, px) in KNOWN.items():
            rows = cx.execute(text(
                "SELECT trade_id, exit_reason, broker_net_usd FROM bt_trades "
                "WHERE broker_ticket=:tk AND exit_timestamp IS NOT NULL"
            ), {"tk": tk}).fetchall()
            print(f"{tk}: {len(rows)} row(s) -> set reason={reason} net=${net} px={px}")
            for r in rows:
                print(f"    was reason={r.exit_reason} net={r.broker_net_usd}")
            if args.apply:
                cx.execute(text(
                    "UPDATE bt_trades SET exit_reason=:r, broker_exit_reason=:r, "
                    "broker_net_usd=:n, broker_gross_usd=:n, exit_price=:px, "
                    "broker_exit_price=:px, broker_reconciled_at=now() "
                    "WHERE broker_ticket=:tk AND exit_timestamp IS NOT NULL"
                ), {"r": reason, "n": net, "px": px, "tk": tk})
        if not args.apply:
            print("\nDRY-RUN. --apply to write.")
        else:
            print("\nAPPLIED.")


if __name__ == "__main__":
    main()
