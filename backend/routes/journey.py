"""Trade journey API — GET /api/gold/journey for trade candle data."""
from fastapi import APIRouter, Query
from backend.backtest.engine import _get_cached_data

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
    """
    Get candle data for a trade's journey (entry → exit).
    Returns OHLC points for proper visualization.
    """
    import pandas as pd

    data = _get_cached_data()

    if strategy == "alpha_sweep":
        df = data["gold_m3"]
        context_before = 2
        context_after = bars_held + 3
    else:
        df = data["gold_d"]
        context_before = 1
        context_after = bars_held + 2

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
            "open": round(mid_open, 2),
            "high": round(mid_high, 2),
            "low": round(mid_low, 2),
            "close": round(mid_close, 2),
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
        "timeframe": "M3" if strategy == "alpha_sweep" else "D",
    }
