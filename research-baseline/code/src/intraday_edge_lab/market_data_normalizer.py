from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


MT_COLUMNS = ["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<VOL>", "<SPREAD>"]
CORE_COLUMNS = ["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<SPREAD>"]
BINANCE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]


@dataclass(frozen=True)
class NormalizedMarketDataMeta:
    source_path: str
    output_path: str
    source_format: str
    symbol: str
    timeframe: str
    raw_rows: int
    output_rows: int
    start_timestamp: str
    end_timestamp: str
    spread_source: str


def normalize_market_data(
    input_path: str | Path,
    output_path: str | Path,
    *,
    symbol: str,
    timeframe: str = "M1",
    source_format: str = "auto",
    spread_points: int = 0,
) -> NormalizedMarketDataMeta:
    """Convert common M1 data exports into the local MetaTrader-style contract."""
    source = Path(input_path)
    target = Path(output_path)
    detected = detect_format(source, source_format)
    raw = read_source(source, detected)
    normalized = normalize_frame(raw, detected, symbol=symbol, timeframe=timeframe, spread_points=spread_points)

    target.parent.mkdir(parents=True, exist_ok=True)
    normalized[MT_COLUMNS].to_csv(target, sep="\t", index=False)

    timestamps = pd.to_datetime(
        normalized["<DATE>"].astype(str) + " " + normalized["<TIME>"].astype(str),
        format="%Y.%m.%d %H:%M:%S",
        utc=True,
    )
    spread_source = "source_column" if "_source_spread" in normalized.attrs else f"default_{spread_points}"
    return NormalizedMarketDataMeta(
        source_path=str(source),
        output_path=str(target),
        source_format=detected,
        symbol=symbol,
        timeframe=timeframe,
        raw_rows=len(raw),
        output_rows=len(normalized),
        start_timestamp=str(timestamps.min()) if len(timestamps) else "",
        end_timestamp=str(timestamps.max()) if len(timestamps) else "",
        spread_source=spread_source,
    )


def detect_format(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    sample = path.read_text(encoding="utf-8", errors="ignore")[:4096]
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    upper = first_line.upper()
    if "<DATE>" in upper and "<TIME>" in upper:
        return "mt"
    if first_line.count(";") >= 5:
        return "histdata"
    if "OPEN_TIME" in upper or "CLOSE_TIME" in upper:
        return "binance"
    if first_line.count(",") >= 11:
        return "binance"
    return "generic"


def read_source(path: Path, source_format: str) -> pd.DataFrame:
    if source_format == "mt":
        return pd.read_csv(path, sep=None, engine="python")
    if source_format == "histdata":
        return pd.read_csv(path, sep=";", header=None)
    if source_format == "binance":
        first = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        has_header = any(char.isalpha() for char in first)
        return pd.read_csv(path, header=0 if has_header else None, names=None if has_header else BINANCE_COLUMNS)
    if source_format == "generic":
        return pd.read_csv(path, sep=None, engine="python")
    raise ValueError(f"Unsupported source_format: {source_format}")


def normalize_frame(
    raw: pd.DataFrame,
    source_format: str,
    *,
    symbol: str,
    timeframe: str,
    spread_points: int,
) -> pd.DataFrame:
    if source_format == "mt":
        frame = normalize_mt(raw, spread_points)
    elif source_format == "histdata":
        frame = normalize_histdata(raw, spread_points)
    elif source_format == "binance":
        frame = normalize_binance(raw, spread_points)
    elif source_format == "generic":
        frame = normalize_generic(raw, spread_points)
    else:
        raise ValueError(f"Unsupported source_format: {source_format}")

    for column in ["open", "high", "low", "close", "volume", "spread_points"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume", "spread_points"])
    frame = frame.sort_values("timestamp", kind="mergesort").drop_duplicates("timestamp", keep="last")
    frame = frame.reset_index(drop=True)

    out = pd.DataFrame(
        {
            "<DATE>": frame["timestamp"].dt.strftime("%Y.%m.%d"),
            "<TIME>": frame["timestamp"].dt.strftime("%H:%M:%S"),
            "<OPEN>": frame["open"],
            "<HIGH>": frame["high"],
            "<LOW>": frame["low"],
            "<CLOSE>": frame["close"],
            "<TICKVOL>": frame["volume"].round().astype("int64"),
            "<VOL>": 0,
            "<SPREAD>": frame["spread_points"].round().astype("int64"),
        }
    )
    if "source_spread_present" in frame.attrs:
        out.attrs["_source_spread"] = True
    return out


def normalize_mt(raw: pd.DataFrame, spread_points: int) -> pd.DataFrame:
    required = ["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"MT export missing required columns: {missing}")
    spread = raw["<SPREAD>"] if "<SPREAD>" in raw.columns else spread_points
    volume = raw["<TICKVOL>"] if "<TICKVOL>" in raw.columns else 0
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                raw["<DATE>"].astype(str) + " " + raw["<TIME>"].astype(str),
                format="%Y.%m.%d %H:%M:%S",
                errors="coerce",
                utc=True,
            ),
            "open": raw["<OPEN>"],
            "high": raw["<HIGH>"],
            "low": raw["<LOW>"],
            "close": raw["<CLOSE>"],
            "volume": volume,
            "spread_points": spread,
        }
    )
    if "<SPREAD>" in raw.columns:
        frame.attrs["source_spread_present"] = True
    return frame


def normalize_histdata(raw: pd.DataFrame, spread_points: int) -> pd.DataFrame:
    if len(raw.columns) == 6:
        raw = raw.copy()
        raw.columns = ["datetime", "open", "high", "low", "close", "volume"]
        timestamp = pd.to_datetime(raw["datetime"].astype(str), format="%Y%m%d %H%M%S", errors="coerce", utc=True)
    elif len(raw.columns) >= 7:
        raw = raw.copy()
        raw = raw.iloc[:, :7]
        raw.columns = ["date", "time", "open", "high", "low", "close", "volume"]
        timestamp = pd.to_datetime(
            raw["date"].astype(str) + " " + raw["time"].astype(str).str.zfill(6),
            format="%Y%m%d %H%M%S",
            errors="coerce",
            utc=True,
        )
    else:
        raise ValueError("HistData CSV needs either datetime+OHLCV or date+time+OHLCV columns.")
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
            "volume": raw["volume"] if "volume" in raw else 0,
            "spread_points": spread_points,
        }
    )


def normalize_binance(raw: pd.DataFrame, spread_points: int) -> pd.DataFrame:
    rename = {column: str(column).strip().lower() for column in raw.columns}
    data = raw.rename(columns=rename)
    if "open_time" not in data.columns and len(data.columns) >= 6:
        data = data.copy()
        data.columns = BINANCE_COLUMNS[: len(data.columns)]
    required = ["open_time", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Binance kline CSV missing required columns: {missing}")
    open_time = pd.to_numeric(data["open_time"], errors="coerce")
    unit = "ms" if open_time.dropna().median() > 10_000_000_000 else "s"
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(open_time, unit=unit, errors="coerce", utc=True),
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "volume": data["volume"],
            "spread_points": spread_points,
        }
    )


def normalize_generic(raw: pd.DataFrame, spread_points: int) -> pd.DataFrame:
    data = raw.rename(columns={column: str(column).strip().lower() for column in raw.columns})
    timestamp = find_timestamp(data)
    volume_column = first_existing(data, ["tickvol", "tick_volume", "volume", "vol"])
    spread_column = first_existing(data, ["spread", "spread_points"])
    required = ["open", "high", "low", "close"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Generic CSV missing OHLC columns: {missing}")
    frame = pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "volume": data[volume_column] if volume_column else 0,
            "spread_points": data[spread_column] if spread_column else spread_points,
        }
    )
    if spread_column:
        frame.attrs["source_spread_present"] = True
    return frame


def find_timestamp(data: pd.DataFrame) -> pd.Series:
    if "timestamp" in data.columns:
        return pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
    if "datetime" in data.columns:
        return pd.to_datetime(data["datetime"], utc=True, errors="coerce")
    date_column = first_existing(data, ["date", "<date>"])
    time_column = first_existing(data, ["time", "<time>"])
    if date_column and time_column:
        return pd.to_datetime(data[date_column].astype(str) + " " + data[time_column].astype(str), utc=True, errors="coerce")
    raise ValueError("Generic CSV needs timestamp/datetime or date+time columns.")


def first_existing(data: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in data.columns:
            return candidate
    return None
