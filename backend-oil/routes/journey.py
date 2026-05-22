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
    context_before = 2
    context_after = bars_held + 3  # tight: just the trade duration + small buffer

    trade_date = pd.Timestamp(date, tz="UTC")
    idx = df.index.searchsorted(trade_date)
    if idx >= len(df):
        idx = len(df) - 1

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
