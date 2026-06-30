"""Unit tests for TradeRecorder."""
from __future__ import annotations

import csv
from pathlib import Path

from bt_engine.core.recorder import TradeRecorder


def test_recorder_writes_csv(tmp_path: Path) -> None:
    r = TradeRecorder(out_dir=tmp_path, filename="t.csv")
    r.record({"trade_ref": "T1", "entry_price": 100.0, "net_r": 1.0, "direction": "demand"})
    r.record({"trade_ref": "T2", "entry_price": 200.0, "net_r": -0.5, "direction": "supply"})
    out = r.finalize()
    assert out.exists()
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 2
    assert rows[0]["trade_ref"] == "T1"
    assert rows[1]["net_r"] == "-0.5"


def test_recorder_finalize_empty(tmp_path: Path) -> None:
    r = TradeRecorder(out_dir=tmp_path)
    out = r.finalize()
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 0


def test_recorder_extras_ignored(tmp_path: Path) -> None:
    r = TradeRecorder(out_dir=tmp_path)
    r.record({"trade_ref": "T1", "net_r": 1.0, "unknown_col": "ignored"})
    out = r.finalize()
    rows = list(csv.DictReader(out.open()))
    assert "unknown_col" not in rows[0]
