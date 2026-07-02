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
        max_lot=args.max_lot,
        commission_per_lot_usd=args.commission_per_lot_usd,
        spread_usd_per_lot=args.spread_usd_per_lot,
        entry_slip_pips=args.entry_slip_pips,
        sl_slip_pips=args.sl_slip_pips,
        tp_slip_pips=args.tp_slip_pips,
        swap_long_per_lot_per_night=args.swap_long_per_lot_per_night,
        swap_short_per_lot_per_night=args.swap_short_per_lot_per_night,
        max_open_positions=args.max_open_positions_bt,
        reject_pct=args.reject_pct,
        gap_threshold_seconds=args.gap_threshold_seconds,
        gap_extra_slip_pips=args.gap_extra_slip_pips,
        partial_tp_fail_pct=args.partial_tp_fail_pct,
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
            max_entry_slip_ratio=args.max_entry_slip_ratio,
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
    bt.add_argument("--max-lot", type=float, default=2.0,
                     help="Hard safety cap on lot size (matches live default). BT-only.")
    bt.add_argument("--commission-per-lot-usd", type=float, default=6.50,
                     help="Broker commission per lot round-turn (JM Raw Spread default).")
    bt.add_argument("--spread-usd-per-lot", type=float, default=9.00,
                     help="Broker spread cost per lot ($0.09 pip × 100 XAU contract).")
    # P1a slippage
    bt.add_argument("--entry-slip-pips", type=float, default=0.0,
                     help="Fixed $ price offset against fill (worse). Realistic XAU: 0.10-0.30.")
    bt.add_argument("--sl-slip-pips", type=float, default=0.0,
                     help="Extra $ price beyond stop on SL hit (worse). Realistic XAU: 0.20-1.00.")
    bt.add_argument("--tp-slip-pips", type=float, default=0.0,
                     help="Extra $ price short of TP on TP hit (worse). Usually 0.")
    # P1b overnight swap (JM Demo2 XAU rates: long -71.04 pts/night, short -84.12 pts/night)
    bt.add_argument("--swap-long-per-lot-per-night", type=float, default=0.0,
                     help="Long swap $/lot/night. JM XAU: -0.71 = -$0.71 per 0.01 lot.")
    bt.add_argument("--swap-short-per-lot-per-night", type=float, default=0.0,
                     help="Short swap $/lot/night. JM XAU: -0.84.")
    # P1c engine cap
    bt.add_argument("--max-open-positions-bt", type=int, default=4,
                     help="Max concurrent open trades in BT. Matches live default 4.")
    # P2c requote/reject dropout (deterministic hash-based)
    bt.add_argument("--reject-pct", type=float, default=0.0,
                     help="Fraction of orders deterministically rejected (requote sim). 0.01 = 1%%.")
    # P2a weekend/session gap slip
    bt.add_argument("--gap-threshold-seconds", type=float, default=0.0,
                     help="Bar gap > this (sec) triggers extra SL slip. Weekend = 172800 (48h).")
    bt.add_argument("--gap-extra-slip-pips", type=float, default=0.0,
                     help="Extra $ SL slip when bar follows a gap. Realistic XAU weekend: 2-10.")
    # P2d partial-TP broker modify-fail sim
    bt.add_argument("--partial-tp-fail-pct", type=float, default=0.0,
                     help="Fraction of partial-TP events where SL→BE modify fails (remainder exposed). 0.01-0.02 realistic.")
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
    live.add_argument("--max-live-lot", type=float, default=2.0,
                       help="HARD safety ceiling against runaway sizer bugs. "
                            "Real sizing is Model B (equity_sizer). Default 2.0.")
    live.add_argument("--max-entry-slip-ratio", type=float, default=1.15,
                       help="Reject fill if actual stop distance / expected risk > this ratio. "
                            "Default 1.15 = allow 15%% risk over-run before rejecting. Closes position.")
    live.add_argument("--max-open-positions", type=int, default=4,
                       help="Broker-wide open position cap. Default 4 allows A+D "
                            "concurrent hedge + partial-TP overlap (research validated).")
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
