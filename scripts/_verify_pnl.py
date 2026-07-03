from datetime import datetime, timezone
from sqlalchemy import text
from bt_engine.db.engine import get_engine
c = get_engine().connect()
rows = list(c.execute(text(
    "SELECT DISTINCT ON (broker_ticket) broker_ticket, broker_net_usd, exit_timestamp, raw_features "
    "FROM bt_trades t JOIN bt_runs r ON r.run_id=t.run_id "
    "WHERE r.mode='live' AND broker_ticket IS NOT NULL AND broker_ticket<>'' "
    "ORDER BY broker_ticket, exit_timestamp DESC NULLS LAST"
)))
sod = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
closed = sum(r[1] or 0 for r in rows if r[2] is not None)
today = sum(r[1] or 0 for r in rows if r[2] is not None and r[2] >= sod)
booked = 0.0
for r in rows:
    if r[2] is None:  # open
        rf = r[3] if isinstance(r[3], dict) else {}
        booked += float(rf.get("partial_booked_usd") or 0)
print(f"closed_all_realized = {closed:.2f}")
print(f"closed_today        = {today:.2f}")
print(f"open_booked         = {booked:.2f}")
