"""Backfill net_r + bars_held for reconciled-closed trades that my cutover/
backfill scripts left NULL (they set broker $ but not the R-multiple / hold).

net_r     = (exit_price - entry_price) * side / risk_units   (price-based bracket R)
bars_held = round((exit_ts - entry_ts) seconds / tf_seconds)

Only touches rows where exit_timestamp IS NOT NULL AND net_r IS NULL AND a real
broker_ticket exists. DRY-RUN default.
"""
from __future__ import annotations
import argparse
from sqlalchemy import text
from bt_engine.db.engine import get_engine

TF_SECONDS = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800,
              "H1": 3600, "H4": 14400, "D1": 86400}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    eng = get_engine()
    with eng.begin() as cx:
        rows = cx.execute(text(
            "SELECT trade_id, side, entry_price, exit_price, risk_units, timeframe, "
            "entry_timestamp, exit_timestamp FROM bt_trades "
            "WHERE exit_timestamp IS NOT NULL AND net_r IS NULL "
            "AND broker_ticket IS NOT NULL AND broker_ticket <> ''"
        )).fetchall()
        print(f"Rows to backfill net_r/bars_held: {len(rows)}")
        for r in rows:
            if not r.risk_units or r.exit_price is None:
                print(f"  {r.trade_id}: missing risk/exit -> skip"); continue
            net_r = (float(r.exit_price) - float(r.entry_price)) * int(r.side) / float(r.risk_units)
            tf_s = TF_SECONDS.get(r.timeframe or "M15", 900)
            secs = (r.exit_timestamp - r.entry_timestamp).total_seconds()
            bars = max(0, round(secs / tf_s))
            print(f"  {r.trade_id}: net_r={net_r:.3f} bars_held={bars}")
            if args.apply:
                cx.execute(text(
                    "UPDATE bt_trades SET net_r=:nr, gross_r=:nr, bars_held=:bh "
                    "WHERE trade_id=:tid"
                ), {"nr": net_r, "bh": bars, "tid": r.trade_id})
        print("\n" + ("APPLIED." if args.apply else "DRY-RUN. --apply to write."))


if __name__ == "__main__":
    main()
