"""Unit tests for run_backtest end-to-end."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bt_engine.runner.backtest import DEFAULT_LEDGER, run_backtest


REPO_ROOT = Path(__file__).resolve().parents[4]
LEDGER = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


pytestmark = pytest.mark.skipif(not LEDGER.is_file(), reason="ledger missing")


def test_run_backtest_writes_csv_and_summary(tmp_path: Path, db_session) -> None:
    """db_session fixture wipes all bt_* tables before run so trade_ref is unique."""
    result = run_backtest(
        strategy="sdr001",
        ledger_path=LEDGER,
        out_dir=tmp_path,
        db_url=os.environ.get(
            "BT_ENGINE_TEST_DB_URL",
            "postgresql+psycopg2://subash@localhost:5432/golddigger_bt_test",
        ),
    )
    assert result.trades_inserted == 1032
    assert result.trades_csv.exists()
    assert result.summary_json.exists()
    summary = json.loads(result.summary_json.read_text())
    assert summary["trades"] == 1032
    assert summary["positive_years_ratio"] == "8/8"
    assert abs(summary["net_r"] - 256.106675) < 1e-3
