from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd


@dataclass(frozen=True)
class MarketDataQuality:
    symbol: str
    rows: int
    start_timestamp: str
    end_timestamp: str
    duplicate_timestamps: int
    non_monotonic_timestamps: int
    expected_step_seconds: int
    off_step_gaps: int
    max_gap_minutes: float
    median_gap_minutes: float
    zero_or_negative_spread_rows: int
    median_spread_points: float
    p95_spread_points: float
    zero_volume_rows: int
    invalid_ohlc_rows: int
    quality_status: str
    quality_notes: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def analyze_m1_quality(frame: pd.DataFrame, *, symbol: str, expected_step_seconds: int = 60) -> MarketDataQuality:
    if frame.empty:
        return MarketDataQuality(
            symbol=symbol,
            rows=0,
            start_timestamp="",
            end_timestamp="",
            duplicate_timestamps=0,
            non_monotonic_timestamps=0,
            expected_step_seconds=expected_step_seconds,
            off_step_gaps=0,
            max_gap_minutes=0.0,
            median_gap_minutes=0.0,
            zero_or_negative_spread_rows=0,
            median_spread_points=0.0,
            p95_spread_points=0.0,
            zero_volume_rows=0,
            invalid_ohlc_rows=0,
            quality_status="FAIL_EMPTY",
            quality_notes="empty_frame",
        )

    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    timestamps = data["timestamp"]
    diffs = timestamps.sort_values().diff().dt.total_seconds().dropna()
    duplicate_timestamps = int(timestamps.duplicated().sum())
    non_monotonic = int((timestamps.diff().dt.total_seconds().dropna() < 0).sum())
    off_step = int((diffs != expected_step_seconds).sum())
    max_gap = float(diffs.max() / 60.0) if len(diffs) else 0.0
    median_gap = float(diffs.median() / 60.0) if len(diffs) else 0.0

    spread = pd.to_numeric(data.get("spread_points", pd.Series(dtype=float)), errors="coerce")
    volume = pd.to_numeric(data.get("volume", pd.Series(dtype=float)), errors="coerce")
    high = pd.to_numeric(data.get("high", pd.Series(dtype=float)), errors="coerce")
    low = pd.to_numeric(data.get("low", pd.Series(dtype=float)), errors="coerce")
    open_ = pd.to_numeric(data.get("open", pd.Series(dtype=float)), errors="coerce")
    close = pd.to_numeric(data.get("close", pd.Series(dtype=float)), errors="coerce")

    zero_spread = int((spread <= 0).sum())
    zero_volume = int((volume <= 0).sum())
    invalid_ohlc = int(((high < low) | (open_ > high) | (open_ < low) | (close > high) | (close < low)).sum())
    median_spread = float(spread.median()) if len(spread.dropna()) else 0.0
    p95_spread = float(spread.quantile(0.95)) if len(spread.dropna()) else 0.0

    notes = []
    if duplicate_timestamps:
        notes.append(f"duplicate_timestamps:{duplicate_timestamps}")
    if non_monotonic:
        notes.append(f"non_monotonic_timestamps:{non_monotonic}")
    if invalid_ohlc:
        notes.append(f"invalid_ohlc_rows:{invalid_ohlc}")
    if zero_spread:
        notes.append(f"zero_or_negative_spread_rows:{zero_spread}")
    if max_gap > 3 * expected_step_seconds / 60.0:
        notes.append(f"large_gap_minutes:{max_gap:.1f}")
    status = "PASS" if not any(key in ",".join(notes) for key in ["duplicate", "non_monotonic", "invalid_ohlc"]) else "CAUTION"

    return MarketDataQuality(
        symbol=symbol,
        rows=int(len(data)),
        start_timestamp=str(timestamps.min()),
        end_timestamp=str(timestamps.max()),
        duplicate_timestamps=duplicate_timestamps,
        non_monotonic_timestamps=non_monotonic,
        expected_step_seconds=expected_step_seconds,
        off_step_gaps=off_step,
        max_gap_minutes=max_gap,
        median_gap_minutes=median_gap,
        zero_or_negative_spread_rows=zero_spread,
        median_spread_points=median_spread,
        p95_spread_points=p95_spread,
        zero_volume_rows=zero_volume,
        invalid_ohlc_rows=invalid_ohlc,
        quality_status=status,
        quality_notes="ok" if not notes else ",".join(notes),
    )
