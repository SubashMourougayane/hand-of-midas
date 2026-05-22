"""Oil trade journey API — GET /api/oil/journey."""
from fastapi import APIRouter, Query
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.engine import _get_cached_data

router = APIRouter()


@router.get("/journey")
def get_trade_journey(
    date: str = Query(...),
    strategy: str = Query(...),
    direction: str = Query("long"),
    entry: float = Query(...),
    sl: float = Query(...),
    tp: float = Query(0),
    bars_held: int = Query(10),
):
    """Get Oil candle data for a trade's journey."""
    data = _get_cached_data()
    df = data["oil_m3"]
    context_before = 3
    context_after = max(bars_held + 5, 20)

    trade_date = pd.Timestamp(date, tz="UTC")
    idx = df.index.searchsorted(trade_date)
    if idx >= len(df):
        idx = len(df) - 1

    # Find the bar closest to entry PRICE on that day (date alone lands at midnight)
    day_start = idx
    day_end = min(idx + 200, len(df))
    best_idx = idx
    best_diff = float("inf")
    for i in range(day_start, day_end):
        mid = (df["bid_close"].iat[i] + df["ask_close"].iat[i]) / 2
        diff = abs(mid - entry)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
        if diff > best_diff * 3 and best_diff < 0.5:
            break
    idx = best_idx

    start_idx = max(0, idx - context_before)
    end_idx = min(len(df), idx + context_after)
    window = df.iloc[start_idx:end_idx]

    points = []
    for ts, row in window.iterrows():
        mid_open = (row["bid_open"] + row["ask_open"]) / 2
        mid_high = (row["bid_high"] + row["ask_high"]) / 2
        mid_low = (row["bid_low"] + row["ask_low"]) / 2
        mid_close = (row["bid_close"] + row["ask_close"]) / 2
        points.append({
            "time": ts.isoformat(),
            "open": round(mid_open, 4),
            "high": round(mid_high, 4),
            "low": round(mid_low, 4),
            "close": round(mid_close, 4),
        })

    return {
        "points": points,
        "entry": entry,
        "sl": sl,
        "tp": tp if tp > 0 else None,
        "direction": direction,
        "strategy": strategy,
        "bars_held": bars_held,
        "entry_bar_index": context_before,
        "timeframe": "M3",
    }
