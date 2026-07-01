"""GET /api/bars — recent OHLC bars for a symbol+timeframe.

Reads from DWX live dump (Common/Files/DWX/bars_<sym>_<tf>.json) for live mode
or from cached parquet for backtests.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/bars", tags=["bars"])


DWX_DIR = Path(os.environ.get(
    "DWX_DIR",
    str(Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5"
        "/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"),
))


def _safe_symbol(symbol: str) -> str:
    return symbol.replace(".", "_")


@router.get("")
def get_bars(
    symbol: str = Query("XAUUSD.ecn"),
    tf: str = Query("M15"),
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    around_ts: str | None = Query(None, description="ISO ts; returns N bars centered around it"),
    n_before: int = 8,
    n_after: int = 2,
) -> list[dict]:
    """Return OHLC bars filtered by time range or windowed around a timestamp.

    Three modes:
      ?from=...&to=...                  → bars in [from, to]
      ?around_ts=...&n_before=8&n_after=2 → 8 bars before + signal bar + 2 after
      (none)                             → last 50 bars
    """
    path = DWX_DIR / f"bars_{_safe_symbol(symbol)}_{tf}.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return []
    if not isinstance(raw, list):
        return []

    # Each entry: {time, open, high, low, close, volume, spread}
    # Server offset is +3 — most DWX feeds. We pass timestamps as-is and let
    # the frontend handle display.
    rows = []
    for b in raw:
        ts_str = b.get("time", "")
        try:
            # Format: "2026.06.30 23:00:00"
            ts = datetime.strptime(ts_str, "%Y.%m.%d %H:%M:%S")
            # Apply DWX server offset → UTC. Server is UTC+3.
            ts_utc = ts - timedelta(hours=3)
            ts_iso = ts_utc.replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            continue
        rows.append({
            "ts": ts_iso,
            "open": float(b.get("open", 0)),
            "high": float(b.get("high", 0)),
            "low": float(b.get("low", 0)),
            "close": float(b.get("close", 0)),
            "volume": float(b.get("volume", 0) or 0),
        })

    rows.sort(key=lambda r: r["ts"])

    if around_ts:
        # Window mode — find closest match + return N before/after.
        target = pd.Timestamp(around_ts)
        # Compare against parsed timestamps.
        df = pd.DataFrame(rows)
        if df.empty:
            return []
        df["ts_parsed"] = pd.to_datetime(df["ts"])
        # Index of closest bar to target
        idx = (df["ts_parsed"] - target).abs().idxmin()
        lo = max(0, idx - n_before)
        hi = min(len(df), idx + n_after + 1)
        sliced = df.iloc[lo:hi].drop(columns=["ts_parsed"])
        return sliced.to_dict("records")

    if from_ts or to_ts:
        df = pd.DataFrame(rows)
        if df.empty:
            return []
        if from_ts:
            df = df[df["ts"] >= from_ts]
        if to_ts:
            df = df[df["ts"] <= to_ts]
        return df.to_dict("records")

    # Default — last 50.
    return rows[-50:]
