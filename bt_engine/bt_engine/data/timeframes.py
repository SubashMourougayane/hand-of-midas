"""Timeframe identifiers + DWX name mapping + pandas resample rules."""
from __future__ import annotations

from typing import Final


TIMEFRAMES: Final[tuple[str, ...]] = ("M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1")

# pandas resample rules (offset aliases)
PANDAS_RULE: Final[dict[str, str]] = {
    "M1": "1min",
    "M3": "3min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
}

# seconds per timeframe
SECONDS: Final[dict[str, int]] = {
    "M1": 60,
    "M3": 180,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

# DWX EA writes filenames like bars_<symbol>_<tf>.json where symbol has '.' replaced with '_'
DWX_TF_NAME: Final[dict[str, str]] = {
    "M1": "M1",
    "M3": "M3",
    "M5": "M5",
    "M15": "M15",
    "M30": "M30",
    "H1": "H1",
    "H4": "H4",
    "D1": "D1",
}


def is_valid_timeframe(tf: str) -> bool:
    return tf in TIMEFRAMES


def pandas_rule(tf: str) -> str:
    if tf not in PANDAS_RULE:
        raise ValueError(f"Unknown timeframe: {tf}")
    return PANDAS_RULE[tf]


def seconds(tf: str) -> int:
    if tf not in SECONDS:
        raise ValueError(f"Unknown timeframe: {tf}")
    return SECONDS[tf]


def dwx_symbol_token(symbol: str) -> str:
    return symbol.replace(".", "_")


def dwx_bars_filename(symbol: str, tf: str) -> str:
    return f"bars_{dwx_symbol_token(symbol)}_{DWX_TF_NAME[tf]}.json"
