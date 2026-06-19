"""Tape Server — chronological CSV → bar stream.

Reads `data/raw/{instrument}_{tf}.csv` (M3, H1, D) into memory pandas
DataFrames. Maintains a "tape clock" that advances on demand. Exposes:

- `current_time()` — the current tape timestamp (UTC, aware datetime)
- `advance_to(ts)` — jump tape clock to ts (must be monotonically forward)
- `get_window(instrument, granularity, count)` — return last N bars whose
  timestamp ≤ current_time (this is the "live broker view")
- `get_current_bar(instrument, granularity)` — return the bar at exactly
  current_time, or None if no bar exists at that exact ts
- `iter_bars(instrument, granularity, start, end)` — yield bars in slice

Data is stored as pandas DataFrames indexed by timestamp (UTC tz-aware).
Lookups are O(log N) via index `searchsorted`.

The tape server is **passive** — it doesn't push. The replay runner advances
the clock and pulls. This makes the runner deterministic.

NEVER mutates source CSVs. NEVER writes to disk.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DATA_DIR = os.path.join(REPO_ROOT, "data", "raw")


# Live's get_candles returns dict[] with these keys. We store DataFrames
# internally but emit dicts shaped like live's broker view for parity.
LIVE_BAR_KEYS = (
    "timestamp", "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close", "volume",
)


@dataclass
class TapeServer:
    """Holds source data + advances clock. Single instance per replay run."""

    instruments: tuple[str, ...] = ("XAU_USD", "BCO_USD")
    granularities: tuple[str, ...] = ("M3", "H1", "D")
    _data: dict[tuple[str, str], pd.DataFrame] = field(default_factory=dict)
    _clock: Optional[datetime] = None

    def load(self) -> None:
        """Read every (instrument, granularity) CSV into memory."""
        for inst in self.instruments:
            for gran in self.granularities:
                path = os.path.join(RAW_DATA_DIR, f"{inst}_{gran}.csv")
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"Tape source missing: {path}")
                df = pd.read_csv(path, parse_dates=["timestamp"])
                # Normalize timestamps to tz-aware UTC. Source CSVs are
                # already +00:00 marked, but be defensive.
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
                df = df.set_index("timestamp").sort_index()
                # Drop duplicate timestamps (last write wins) — defensive
                df = df[~df.index.duplicated(keep="last")]
                self._data[(inst, gran)] = df

    def date_range(self, instrument: str = "XAU_USD",
                   granularity: str = "M3") -> tuple[datetime, datetime]:
        """Return (first_ts, last_ts) for a given source."""
        df = self._require_data(instrument, granularity)
        return df.index[0].to_pydatetime(), df.index[-1].to_pydatetime()

    # ── Clock control ───────────────────────────────────────────────────

    def set_clock(self, ts: datetime) -> None:
        """Set tape clock initially. Idempotent only on first call —
        subsequent calls must use advance_to()."""
        ts_utc = self._to_utc(ts)
        if self._clock is not None and ts_utc < self._clock:
            raise ValueError(
                f"Clock cannot move backwards: current={self._clock} "
                f"requested={ts_utc}"
            )
        self._clock = ts_utc

    def advance_to(self, ts: datetime) -> None:
        """Move tape clock forward (or stay). Backward is an error."""
        ts_utc = self._to_utc(ts)
        if self._clock is None:
            self._clock = ts_utc
            return
        if ts_utc < self._clock:
            raise ValueError(
                f"Tape clock cannot move backwards: current={self._clock} "
                f"requested={ts_utc}"
            )
        self._clock = ts_utc

    def current_time(self) -> datetime:
        if self._clock is None:
            raise RuntimeError("Tape clock not initialised. Call set_clock() first.")
        return self._clock

    # ── Data access (matches live broker semantics) ─────────────────────

    def get_window(self, instrument: str, granularity: str,
                   count: int) -> list[dict]:
        """Return the last `count` bars whose timestamp is STRICTLY ≤ clock.

        This mirrors live's get_candles() which returns the most-recent N
        bars the broker has written. Excludes bars FROM THE FUTURE (which
        the tape has but live wouldn't).

        Returns: list[dict] in chronological order, oldest-first.
        """
        df = self._require_data(instrument, granularity)
        clock = self.current_time()
        # Bars with index ≤ clock. Note: live's broker view returns
        # COMPLETED bars only. The bar AT clock-time is "in progress" by
        # convention — exclude it (use < not ≤). Live's bar_ts is the
        # bar's CLOSE time though, so a 14:09 bar means [14:06, 14:09)
        # data — by the time clock reads 14:09:00.000 the bar IS complete.
        # Be generous and include exact-match.
        idx = df.index.searchsorted(clock, side="right")
        start = max(0, idx - count)
        slice_df = df.iloc[start:idx]
        return [
            self._row_to_dict(ts, row)
            for ts, row in slice_df.iterrows()
        ]

    def get_current_bar(self, instrument: str, granularity: str) -> Optional[dict]:
        """Return the bar EXACTLY AT clock-time, or None."""
        df = self._require_data(instrument, granularity)
        clock = self.current_time()
        if clock not in df.index:
            return None
        return self._row_to_dict(clock, df.loc[clock])

    def get_current_tick(self, instrument: str) -> Optional[dict]:
        """Return a synthetic 'live tick' from the most-recent M3 bar's close.

        Live's get_current_price() returns {bid, ask, mid, spread, time, tradeable}.
        We approximate from the latest M3 bar at-or-before clock-time.
        """
        # Use M3 since that's the finest tape resolution.
        df = self._require_data(instrument, "M3")
        clock = self.current_time()
        idx = df.index.searchsorted(clock, side="right")
        if idx == 0:
            return None
        bar_ts = df.index[idx - 1]
        row = df.loc[bar_ts]
        bid = float(row["bid_close"])
        ask = float(row["ask_close"])
        return {
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2,
            "spread": ask - bid,
            "time": bar_ts.strftime("%Y.%m.%d %H:%M:%S"),
            "tradeable": True,
        }

    def iter_bars(self, instrument: str, granularity: str,
                  start: datetime, end: datetime):
        """Yield bars in [start, end] (both inclusive) in chronological order.

        Used by the replay runner to drive cron ticks; NOT used as broker view.
        """
        df = self._require_data(instrument, granularity)
        s = self._to_utc(start)
        e = self._to_utc(end)
        slice_df = df.loc[s:e]
        for ts, row in slice_df.iterrows():
            yield self._row_to_dict(ts, row)

    # ── Internals ───────────────────────────────────────────────────────

    def _require_data(self, instrument: str, granularity: str) -> pd.DataFrame:
        key = (instrument, granularity)
        if key not in self._data:
            raise KeyError(
                f"Tape source not loaded: {key}. Did you call .load()?"
            )
        return self._data[key]

    @staticmethod
    def _to_utc(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @staticmethod
    def _row_to_dict(ts, row) -> dict:
        return {
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "bid_open": float(row["bid_open"]),
            "bid_high": float(row["bid_high"]),
            "bid_low": float(row["bid_low"]),
            "bid_close": float(row["bid_close"]),
            "ask_open": float(row["ask_open"]),
            "ask_high": float(row["ask_high"]),
            "ask_low": float(row["ask_low"]),
            "ask_close": float(row["ask_close"]),
            "volume": int(row["volume"]),
            # Live broker view also has 'complete' (always True for
            # historical CSV bars). Add for compatibility with live's
            # `complete=True` filter in scheduler.
            "complete": True,
        }
