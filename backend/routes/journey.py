"""Trade journey API — GET /api/gold/journey for trade candle data."""
from fastapi import APIRouter, Query
from backend.db import execute
from backend.backtest.engine import _get_cached_data

router = APIRouter()


@router.get("/journey")
def get_trade_journey(
    date: str = Query(...),
    strategy: str = Query(...),
    entry: float = Query(...),
    sl: float = Query(...),
    tp: float = Query(0),
    bars_held: int = Query(10),
):
    """
    Get candle data for a trade's journey (entry → exit).
    Returns price points around the trade window for charting.
    """
    import pandas as pd

    data = _get_cached_data()

    # Determine timeframe from strategy
    if strategy == "alpha_sweep":
        df = data["gold_m3"]
        context_before = 5  # fewer bars before for M3 (tight window)
        context_after = max(bars_held + 10, 30)
    else:
        df = data["gold_d"]
        context_before = 2  # minimal context — chart starts near entry
        context_after = max(bars_held + 3, 8)

    # Find the entry bar
    trade_date = pd.Timestamp(date, tz="UTC")

    # Find closest bar to trade date
    idx = df.index.searchsorted(trade_date)
    if idx >= len(df):
        idx = len(df) - 1

    # Get window
    start_idx = max(0, idx - context_before)
    end_idx = min(len(df), idx + context_after)

    window = df.iloc[start_idx:end_idx]

    # Build price points
    points = []
    for i, (ts, row) in enumerate(window.iterrows()):
        mid = (row["bid_close"] + row["ask_close"]) / 2 if "ask_close" in row else row.get("mid_close", row.get("bid_close", 0))
        mid_high = (row["bid_high"] + row["ask_high"]) / 2 if "ask_high" in row else row.get("mid_high", mid)
        mid_low = (row["bid_low"] + row["ask_low"]) / 2 if "ask_low" in row else row.get("mid_low", mid)

        points.append({
            "time": ts.isoformat(),
            "price": round(mid, 2),
            "high": round(mid_high, 2),
            "low": round(mid_low, 2),
        })

    return {
        "points": points,
        "entry": entry,
        "sl": sl,
        "tp": tp if tp > 0 else None,
        "strategy": strategy,
        "bars_held": bars_held,
        "entry_bar_index": context_before,
        "timeframe": "M3" if strategy == "alpha_sweep" else "D",
    }
