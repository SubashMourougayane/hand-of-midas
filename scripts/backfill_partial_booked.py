"""One-time: stamp partial_booked_usd into raw_features for the open trade whose
partial-close deal aged off the DWX buffer (so the dashboard open-card can show
the already-booked $ via a DB fallback when the live WS has none).

ticket -> booked_usd (from MT5 History). DRY-RUN default.
"""
from __future__ import annotations
import argparse, json
from sqlalchemy import text
from bt_engine.db.engine import get_engine

KNOWN = {"2118599832": 62.88}  # 0.02 partial close, +$62.88 (MT5 History)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    eng = get_engine()
    with eng.begin() as cx:
        for tk, booked in KNOWN.items():
            rows = cx.execute(text(
                "SELECT trade_id, raw_features, partial_taken FROM bt_trades "
                "WHERE broker_ticket=:tk AND exit_timestamp IS NULL"
            ), {"tk": tk}).fetchall()
            print(f"{tk}: {len(rows)} open row(s), booked=${booked}")
            for r in rows:
                rf = r.raw_features or {}
                if isinstance(rf, str):
                    rf = json.loads(rf)
                rf = dict(rf)
                rf["partial_booked_usd"] = booked
                print(f"    row partial_taken={r.partial_taken} -> set partial_booked_usd={booked}")
                if args.apply:
                    cx.execute(text(
                        "UPDATE bt_trades SET raw_features=CAST(:rf AS jsonb), partial_taken=true "
                        "WHERE trade_id=:tid"
                    ), {"rf": json.dumps(rf), "tid": r.trade_id})
        print("\n" + ("APPLIED." if args.apply else "DRY-RUN. --apply to write."))


if __name__ == "__main__":
    main()
