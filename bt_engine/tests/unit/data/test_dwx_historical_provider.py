"""Unit tests for Mt5HistoricalDataProvider — uses tmp_path simulated DWX dir."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.data.dwx_historical_provider import Mt5HistoricalDataProvider


def _write_bars(dwx_dir: Path, symbol: str, tf: str, bars: list[dict]) -> None:
    safe = symbol.replace(".", "_")
    p = dwx_dir / f"bars_{safe}_{tf}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bars))


def _make_bars(n: int, start: str = "2026.06.25 20:00:00") -> list[dict]:
    base = pd.to_datetime(start, format="%Y.%m.%d %H:%M:%S", utc=True)
    out = []
    for i in range(n):
        ts = base + pd.Timedelta(hours=i)
        price = 1000.0 + i
        out.append({
            "time": ts.strftime("%Y.%m.%d %H:%M:%S"),
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price + 0.5,
            "volume": 1000 + i,
            "spread": 10,
        })
    return out


def test_loads_dwx_bars_into_normalized_frame(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(10))
    p = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1")
    f = p.frame
    assert len(f) == 10
    assert f["timestamp"].dt.tz is not None
    assert "spread" in f.columns


def test_history_up_to_filters(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(5))
    p = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1")
    cutoff = pd.Timestamp("2026-06-25T22:00:00Z")
    h = p.history_up_to(cutoff)
    assert (h["timestamp"] <= cutoff).all()
    assert len(h) == 3


def test_bars_iterator_yields_valid(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(3))
    p = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1")
    bars = list(p.bars())
    assert len(bars) == 3
    assert all(b.symbol == "XAUUSD.ecn" for b in bars)
    assert bars[0].low <= bars[0].close <= bars[0].high


def test_start_end_filter(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(10))
    p = Mt5HistoricalDataProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        start=pd.Timestamp("2026-06-25T22:00:00Z"),
        end=pd.Timestamp("2026-06-26T00:00:00Z"),
    )
    f = p.frame
    assert len(f) == 3  # 22, 23, 00


def test_refresh_appends_new_bars(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(3))
    p = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1")
    assert len(p.frame) == 3
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(5))
    appended = p.refresh()
    assert appended == 2
    assert len(p.frame) == 5


def test_rejects_unsupported_timeframe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not write bars"):
        Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "M15")


def test_rejects_invalid_timeframe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown timeframe"):
        Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "Q9")
