"""Load Oil candle data from CSV files."""
import pandas as pd
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR


def load_candles(filename: str) -> pd.DataFrame:
    """Load CSV with bid/ask or simple OHLC. Always produces mid_* columns."""
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
    elif "open" in df.columns:
        df["mid_open"] = df["open"]
        df["mid_high"] = df["high"]
        df["mid_low"] = df["low"]
        df["mid_close"] = df["close"]
        df["bid_open"] = df["open"]
        df["bid_high"] = df["high"]
        df["bid_low"] = df["low"]
        df["bid_close"] = df["close"]
        df["ask_open"] = df["open"]
        df["ask_high"] = df["high"]
        df["ask_low"] = df["low"]
        df["ask_close"] = df["close"]
        df["spread"] = 0.0

    return df
