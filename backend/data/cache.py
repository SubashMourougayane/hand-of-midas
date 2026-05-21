"""Load candle data from CSV files (same format as strategy-tester)."""
import pandas as pd
import os
from backend.config import DATA_DIR


def load_candles(filename: str) -> pd.DataFrame:
    """Load a CSV with bid/ask OHLC, compute mid prices, timestamp as DatetimeIndex."""
    path = os.path.join(DATA_DIR, filename) if not os.path.isabs(filename) else filename
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    if "bid_open" in df.columns and "ask_open" in df.columns:
        df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
        df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
        df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
        df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
        df["spread"] = df["ask_close"] - df["bid_close"]

    return df


def load_inter_market(instrument: str) -> pd.DataFrame:
    """Load daily inter-market data (mid prices only)."""
    filename = f"{instrument}_D.csv"
    path = os.path.join(DATA_DIR, filename)
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()
