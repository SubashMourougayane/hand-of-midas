import json
from sqlalchemy import text
from bt_engine.db.engine import get_engine
c = get_engine().connect()
# One row per real broker ticket (dedup across dual-adopt run rows: richest wins).
rows = list(c.execute(text(
    "SELECT broker_ticket, leg, side, entry_timestamp, exit_timestamp, entry_price, "
    "exit_price, stop_price, take_profit_price, risk_units, net_r, bars_held, "
    "exit_reason, broker_net_usd, mfe_r, mae_r, partial_taken, partial_r, "
    "raw_features, regime_at_entry, ext_target_pct, sl_buffer_pct, confluence_score "
    "FROM bt_trades t JOIN bt_runs r ON r.run_id=t.run_id "
    "WHERE r.mode='live' AND broker_ticket IS NOT NULL AND broker_ticket<>'' "
    "ORDER BY broker_ticket, exit_timestamp DESC NULLS LAST"
)))
best = {}
def score(m):
    rf = m.get("raw_features") or {}
    b = rf.get("partial_booked_usd") if isinstance(rf, dict) else None
    return (8 if b else 0) + (abs(m["partial_r"]) if m["partial_r"] else 0) + (1 if m["broker_net_usd"] is not None else 0) + (0.5 if m["partial_taken"] else 0)
cols = rows[0].keys() if rows else []
for r in rows:
    m = dict(zip(cols, r))
    m["entry_timestamp"] = str(m["entry_timestamp"]); m["exit_timestamp"] = str(m["exit_timestamp"])
    tk = m["broker_ticket"]
    if tk not in best or score(m) > score(best[tk]):
        best[tk] = m
out = sorted(best.values(), key=lambda m: m["entry_timestamp"])
print(json.dumps(out, default=str))
