"""Unit tests for Mt5LiveBarProvider — uses tmp_path DWX dir + frozen now()."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.data.dwx_live_provider import Mt5LiveBarProvider


def _make_bars(n: int, start: str = "2026.06.29 00:00:00", tf_seconds: int = 3600) -> list[dict]:
    base = pd.to_datetime(start, format="%Y.%m.%d %H:%M:%S", utc=True)
    out = []
    for i in range(n):
        ts = base + pd.Timedelta(seconds=tf_seconds * i)
        p = 1000.0 + i
        out.append({
            "time": ts.strftime("%Y.%m.%d %H:%M:%S"),
            "open": p, "high": p+1, "low": p-1, "close": p+0.5,
            "volume": 100+i, "spread": 10,
        })
    return out


def _write_bars(dwx_dir: Path, symbol: str, tf: str, bars: list[dict]) -> None:
    safe = symbol.replace(".", "_")
    p = dwx_dir / f"bars_{safe}_{tf}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bars))


def _frozen_now(s: str):
    return lambda: datetime.fromisoformat(s)


def test_yields_no_bar_when_none_closed(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(2))
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=_frozen_now("2026-06-29T00:30:00+00:00"),  # first bar still forming
    )
    assert p.next_closed_bar() is None


def test_yields_oldest_closed_bar_first(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(3))
    # at 02:30, bars 00:00 and 01:00 are closed; 02:00 still open
    # FIFO catchup: first yields 00:00, next yields 01:00
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=_frozen_now("2026-06-29T02:30:00+00:00"),
    )
    b1 = p.next_closed_bar()
    assert b1 is not None
    assert b1.timestamp == pd.Timestamp("2026-06-29T00:00:00Z")
    b2 = p.next_closed_bar()
    assert b2.timestamp == pd.Timestamp("2026-06-29T01:00:00Z")
    assert p.next_closed_bar() is None


def test_no_double_yield_same_bar(tmp_path: Path) -> None:
    """With 1 closed bar available, only 1 should ever be yielded."""
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(2))
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=_frozen_now("2026-06-29T01:30:00+00:00"),
    )
    first = p.next_closed_bar()
    second = p.next_closed_bar()
    assert first is not None
    assert second is None


def test_yields_next_bar_after_new_close(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(3))
    now_state = ["2026-06-29T01:30:00+00:00"]
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=lambda: datetime.fromisoformat(now_state[0]),
    )
    b1 = p.next_closed_bar()
    assert b1.timestamp == pd.Timestamp("2026-06-29T00:00:00Z")
    now_state[0] = "2026-06-29T02:30:00+00:00"
    b2 = p.next_closed_bar()
    assert b2.timestamp == pd.Timestamp("2026-06-29T01:00:00Z")


def test_server_utc_offset_converts_mt5_server_time_to_utc(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "M1", _make_bars(2, start="2026.06.29 10:39:00", tf_seconds=60))
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path),
        "XAUUSD.ecn",
        "M1",
        now_fn=_frozen_now("2026-06-29T07:41:00+00:00"),
        server_utc_offset_hours=3,
    )
    b1 = p.next_closed_bar()
    assert b1 is not None
    assert b1.timestamp == pd.Timestamp("2026-06-29T07:39:00Z")


def test_history_up_to_filters(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(5))
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=_frozen_now("2026-06-29T05:30:00+00:00"),
    )
    cutoff = pd.Timestamp("2026-06-29T02:00:00Z")
    h = p.history_up_to(cutoff)
    assert (h["timestamp"] <= cutoff).all()
    assert len(h) == 3


def test_can_mark_existing_closed_bars_as_seen(tmp_path: Path) -> None:
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", _make_bars(4))
    p = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=_frozen_now("2026-06-29T03:30:00+00:00"),
    )
    latest = p.latest_closed_timestamp()
    assert latest == pd.Timestamp("2026-06-29T02:00:00Z")
    p.mark_yielded_through(latest)
    assert p.next_closed_bar() is None


def test_rejects_invalid_timeframe(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Mt5LiveBarProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "Q9")
