"""Live ↔ replay parity.

Simulates a captured live stream by writing the bars JSON in chunks (as the EA
would over time). Verifies that the sequence of bars yielded by the live
provider equals what a historical provider would read from the final snapshot.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.data.dwx_historical_provider import Mt5HistoricalDataProvider
from bt_engine.data.dwx_live_provider import Mt5LiveBarProvider


def _make_bar(hour_offset: int) -> dict:
    base = pd.Timestamp("2026-06-29T00:00:00Z")
    ts = base + pd.Timedelta(hours=hour_offset)
    p = 1000.0 + hour_offset
    return {
        "time": ts.strftime("%Y.%m.%d %H:%M:%S"),
        "open": p, "high": p+1, "low": p-1, "close": p+0.5,
        "volume": 100 + hour_offset, "spread": 10,
    }


def _write_bars(dwx_dir: Path, symbol: str, tf: str, bars: list[dict]) -> None:
    safe = symbol.replace(".", "_")
    p = dwx_dir / f"bars_{safe}_{tf}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bars))


def test_live_yielded_sequence_equals_historical_snapshot(tmp_path: Path) -> None:
    """Stream 5 bars to disk one at a time; collect what live provider yields."""
    final = [_make_bar(i) for i in range(5)]

    # walk wall-clock forward through the bar closes
    yielded = []
    now_state = ["2026-06-29T00:30:00+00:00"]
    live = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=lambda: datetime.fromisoformat(now_state[0]),
    )

    # progressively grow the bars file as the EA would do
    for i in range(1, 6):
        # write bars 0..i-1 (EA always writes the rolling buffer)
        _write_bars(tmp_path, "XAUUSD.ecn", "H1", final[:i])
        # advance wall clock so bar i-1 is now closed
        now_state[0] = f"2026-06-29T{i:02d}:30:00+00:00"
        bar = live.next_closed_bar()
        if bar is not None:
            yielded.append(bar)

    # at end, historical provider sees all 5 bars; with wall clock at 05:30 all
    # five bars (00..04) are closed and yielded exactly once
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", final)
    hist = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1")

    yielded_ts = [b.timestamp for b in yielded]
    hist_ts = list(hist.frame["timestamp"])
    assert yielded_ts == hist_ts


def test_replay_history_up_to_matches_live_history(tmp_path: Path) -> None:
    bars = [_make_bar(i) for i in range(4)]
    _write_bars(tmp_path, "XAUUSD.ecn", "H1", bars)

    live = Mt5LiveBarProvider(
        DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1",
        now_fn=lambda: datetime.fromisoformat("2026-06-29T04:30:00+00:00"),
    )
    hist = Mt5HistoricalDataProvider(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn", "H1")

    cutoff = pd.Timestamp("2026-06-29T02:00:00Z")
    live_h = live.history_up_to(cutoff)[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    hist_h = hist.history_up_to(cutoff)[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(live_h, hist_h, check_dtype=False)
