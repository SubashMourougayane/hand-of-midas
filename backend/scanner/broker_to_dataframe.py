"""Adapter: live broker candle list[dict] → BT-compatible pandas DataFrame.

Built for the Phase 2-5 refactor that unifies live signal-gen with BT's
`generate_signals()`. Live schedulers fetch candles from DWX (MT5) or OANDA
as `list[dict]`. BT engines work on `pd.DataFrame` with explicit bid/ask
columns, computed mid columns, and a UTC `DatetimeIndex`.

This module is the ONE place that handles broker-quirk normalisation. Both
Micros (Gold + Oil) call it. Both BT engines load the same shape via
`backend/data/cache.py:load_candles()`.

Reference for column shape: `backend/data/cache.py:load_candles()`.
Reference for live dict shape: `get_candles(instrument, granularity,
count, price="BA")` returns from `backend/execution/oanda_executor.py`
and `backend/execution/mt5_executor.py`.

NO LIVE OR BT CODE EDITS at Phase 1 — this is a NEW module that Phase 4-5
will WIRE IN. Phase 1 just builds the adapter + tests.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd


_REQUIRED_PRICE_KEYS = (
    "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close",
)


def _parse_broker_timestamp(ts: str | datetime) -> pd.Timestamp:
    """Parse a broker timestamp into a tz-aware UTC `pd.Timestamp`.

    Handles three observed formats:
    - DWX/MT5: `"2026.06.18 13:00:00"` (server-time, no tz). Treated as UTC.
    - OANDA:   `"2026-06-18T13:00:00.000000000Z"` (nanosecond precision, Z=UTC).
                The 9-digit fractional second is truncated to 6 digits because
                Python's `datetime.fromisoformat` only handles microseconds.
                Same trick `backend-micro/scanner/scheduler.py:_parse_ts` uses.
    - ISO 8601 with offset: `"2026-06-18T13:00:00+00:00"` — passed through.

    Already-parsed `datetime` / `pd.Timestamp` are coerced to UTC.
    """
    if isinstance(ts, pd.Timestamp):
        return ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return pd.Timestamp(ts).tz_convert("UTC")

    if not isinstance(ts, str):
        raise TypeError(f"unsupported timestamp type: {type(ts).__name__}")

    cleaned = ts.strip()
    if not cleaned:
        raise ValueError("empty timestamp string")

    # OANDA "Z" → "+00:00" so fromisoformat accepts it
    cleaned = cleaned.replace("Z", "+00:00")
    # OANDA nanosecond precision: truncate to microseconds
    cleaned = re.sub(r"(\.\d{6})\d+", r"\1", cleaned)

    # DWX server-time uses dots: "2026.06.18 13:00:00". Convert to ISO.
    if re.match(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", cleaned):
        cleaned = cleaned.replace(".", "-", 2).replace(" ", "T", 1)

    parsed = pd.Timestamp(cleaned)
    return parsed.tz_convert("UTC") if parsed.tzinfo else parsed.tz_localize("UTC")


def broker_bars_to_dataframe(bars: Iterable[dict]) -> pd.DataFrame:
    """Convert a list of broker candle dicts to a BT-format DataFrame.

    Args:
        bars: Iterable of dicts. Each dict expected keys:
              - `timestamp` (string or datetime)
              - `bid_open, bid_high, bid_low, bid_close` (floats)
              - `ask_open, ask_high, ask_low, ask_close` (floats)
              - `volume` (int, optional — defaults to 0)
              - `complete` (bool, optional — bars with complete=False are dropped)

    Returns:
        `pd.DataFrame` with:
        - `DatetimeIndex(tz='UTC')`, sorted ascending, deduplicated (keep last).
        - Columns: `bid_open, bid_high, bid_low, bid_close,
                    ask_open, ask_high, ask_low, ask_close,
                    mid_open, mid_high, mid_low, mid_close,
                    spread, volume`
        Returns an empty DataFrame (not an error) if `bars` is empty
        OR if every bar is `complete=False`.

    Behaviour notes:
    - Mid columns and spread are computed from bid/ask, matching
      `backend/data/cache.py:load_candles()` exactly.
    - Duplicate timestamps keep the LAST value (matches `cache.py`).
    - Bars missing required price keys raise `KeyError` (defensive — caller
      should pass clean broker output).
    """
    bars_list = list(bars) if bars is not None else []
    if not bars_list:
        return pd.DataFrame()

    rows = []
    for bar in bars_list:
        # Drop incomplete bars (DWX sends in-progress bar with complete=False
        # at the end of fresh fetches; live schedulers already filter these
        # at the call site, but the adapter is defensive).
        if bar.get("complete") is False:
            continue
        # Validate required keys to fail loudly if a broker change drops one.
        missing = [k for k in _REQUIRED_PRICE_KEYS if k not in bar]
        if missing:
            raise KeyError(
                f"broker bar missing required keys: {missing} "
                f"(bar keys: {sorted(bar.keys())})"
            )
        ts = _parse_broker_timestamp(bar["timestamp"])
        rows.append({
            "timestamp": ts,
            "bid_open": float(bar["bid_open"]),
            "bid_high": float(bar["bid_high"]),
            "bid_low": float(bar["bid_low"]),
            "bid_close": float(bar["bid_close"]),
            "ask_open": float(bar["ask_open"]),
            "ask_high": float(bar["ask_high"]),
            "ask_low": float(bar["ask_low"]),
            "ask_close": float(bar["ask_close"]),
            "volume": int(bar.get("volume", 0)),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    # Mid prices + spread (mirror `backend/data/cache.py:load_candles`)
    df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
    df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
    df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
    df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
    df["spread"] = df["ask_close"] - df["bid_close"]

    return df
