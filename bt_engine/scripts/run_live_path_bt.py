"""run_live_path_bt — THE single backtest: the exact live code path over history.

This is the ONE script that reproduces live == BT. It does NOT re-implement the
strategy, sizing, bracket, or $-booking. It calls the SAME `runner.live.run_live`
the production process calls, with `bt_mode=True` and injected sim deps:

    provider  = MemoryBarProvider(21yr M15)        (instead of Mt5LiveBarProvider)
    clock     = MemoryClock                          (instead of LiveClock)
    bridge    = FakeBridge (physical, fills-from-bar)(instead of DwxBridge → MT5)
    broker    = LiveSafetyBroker(SimBrokerAdapter(bridge), sizer=EquitySizer)
                ^^^ the REAL live broker wrapper: real sizing, slip-check, $-booking

Any change to the live code path (sizing, bracket, partial-$, on_close booking)
automatically changes this backtest — there is no second copy.

The FakeBridge balance is PHYSICAL (partial closes realize only the closed
fraction). So it reports BOTH:
  - final $ from the broker balance (physical / what MT5 would show)
  - the equity sizer's believed $ (what live.py:641 books)
The gap = the partial-TP over-count, quantified by the live path itself.

Usage:
    python3 -m bt_engine.scripts.run_live_path_bt \
        [--start-balance 5000] [--risk-pct 0.015] \
        [--from 2026-07-02] [--to 2026-07-11] [--db-url ...] [--no-persist]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _setup_logging(log_file: str) -> None:
    """Route the FULL live-code-path logs (INFO) to a FILE — auditable — instead
    of stdout. Console stays clean (only our print() summary). Writing to a file
    is buffered, so full logs no longer bottleneck the run the way unbuffered
    stdout did.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file, mode="w")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(fh)

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from bt_engine.db.engine import make_engine, get_db_url
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig
from bt_engine.runner.live import LiveSafetyConfig, run_live
from bt_engine.runner.sim_broker import FakeBridge, SimBrokerAdapter

SYMBOL = "XAUUSD.ecn"
TIMEFRAME = "M15"
STRATEGY = "fib_v2_intraday_a_plus_d"
M5_PATH = Path("/tmp/oanda_xau_m5.parquet")


def load_frame(from_ts: str | None, to_ts: str | None) -> pd.DataFrame:
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, TIMEFRAME)
    if from_ts:
        frame = frame[frame["timestamp"] >= pd.Timestamp(from_ts, tz="UTC")]
    if to_ts:
        frame = frame[frame["timestamp"] <= pd.Timestamp(to_ts, tz="UTC")]
    return frame.reset_index(drop=True)


def report(db_url: str, run_id: str, bridge: FakeBridge, sizer: EquitySizer,
           start_balance: float) -> None:
    engine = make_engine(db_url)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        rows = s.execute(text("""
            SELECT net_r, gross_r, exit_reason, partial_taken, broker_net_usd
            FROM bt_trades WHERE run_id = :rid AND exit_timestamp IS NOT NULL
        """), {"rid": run_id}).fetchall()
    finally:
        s.close()
    if not rows:
        print("no closed trades persisted"); return
    net = [float(r[0]) for r in rows if r[0] is not None]
    wins = [x for x in net if x > 0]
    gw = sum(x for x in net if x > 0); gl = -sum(x for x in net if x < 0)
    pf = gw / gl if gl > 0 else float("inf")
    reasons: dict[str, int] = {}
    for r in rows:
        reasons[r[2]] = reasons.get(r[2], 0) + 1
    broker_usd = sum(float(r[4]) for r in rows if r[4] is not None)
    print("\n" + "=" * 66)
    print(f"  LIVE-CODE-PATH BACKTEST  run_id={run_id}")
    print("=" * 66)
    print(f"  closed trades      {len(rows)}")
    print(f"  sum net_r          {sum(net):+.1f}")
    print(f"  PF                 {pf:.3f}")
    print(f"  win rate           {100*len(wins)/len(net):.1f}%")
    print(f"  exit mix           {reasons}")
    print("  " + "-" * 62)
    print(f"  start balance      ${start_balance:,.2f}")
    print(f"  PHYSICAL final $   ${bridge.balance:,.2f}   (FakeBridge realized — MT5-equivalent)")
    print(f"  sizer believed $   ${sizer.equity():,.2f}   (live.py on_trade_closed booking)")
    print(f"  over-count gap     ${sizer.equity() - bridge.balance:+,.2f}")
    print(f"  reconciled broker  ${broker_usd:+,.2f}   (sum broker_net_usd, physical deals)")
    print("=" * 66)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-balance", type=float, default=5000.0)
    ap.add_argument("--risk-pct", type=float, default=0.015)
    ap.add_argument("--from", dest="from_ts", default=None)
    ap.add_argument("--to", dest="to_ts", default=None)
    ap.add_argument("--db-url", default=None)
    ap.add_argument("--no-persist", action="store_true",
                    help="use a throwaway in-memory-ish run (still needs a DB for repos)")
    ap.add_argument("--log-file", default="run_live_path_bt.log",
                    help="full INFO live-code-path logs written here (auditable)")
    ap.add_argument("--strategy", default=STRATEGY,
                    help="registry strategy id (e.g. fib_v2_intraday_a_plus_d_edge)")
    args = ap.parse_args()

    _setup_logging(args.log_file)
    print(f"[log] full live-code-path logs -> {args.log_file}")
    db_url = args.db_url or get_db_url()
    frame = load_frame(args.from_ts, args.to_ts)
    print(f"[frame] {len(frame):,} M15 bars  {frame['timestamp'].min()} -> {frame['timestamp'].max()}")

    provider = MemoryBarProvider(frame, symbol=SYMBOL, timeframe=TIMEFRAME)
    clock = MemoryClock(provider)
    bridge = FakeBridge(start_balance=args.start_balance, symbol=SYMBOL)
    sizer = EquitySizer(EquitySizerConfig(start_balance=args.start_balance, risk_pct=args.risk_pct))

    # The REAL live broker wrapper (sizing + slip-check + $-booking is live code).
    # BT-relaxed safety: no demo/kill/spread/lot gates (cost modeled via cost_r).
    safety = LiveSafetyConfig(
        require_demo=False,
        max_lot=1e9,
        max_open_positions=1_000_000,
        max_spread=1e9,
        kill_switch_path=Path("/nonexistent/bt-kill-switch"),
    )
    from bt_engine.runner.live import LiveSafetyBroker
    broker = LiveSafetyBroker(SimBrokerAdapter(bridge), bridge, safety, sizer=sizer)

    result = run_live(
        strategy=args.strategy, symbol=SYMBOL, timeframe=TIMEFRAME,
        bt_mode=True, provider=provider, clock=clock, broker=broker, bridge=bridge,
        equity_sizer=sizer, db_url=db_url, dry_run=False,
    )
    report(db_url, result.run_id, bridge, sizer, args.start_balance)


if __name__ == "__main__":
    main()
