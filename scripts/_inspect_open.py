from sqlalchemy import text
from bt_engine.db.engine import get_engine
c = get_engine().connect()
for r in c.execute(text(
    "SELECT trade_id, partial_taken, partial_r, broker_net_usd, raw_features "
    "FROM bt_trades WHERE broker_ticket='2118599832' AND exit_timestamp IS NULL"
)):
    rf = r[4] if isinstance(r[4], dict) else {}
    print(str(r[0])[:8], "partial_taken=", r[1], "partial_r=", r[2],
          "broker_net=", r[3], "booked=", rf.get("partial_booked_usd"))
