"""Replay Jun 19 2026 through live's Gold Micro code.

Goal: reproduce A10 — show that with the same data BT used, live's
gate loop rejects the 14:09 LONG and 16:27 SHORT signals.

Outputs:
  - Counts of trades placed by replay
  - Comparison vs BT replay output ($456.92 expected on Gold)
  - Comparison vs LIVE production trades (0 expected)
  - Event log with which gate fired for each rejection
"""
from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone

REPO_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, REPO_ROOT)

from replay.tape.server import TapeServer
from replay.bridge.broker import FakeBroker
from replay.runner import ReplaySession, _truncate_replay_db


def main():
    # 1. Wipe replay DB
    print("Truncating golddigger_replay...")
    _truncate_replay_db()

    # 2. Build tape — load Gold + Oil M3+H1+D
    print("Loading tape...")
    tape = TapeServer(
        instruments=("XAU_USD", "BCO_USD"),
        granularities=("M3", "H1", "D"),
    )
    tape.load()
    g_first, g_last = tape.date_range("XAU_USD", "M3")
    o_first, o_last = tape.date_range("BCO_USD", "M3")
    print(f"  XAU_USD M3: {g_first} → {g_last}")
    print(f"  BCO_USD M3: {o_first} → {o_last}")

    # 3. Bridge — broker over the tape
    broker = FakeBroker(tape=tape, starting_balance=10000.0)

    # 4. Session — install Gold Micro first
    session = ReplaySession(tape=tape, broker=broker, verbose=False)
    print("Installing gold-micro...")
    session.add_system("gold-micro", "backend-micro", "XAU_USD", bias_mode="neutral")
    # NOTE: oil-micro is in same backend.execution namespace via the stub,
    # so installing both currently overwrites the gold-micro scheduler with
    # oil-micro's scheduler module. Single-system per-replay for now.
    # Will solve multi-system in a later iteration.

    # 5. Run Jun 19 from 00:00 UTC to 18:30 UTC (after the latest BT post-deploy trade)
    start = datetime(2026, 6, 19, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 18, 30, tzinfo=timezone.utc)
    print(f"\nRunning replay from {start} to {end}...")
    result = session.run(start, end)

    print(f"\n--- REPLAY DONE ---")
    print(f"Steps (1-min ticks): {result['steps']}")
    print(f"Total events: {len(result['events'])}")

    # 6. Show broker trades
    closed = list(broker._closed_history.values())
    print(f"\nBroker closed trades: {len(closed)}")
    for c in closed:
        print(f"  {c['ticket']} {c['side']} {c['instrument']} "
              f"open={c['open_price']:.4f} close={c['close_price']:.4f} "
              f"pl={c['realized_pl']:+.2f} reason={c['exit_reason']} "
              f"open_time={c.get('close_time', 'n/a')}")

    open_trades = broker.get_open_trades()
    print(f"\nBroker open trades: {len(open_trades)}")
    for t in open_trades:
        print(f"  {t['id']} {t['side']} {t['instrument']} entry={t['price']:.4f} "
              f"unreal={t['unrealizedPL']:+.2f}")

    # 7. Pull replay DB trades for cross-check
    import psycopg2
    conn = psycopg2.connect("postgresql://subash@localhost:5432/golddigger_replay")
    cur = conn.cursor()
    cur.execute(
        "SELECT trade_ref, strategy, side, entry_price, sl_price, tp_price, "
        "exit_time, exit_reason, pnl_usd FROM gd_trades ORDER BY entry_time"
    )
    rows = cur.fetchall()
    print(f"\nReplay DB gd_trades: {len(rows)}")
    for r in rows:
        print(f"  {r}")

    # Pull gd_signals to see what the strategy actually emitted
    cur.execute(
        "SELECT timestamp, strategy, direction, taken, skip_reason "
        "FROM gd_signals ORDER BY timestamp"
    )
    sigs = cur.fetchall()
    print(f"\nReplay DB gd_signals: {len(sigs)}")
    for s in sigs:
        print(f"  {s}")

    # Pull gd_journal for any rejection events
    cur.execute(
        "SELECT timestamp, event_type, trade_ref FROM gd_journal "
        "WHERE event_type LIKE '%SKIP%' OR event_type LIKE '%REJECT%' "
        "ORDER BY timestamp LIMIT 50"
    )
    jrows = cur.fetchall()
    print(f"\nReplay DB gd_journal (skip/reject events): {len(jrows)}")
    for j in jrows:
        print(f"  {j}")

    cur.execute("SELECT system, sweep_key, consumed_at FROM gd_traded_sweeps ORDER BY consumed_at")
    sweeps = cur.fetchall()
    print(f"\nReplay DB gd_traded_sweeps: {len(sweeps)}")
    for s in sweeps:
        print(f"  {s}")

    conn.close()


if __name__ == "__main__":
    main()
