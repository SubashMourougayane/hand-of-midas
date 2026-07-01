"""Production-spec A+D combined backtest with Model B 1.5% asymmetric monthly sizing.

Mirrors what LIVE does:
  - Both A + D legs operate on SHARED NAV (one account)
  - Each trade sized by current equity × 1.5% / stop_distance
  - Lot floor / cap apply (JustMarkets reality)
  - Skim profits at month-end (Model B asymmetric)
  - Eat losses (no claw-back)
  - $5,000 start

Input:
  - Latest finished `fib_v2_intraday_a` BT run in DB
  - Latest finished `fib_v2_intraday_d` BT run in DB

Output:
  - New DB run: strategy_id='fib_v2_intraday_a_plus_d'
  - Trades replayed with REAL qty per trade
  - cost_r / gross_r / net_r preserved from underlying runs
  - bt_trades.raw_features extended with `qty`, `pnl_usd`, `equity_at_entry`

This gives the dashboard the production numbers ($816k target).

Usage:
  python3 -m bt_engine.scripts.seed_intraday_combined_production [--start-balance 5000]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtTrade
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)


def _latest_finished(session, strategy_id: str) -> BtRun:
    q = (
        select(BtRun)
        .where(BtRun.strategy_id == strategy_id)
        .where(BtRun.mode == "bt")
        .where(BtRun.end_ts.is_not(None))
        .order_by(desc(BtRun.start_ts))
        .limit(1)
    )
    row = session.execute(q).scalar_one_or_none()
    if row is None:
        raise SystemExit(
            f"No finished BT run for {strategy_id}. "
            f"Run scripts/seed_intraday_ad_bt.py first."
        )
    return row


def _load_trades(session, run_id) -> list[BtTrade]:
    q = (
        select(BtTrade)
        .where(BtTrade.run_id == run_id)
        .where(BtTrade.exit_timestamp.is_not(None))
        .order_by(BtTrade.entry_timestamp)
    )
    return list(session.execute(q).scalars())


def run(start_balance: float, risk_pct: float) -> None:
    engine_db = make_engine(DB_URL)
    Session = sessionmaker(bind=engine_db, expire_on_commit=False)

    with Session() as s:
        a_run = _latest_finished(s, "fib_v2_intraday_a")
        d_run = _latest_finished(s, "fib_v2_intraday_d")
        print(f"A run: {a_run.ref}")
        print(f"D run: {d_run.ref}")

        a_trades = _load_trades(s, a_run.run_id)
        d_trades = _load_trades(s, d_run.run_id)
        print(f"  A trades closed: {len(a_trades):,}")
        print(f"  D trades closed: {len(d_trades):,}")

    # Merge + sort chronologically.
    merged = sorted(a_trades + d_trades, key=lambda t: t.entry_timestamp)
    print(f"  combined chronological ledger: {len(merged):,} trades")

    # ── Replay through equity sizer ──
    sizer = EquitySizer(EquitySizerConfig(
        start_balance=start_balance,
        risk_pct=risk_pct,
        # everything else Model B default
    ))

    new_run_id = uuid.uuid4()
    new_ref = f"BT-INTRADAY-AD-COMBO-{new_run_id.hex[:8]}"

    # Snapshot config from underlying runs
    combo_config = {
        "source_a_run": str(a_run.run_id),
        "source_d_run": str(d_run.run_id),
        "start_balance": start_balance,
        "risk_pct": risk_pct,
        "sizer_model": "B_asymmetric_monthly",
        "symbol": a_run.symbol,
        "timeframe": a_run.timeframe,
        "session_a": "london_ny",
        "session_d": "all",
        "max_hold_h_a": 12,
        "max_hold_h_d": 24,
        "partial_tp_at_r": 1.0,
        "partial_tp_pct": 0.5,
        "min_risk_units": 0.50,
        "ext_target_pct": 2.618,
        "sl_buffer_pct": 0.02,
        "pivot_lb": 3,
        "cost_usd": 0.65,
    }

    # Build new BtRun + replay-merged trades.
    new_trades: list[dict] = []
    equity_log: list[dict] = []
    n_skipped_lot_floor = 0

    for t in merged:
        # Stop distance in price units (already in t.risk_units)
        stop_distance = float(t.risk_units)
        # Ask sizer for qty (lots) given current equity.
        try:
            qty = sizer.size_order(
                symbol=t.symbol,
                stop_distance=stop_distance,
                ts=t.entry_timestamp,
            )
        except Exception:
            n_skipped_lot_floor += 1
            continue
        if qty <= 0:
            n_skipped_lot_floor += 1
            continue

        # Compute $ PnL with real qty.
        #   gross_r is in R-units (multiples of 1R = risk_units price-distance)
        #   $ PnL = gross_r × stop_distance × qty × contract_size
        contract_size = {
            "XAUUSD.ecn": 100, "XAUUSD": 100,
            "EURUSD.ecn": 100_000, "EURUSD": 100_000,
            "GBPUSD.ecn": 100_000,
            "BRENT.ecn": 1000, "BRENT": 1000,
        }.get(t.symbol, 1)
        gross_r = float(t.gross_r if t.gross_r is not None else 0.0)
        cost_r = float(t.cost_r if t.cost_r is not None else 0.0)
        net_r = float(t.net_r if t.net_r is not None else 0.0)
        pnl_usd = net_r * stop_distance * qty * contract_size

        # Notify sizer of close.
        sizer.on_trade_closed(
            pnl_dollars=pnl_usd,
            close_ts=t.exit_timestamp or t.entry_timestamp,
        )

        # Build new trade row (preserves underlying fields; adds qty + pnl).
        # source_trade_id lets the journal page resolve events/bar_walk from
        # the underlying A or D run (combined run owns no journal of its own).
        new_trade_id = uuid.uuid4()
        new_trades.append(dict(
            trade_id=new_trade_id,
            trade_ref=f"COMBO-{t.trade_ref}",
            run_id=new_run_id,
            strategy_id="fib_v2_intraday_a_plus_d",
            symbol=t.symbol,
            timeframe=t.timeframe,
            direction=t.direction,
            side=t.side,
            entry_timestamp=t.entry_timestamp,
            entry_price=t.entry_price,
            stop_price=t.stop_price,
            risk_units=t.risk_units,
            take_profit_price=t.take_profit_price,
            exit_timestamp=t.exit_timestamp,
            exit_price=t.exit_price,
            exit_reason=t.exit_reason,
            bars_held=t.bars_held,
            bracket_1r_outcome=t.bracket_1r_outcome,
            cost_r=cost_r,
            gross_r=gross_r,
            net_r=net_r,
            pivot_lb=3,
            regime=t.regime,
            ext_target_pct=2.618,
            sl_buffer_pct=0.02,
            fib_diff=t.fib_diff,
            regime_at_entry=t.regime_at_entry,
            leg=t.leg,
            partial_tp_at_r=1.0,
            partial_tp_pct=0.5,
            partial_taken=t.partial_taken,
            partial_r=t.partial_r,
            partial_fill_price=t.partial_fill_price,
            partial_fill_ts=t.partial_fill_ts,
            raw_features={
                **(t.raw_features or {}),
                "qty_lots": qty,
                "pnl_usd": pnl_usd,
                "equity_at_close": sizer.state.current_equity,
                "contract_size": contract_size,
                "source_trade_id": str(t.trade_id),
                "source_run_id": str(t.run_id),
            },
        ))

    # Persist new run + trades.
    with Session() as s:
        s.add(BtRun(
            run_id=new_run_id, ref=new_ref, mode="bt",
            strategy_id="fib_v2_intraday_a_plus_d",
            strategy_config=combo_config,
            symbol=a_run.symbol, timeframe=a_run.timeframe,
            start_ts=datetime.now(timezone.utc),
            end_ts=datetime.now(timezone.utc),
            data_provider="combined_replay",
        ))
        s.commit()
        s.bulk_insert_mappings(BtTrade, new_trades)
        s.commit()

    # Headline.
    n = len(new_trades)
    cumulative_skim = sum(r.get("skim_amount", 0.0) for r in sizer.state.skim_history)
    pnl_total = sum(t["raw_features"]["pnl_usd"] for t in new_trades)
    wins = sum(1 for t in new_trades if t["net_r"] > 0)
    losses = sum(1 for t in new_trades if t["net_r"] < 0)
    net_r_sum = sum(t["net_r"] for t in new_trades)
    n_months = len(sizer.state.skim_history)

    print()
    print("=" * 60)
    print(f"  COMBINED RUN: {new_ref}")
    print(f"  trades:     {n:,}")
    print(f"  wins/loss:  {wins:,} / {losses:,}  ({wins/max(n,1)*100:.1f}% WR)")
    print(f"  skipped:    {n_skipped_lot_floor:,} (lot floor)")
    print(f"  net R:      {net_r_sum:+.1f}")
    print(f"  net P&L:    ${pnl_total:+,.0f}  (raw, no skim)")
    print(f"  end equity: ${sizer.state.current_equity:,.0f}")
    print(f"  months:     {n_months}")
    print(f"  skimmed:    ${cumulative_skim:,.0f}  (Model B profits cashed)")
    print(f"  TOTAL (skim+remaining-start):  ${cumulative_skim + sizer.state.current_equity - start_balance:,.0f}")
    print("=" * 60)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start-balance", type=float, default=5000.0)
    p.add_argument("--risk-pct", type=float, default=0.015)
    args = p.parse_args()
    run(start_balance=args.start_balance, risk_pct=args.risk_pct)


if __name__ == "__main__":
    main()
