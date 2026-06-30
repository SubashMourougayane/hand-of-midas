"""Provider parity: CSV provider vs DWX-historical provider on identical input.

Both providers must produce the same engine-contract frame:
    timestamp (UTC), open, high, low, close, volume (+ optional spread).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bt_engine.data.csv_provider import CsvHistoricalProvider
from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.data.dwx_historical_provider import Mt5HistoricalDataProvider


def _make_h1_csv(tmp_path: Path, n: int) -> Path:
    """Synthesize an MT5-format tab-separated CSV with H1 bars."""
    base = pd.Timestamp("2026-06-25T20:00:00Z")
    rows = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for i in range(n):
        ts = base + pd.Timedelta(hours=i)
        p = 1000.0 + i
        rows.append(
            f"{ts.strftime('%Y.%m.%d')}\t{ts.strftime('%H:%M:%S')}\t"
            f"{p}\t{p+1.0}\t{p-1.0}\t{p+0.5}\t{1000+i}\t0\t10"
        )
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "test_h1.csv"
    path.write_text("\n".join(rows) + "\n")
    return path


def _make_h1_dwx(tmp_path: Path, symbol: str, n: int) -> Path:
    """Synthesize DWX bars JSON in tmp_path."""
    base = pd.Timestamp("2026-06-25T20:00:00Z")
    bars = []
    for i in range(n):
        ts = base + pd.Timedelta(hours=i)
        p = 1000.0 + i
        bars.append({
            "time": ts.strftime("%Y.%m.%d %H:%M:%S"),
            "open": p, "high": p+1.0, "low": p-1.0, "close": p+0.5,
            "volume": 1000+i, "spread": 10,
        })
    safe = symbol.replace(".", "_")
    tmp_path.mkdir(parents=True, exist_ok=True)
    p_path = tmp_path / f"bars_{safe}_H1.json"
    p_path.write_text(json.dumps(bars))
    return p_path


def test_csv_and_dwx_providers_return_identical_frame(tmp_path: Path) -> None:
    n = 10
    csv_path = _make_h1_csv(tmp_path / "csv", n)
    _make_h1_dwx(tmp_path / "dwx", "XAUUSD.ecn", n)

    csv = CsvHistoricalProvider(csv_path, symbol="XAUUSD.ecn", timeframe="H1", source_timeframe="H1")
    dwx = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path / "dwx"), "XAUUSD.ecn", "H1")

    csv_f = csv.frame[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    dwx_f = dwx.frame[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    pd.testing.assert_frame_equal(csv_f, dwx_f, check_dtype=False)


def test_csv_and_dwx_history_up_to_aligned(tmp_path: Path) -> None:
    n = 8
    csv_path = _make_h1_csv(tmp_path / "csv", n)
    _make_h1_dwx(tmp_path / "dwx", "XAUUSD.ecn", n)
    csv = CsvHistoricalProvider(csv_path, symbol="XAUUSD.ecn", timeframe="H1", source_timeframe="H1")
    dwx = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path / "dwx"), "XAUUSD.ecn", "H1")
    cutoff = pd.Timestamp("2026-06-25T23:00:00Z")
    csv_h = csv.history_up_to(cutoff)[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    dwx_h = dwx.history_up_to(cutoff)[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(csv_h, dwx_h, check_dtype=False)


def test_bars_iterators_yield_same_bars(tmp_path: Path) -> None:
    n = 5
    csv_path = _make_h1_csv(tmp_path / "csv", n)
    _make_h1_dwx(tmp_path / "dwx", "XAUUSD.ecn", n)
    csv = CsvHistoricalProvider(csv_path, symbol="XAUUSD.ecn", timeframe="H1", source_timeframe="H1")
    dwx = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path / "dwx"), "XAUUSD.ecn", "H1")
    csv_bars = list(csv.bars())
    dwx_bars = list(dwx.bars())
    assert len(csv_bars) == len(dwx_bars) == n
    for cb, db in zip(csv_bars, dwx_bars):
        assert cb.timestamp == db.timestamp
        assert cb.open == db.open
        assert cb.high == db.high
        assert cb.low == db.low
        assert cb.close == db.close
        assert cb.volume == db.volume
