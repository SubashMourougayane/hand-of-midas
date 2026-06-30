"""run_backtest — Phase-1 parity replay end-to-end.

Reads the SDR-001 frozen ledger, streams it through bt_engine's DB + CSV layer,
emits a summary file with headline numbers, and returns the run id.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import sessionmaker

from ..core.recorder import TradeRecorder
from ..db.engine import make_engine
from ..db.repo import RunRepo
from ..strategies.sdr001.parity_replay import load_ledger, replay_to_db
from ..strategies.sdr001.summary import HeadlineSummary, headline


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


@dataclass
class BacktestResult:
    run_id: str
    run_ref: str
    trades_inserted: int
    headline: HeadlineSummary
    trades_csv: Path
    summary_json: Path


def run_backtest(
    *,
    strategy: str = "sdr001",
    ledger_path: str | Path = DEFAULT_LEDGER,
    out_dir: str | Path = "bt_engine/output/run01",
    db_url: str | None = None,
) -> BacktestResult:
    if strategy != "sdr001":
        raise NotImplementedError(f"Strategy not yet wired: {strategy}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    engine = make_engine(db_url) if db_url else make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        result = replay_to_db(session, ledger_path=ledger_path)
        session.commit()
    finally:
        session.close()

    # write CSV
    recorder = TradeRecorder(out_dir=out, filename=f"{strategy}_trades.csv")
    df = result.trades.copy()
    r_col = "net_1r_after_cost" if "net_1r_after_cost" in df.columns else "net_r"
    if r_col != "net_r":
        df["net_r"] = df[r_col]
    for _, row in df.iterrows():
        recorder.record(row.to_dict())
    trades_csv = recorder.finalize()

    summary = headline(df, r_col=r_col)
    summary_path = out / f"{strategy}_summary.json"
    summary_path.write_text(json.dumps(asdict(summary), indent=2))

    return BacktestResult(
        run_id=str(result.run_id),
        run_ref=result.run_ref,
        trades_inserted=result.trades_inserted,
        headline=summary,
        trades_csv=trades_csv,
        summary_json=summary_path,
    )
