"""Partial-TP evidence pack — runs PTP+1R and PTP+2R variants through the
production bt_engine code path, persists all trades to PostgreSQL with the new
partial_* columns populated, and emits the same anatomy CSVs as the baseline.

Re-uses `build_fib_v2_evidence_pack` helpers; only override is the strategy
config (partial_tp_at_r=N) + the persistence row (write partial_* fields).

NO LOOK-AHEAD. NO PHANTOM FILLS.
"""
from __future__ import annotations

import os
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.data.multi_tf_view import MultiTfHistoryView
from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtTrade
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2 import (
    FibV2EnsembleStrategy,
    LONG_BULL_STRONG,
    SHORT_BEAR_STRONG,
)
from bt_engine.strategies.fib_v2.config import FibV2Config

from build_fib_v2_evidence_pack import (
    InMemoryClock,
    InMemoryProvider,
    emit_monthly,
    emit_yearly,
    load_oanda,
    HORIZON_BARS,
)


OUT_DIR = Path("/Users/subash/SUBASH/GoldDigger/bt_engine/evidence/fib_v2_ptp_anatomy")
DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)


VARIANTS = [
    # (label, symbol, m5, h1, cost, legs, ptp_r)
    ("xau_ensemble_ptp1r", "XAUUSD.ecn",
     "/tmp/oanda_xau_m5.parquet", "/tmp/oanda_xau_h1.parquet",
     0.30, (LONG_BULL_STRONG, SHORT_BEAR_STRONG), 1.0),
    ("xau_ensemble_ptp2r", "XAUUSD.ecn",
     "/tmp/oanda_xau_m5.parquet", "/tmp/oanda_xau_h1.parquet",
     0.30, (LONG_BULL_STRONG, SHORT_BEAR_STRONG), 2.0),
    ("eur_ensemble_ptp1r", "EURUSD.ecn",
     "/tmp/oanda_eur_m5.parquet", "/tmp/oanda_eur_h1.parquet",
     0.00003, (LONG_BULL_STRONG, SHORT_BEAR_STRONG), 1.0),
    ("eur_ensemble_ptp2r", "EURUSD.ecn",
     "/tmp/oanda_eur_m5.parquet", "/tmp/oanda_eur_h1.parquet",
     0.00003, (LONG_BULL_STRONG, SHORT_BEAR_STRONG), 2.0),
]


def run_ptp_variant(*, label, symbol, m5_path, h1_path, cost_usd, legs, ptp_r):
    print(f"\n[{label}] loading {Path(m5_path).name} (PTP+{ptp_r}R)...")
    m5, h1 = load_oanda(m5_path, h1_path)
    print(f"  M5={len(m5):,} bars, range {m5.timestamp.min()} → {m5.timestamp.max()}")

    mtf = MultiTfHistoryView(m5)
    if h1 is not None:
        mtf._h1 = h1
    provider = InMemoryProvider(m5, symbol=symbol)
    clock = InMemoryClock(provider)

    cfg = FibV2Config()
    cfg = replace(cfg, partial_tp_at_r=ptp_r, partial_tp_pct=0.5)
    strat = FibV2EnsembleStrategy(
        symbol=symbol, legs=tuple(legs), cost_usd=cost_usd,
        multi_tf_view=mtf, config=cfg,
    )

    run_id = uuid.uuid4()
    run_ref = f"PTP-{label}-{run_id}"
    engine_db = make_engine(DB_URL)
    strategy_id = f"fib_v2_xau_ensemble_ptp{int(ptp_r)}r"

    with Session(engine_db, expire_on_commit=False) as session:
        bt_run = BtRun(
            run_id=run_id, ref=run_ref, mode="bt",
            strategy_id=strategy_id,
            strategy_config={
                "pivot_lb": 5, "ext_target_pct": 1.618, "sl_buffer_pct": 0.02,
                "legs": [l.leg_name for l in legs],
                "cost_usd": cost_usd, "variant": label,
                "partial_tp_at_r": ptp_r, "partial_tp_pct": 0.5,
            },
            symbol=symbol, timeframe="M5",
            start_ts=datetime.now(timezone.utc),
            data_provider="oanda_parquet",
        )
        session.add(bt_run)
        session.commit()

    rows = []

    def _on_close(trade, outcome):
        cost_r = trade.order.extra.get("cost_r", 0.0)
        net_r = outcome.bracket_1r_outcome - cost_r
        leg_name = trade.order.extra.get("leg")
        regime = trade.order.extra.get("regime")
        trade_ref = f"FIB-{label.upper()}-{trade.trade_id}"
        partial_fill_ts = (
            trade.partial_fill_timestamp.to_pydatetime()
            if trade.partial_fill_timestamp is not None else None
        )
        with Session(engine_db, expire_on_commit=False) as session:
            bt_t = BtTrade(
                trade_id=trade.trade_id, trade_ref=trade_ref, run_id=run_id,
                strategy_id=strategy_id,
                symbol=symbol, timeframe="M5",
                direction="long" if trade.side > 0 else "short", side=trade.side,
                entry_timestamp=trade.entry_timestamp.to_pydatetime(),
                entry_price=trade.entry_price,
                stop_price=trade.stop_price, risk_units=trade.risk_units,
                take_profit_price=trade.take_profit,
                exit_timestamp=outcome.exit_timestamp.to_pydatetime(),
                exit_price=outcome.exit_price, exit_reason=outcome.reason,
                bars_held=outcome.bars_held,
                bracket_1r_outcome=outcome.bracket_1r_outcome,
                cost_r=cost_r,
                gross_r=outcome.bracket_1r_outcome,
                net_r=net_r,
                pivot_lb=trade.order.extra.get("pivot_lb"),
                regime=regime,
                ext_target_pct=trade.order.extra.get("ext_target_pct"),
                sl_buffer_pct=trade.order.extra.get("sl_buffer_pct"),
                fib_diff=trade.order.extra.get("fib_diff"),
                regime_at_entry=trade.order.extra.get("regime_at_entry"),
                leg=leg_name,
                partial_tp_at_r=ptp_r,
                partial_tp_pct=0.5,
                partial_taken=trade.partial_taken,
                partial_r=trade.partial_filled_r,
                partial_fill_price=trade.partial_fill_price,
                partial_fill_ts=partial_fill_ts,
                raw_features=trade.order.extra,
            )
            session.add(bt_t)
            session.commit()

        rows.append({
            "trade_ref": trade_ref,
            "run_id": str(run_id),
            "leg": leg_name,
            "regime": regime,
            "side": int(trade.side),
            "entry_ts": trade.entry_timestamp,
            "exit_ts": outcome.exit_timestamp,
            "bars_held": outcome.bars_held,
            "entry_price": float(trade.entry_price),
            "stop_price": float(trade.stop_price),
            "tp_price": float(trade.take_profit) if trade.take_profit else None,
            "exit_price": float(outcome.exit_price),
            "exit_reason": outcome.reason,
            "fib_L": trade.order.extra.get("fib_L"),
            "fib_H": trade.order.extra.get("fib_H"),
            "fib_diff": trade.order.extra.get("fib_diff"),
            "risk_units": float(trade.risk_units),
            "bracket_r": float(outcome.bracket_1r_outcome),
            "cost_r": float(cost_r),
            "net_r": float(net_r),
            "mfe_r": float(trade.mfe_r),
            "mae_r": float(trade.mae_r),
            "partial_taken": bool(trade.partial_taken),
            "partial_r": float(trade.partial_filled_r),
            "partial_fill_price": (
                float(trade.partial_fill_price)
                if trade.partial_fill_price is not None else None
            ),
            "partial_fill_ts": (
                trade.partial_fill_timestamp.isoformat()
                if trade.partial_fill_timestamp is not None else None
            ),
            "year": trade.entry_timestamp.year,
            "month": trade.entry_timestamp.strftime("%Y-%m"),
            "symbol": symbol,
            "variant": label,
            "ptp_r": ptp_r,
        })

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_open=lambda t: None, on_trade_close=_on_close,
        max_bars_held=HORIZON_BARS,
    )
    print(f"  running engine...")
    run = run_engine(run_id=run_id, deps=deps, mode="bt")
    print(f"  bars processed: {run.bars_processed:,}, closed trades: {len(rows)}")

    with Session(engine_db, expire_on_commit=False) as session:
        rec = session.execute(select(BtRun).where(BtRun.run_id == run_id)).scalar_one()
        rec.end_ts = datetime.now(timezone.utc)
        session.commit()

    return pd.DataFrame(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_summaries = []

    for label, symbol, m5_path, h1_path, cost_usd, legs, ptp_r in VARIANTS:
        df = run_ptp_variant(
            label=label, symbol=symbol, m5_path=m5_path, h1_path=h1_path,
            cost_usd=cost_usd, legs=legs, ptp_r=ptp_r,
        )
        if df.empty:
            print(f"[{label}] empty — skipping CSV emit")
            continue
        df.to_csv(OUT_DIR / f"{label}_trades.csv", index=False)
        emit_monthly(df, label).to_csv(OUT_DIR / f"{label}_monthly.csv", index=False)
        emit_yearly(df, label).to_csv(OUT_DIR / f"{label}_yearly.csv", index=False)

        n = len(df)
        wins = int((df["net_r"] > 0).sum())
        losses = -float(df.loc[df["net_r"] < 0, "net_r"].sum())
        winnings = float(df.loc[df["net_r"] > 0, "net_r"].sum())
        pf = winnings / losses if losses > 0 else float("inf")
        net_R = float(df["net_r"].sum())
        partial_hit_rate = float(df["partial_taken"].mean())
        all_summaries.append({
            "variant": label, "ptp_r": ptp_r, "n": n,
            "wins": wins, "WR%": round(wins / n * 100, 2),
            "PF": round(pf, 3), "net_R": round(net_R, 1),
            "partial_taken_rate%": round(partial_hit_rate * 100, 2),
            "avg_partial_r_per_trade": round(float(df["partial_r"].mean()), 3),
        })
        print(f"[{label}] n={n} WR={wins/n*100:.1f}% PF={pf:.2f} net={net_R:+.1f}R partial_hit={partial_hit_rate*100:.1f}%")

    if all_summaries:
        pd.DataFrame(all_summaries).to_csv(OUT_DIR / "ptp_summary_headline.csv", index=False)
        print(f"\nSaved summary → {OUT_DIR}/ptp_summary_headline.csv")


if __name__ == "__main__":
    main()
