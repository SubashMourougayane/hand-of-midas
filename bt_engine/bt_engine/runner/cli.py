"""bt_engine CLI entry point."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from .backtest import DEFAULT_LEDGER, run_backtest_frozen_ledger, run_backtest_intraday
from ..journal.replay import replay_trade, story_to_dict


def _cmd_bt(args: argparse.Namespace) -> int:
    if args.intraday:
        return _cmd_bt_intraday(args)
    result = run_backtest_frozen_ledger(
        strategy=args.strategy,
        ledger_path=args.ledger,
        out_dir=args.out,
        db_url=args.db_url,
    )
    print("=" * 60)
    print(f"run_id      : {result.run_id}")
    print(f"run_ref     : {result.run_ref}")
    print(f"trades      : {result.trades_inserted}")
    print(f"net_r       : {result.headline.net_r:+.6f}")
    print(f"win_rate    : {result.headline.win_rate * 100:.2f}%")
    print(f"profit_fact : {result.headline.profit_factor:.4f}")
    print(f"max_dd_r    : {result.headline.max_drawdown_r:+.4f}")
    print(f"pos_years   : {result.headline.positive_years_ratio}")
    print(f"trades_csv  : {result.trades_csv}")
    print(f"summary_json: {result.summary_json}")
    return 0


def _cmd_bt_intraday(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    result = run_backtest_intraday(
        strategy=args.strategy,
        m5_parquet=args.m5_parquet,
        symbol=args.symbol,
        timeframe=args.timeframe,
        max_bars_held=args.max_bars_held,
        cost_usd=args.cost_usd,
        use_equity_sizer=args.use_equity_sizer,
        start_balance=args.start_balance,
        risk_pct=args.risk_pct,
        db_url=args.db_url,
        max_bars=args.max_bars,
    )
    print("=" * 60)
    print(f"run_id         : {result.run_id}")
    print(f"run_ref        : {result.run_ref}")
    print(f"bars_processed : {result.bars_processed:,}")
    print(f"trades_open    : {result.trades_open:,}")
    print(f"trades_closed  : {result.trades_closed:,}")
    print(f"signals        : {result.signals:,}")
    print(f"bar_walk_rows  : {result.bar_walk_rows:,}")
    print(f"net_r          : {result.net_r:+.2f}")
    if result.net_usd is not None:
        print(f"net_usd        : ${result.net_usd:+,.2f}")
    return 0


def _cmd_journal(args: argparse.Namespace) -> int:
    from sqlalchemy.orm import sessionmaker
    from .. db.engine import make_engine

    engine = make_engine(args.db_url) if args.db_url else make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        story = replay_trade(s, args.trade_ref)
    finally:
        s.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(story_to_dict(story), indent=2))
    print(f"Trade story written to {out}")
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    from .live import run_live
    from .live import LiveSafetyConfig
    from .equity_sizer import EquitySizer, EquitySizerConfig

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    # Optional Model B 1.5% equity sizer
    equity_sizer = None
    if getattr(args, "use_equity_sizer", False):
        equity_sizer = EquitySizer(EquitySizerConfig(
            start_balance=args.start_balance,
            risk_pct=args.risk_pct,
        ))

    result = run_live(
        strategy=args.strategy,
        symbol=args.symbol,
        timeframe=args.timeframe,
        max_ticks=args.max_ticks,
        poll_interval_s=args.poll_interval,
        dry_run=args.dry_run,
        db_url=args.db_url,
        max_wait_s=args.max_wait,
        live_safety=LiveSafetyConfig(
            require_demo=not args.allow_non_demo,
            max_lot=args.max_live_lot,
            max_open_positions=args.max_open_positions,
            max_spread=args.max_spread,
        ),
        equity_sizer=equity_sizer,
    )
    print("=" * 60)
    print(f"run_id         : {result.run_id}")
    print(f"run_ref        : {result.run_ref}")
    print(f"bars_processed : {result.bars_processed}")
    print(f"closed_trades  : {result.closed_trades}")
    return 0


def _cmd_strategies(args: argparse.Namespace) -> int:
    from ..strategies import registry

    for name in registry.list_strategies():
        print(name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bt-engine", description="bt_engine CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    bt = sub.add_parser("bt", help="Run a backtest")
    bt.add_argument("--strategy", default="fib_v2_xau_ensemble")
    bt.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="Frozen ledger CSV path (sdr001 replay only)")
    bt.add_argument("--out", default="bt_engine/output/run01")
    bt.add_argument("--db-url", default=None)
    # Intraday-engine BT (mirrors live plumbing — journal + bar_walk + gate events).
    bt.add_argument("--intraday", action="store_true",
                     help="Run engine-driven intraday BT (M5 parquet -> resample -> run_engine mode=bt)")
    bt.add_argument("--m5-parquet", default="/tmp/oanda_xau_m5.parquet")
    bt.add_argument("--symbol", default="XAUUSD.ecn")
    bt.add_argument("--timeframe", default="M15")
    bt.add_argument("--max-bars-held", type=int, default=None,
                     help="Safety cap on trade hold in bars (None = strategy walker decides)")
    bt.add_argument("--max-bars", type=int, default=None,
                     help="Cap total bars processed (smoke testing)")
    bt.add_argument("--cost-usd", type=float, default=0.65,
                     help="Broker cost per trade in USD (JustMarkets Raw Spread default)")
    bt.add_argument("--use-equity-sizer", action="store_true",
                     help="Enable Model B 1.5%% asymmetric monthly equity sizer")
    bt.add_argument("--start-balance", type=float, default=5000.0)
    bt.add_argument("--risk-pct", type=float, default=0.015)
    bt.set_defaults(func=_cmd_bt)

    live = sub.add_parser("live", help="Run live engine against MT5 via DWX bridge")
    live.add_argument("--strategy", default="fib_v2_xau_ensemble")
    live.add_argument("--symbol", default="XAUUSD.ecn")
    live.add_argument("--timeframe", default="M5")
    live.add_argument("--max-ticks", type=int, default=None, help="Stop after N bars (smoke testing)")
    live.add_argument("--poll-interval", type=float, default=1.0)
    live.add_argument("--max-wait", type=float, default=None, help="Max seconds to wait per bar when --max-ticks is set")
    live.add_argument("--dry-run", action="store_true", help="Log orders, do not submit to broker")
    live.add_argument("--db-url", default=None)
    live.add_argument("--max-live-lot", type=float, default=0.01)
    live.add_argument("--max-open-positions", type=int, default=1)
    live.add_argument("--max-spread", type=float, default=0.50)
    live.add_argument("--allow-non-demo", action="store_true")
    # Model B equity sizer (Step 6 — Paper-live target)
    live.add_argument("--use-equity-sizer", action="store_true",
                       help="Enable Model B 1.5%% asymmetric monthly equity sizer")
    live.add_argument("--start-balance", type=float, default=5000.0,
                       help="Initial account equity for equity sizer ($)")
    live.add_argument("--risk-pct", type=float, default=0.015,
                       help="Risk per trade as fraction of current equity (default 0.015 = 1.5%%)")
    live.set_defaults(func=_cmd_live)

    sl = sub.add_parser("strategies", help="List available strategies")
    sl.set_defaults(func=_cmd_strategies)

    j = sub.add_parser("journal", help="Replay a trade's bar-by-bar story")
    j.add_argument("--trade-ref", required=True)
    j.add_argument("--out", default="bt_engine/output/trade_story.json")
    j.add_argument("--db-url", default=None)
    j.set_defaults(func=_cmd_journal)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
