"""Forex multi-timeframe data gateway.

VibeTrader has H1 + M15 CSVs for 6 pairs (EUR/GBP/USD/JPY/AUD/CAD/XAU).
H4 and D1 are not stored; we resample H1.

Synthesises bid/ask from mid OHLC + spread column on M15 (the trading
timeframe — fill model needs bid_*/ask_*). H1/H4/D1 stay mid-only since
strategies signal off them, never fill.

Live-reproducibility:
- All timestamps coerced to naive UTC (drops timezone) for consistency
  with Labs conventions.
- Resample uses pandas right-closed/right-labelled = each H4 bar's
  timestamp marks bar END (matches M15 convention in production).

Symbol set:
    EUR_USD, GBP_USD, USD_JPY, AUD_USD, USD_CAD, XAU_USD

Dev/Validate windows mirror Labs sprint 2:
    DEV   = 2019-09-26 → 2023-12-31
    VAL   = 2024-01-01 → 2024-12-31
    HOLD  = 2025-01-01 → present (sealed)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pandas as pd

_VIBETRADER_ROOT = Path("/Users/subash/SUBASH/VibeTrader")
_DATA_DIR = _VIBETRADER_ROOT / "data"


class ForexPhase(Enum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


_PHASE_BOUNDS = {
    ForexPhase.DEVELOPMENT: (pd.Timestamp("2019-09-26"), pd.Timestamp("2023-12-31 23:59:59")),
    ForexPhase.VALIDATION:  (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31 23:59:59")),
    ForexPhase.HOLDOUT:     (pd.Timestamp("2025-01-01"), pd.Timestamp("2099-12-31")),
}

_SYMBOL_TO_FILES = {
    "EUR_USD": ("forex_eur_usd_h1_full_history.csv", "forex_eur_usd_m15_full_history.csv"),
    "GBP_USD": ("forex_gbp_usd_h1_full_history.csv", "forex_gbp_usd_m15_full_history.csv"),
    "USD_JPY": ("forex_usd_jpy_h1_full_history.csv", "forex_usd_jpy_m15_full_history.csv"),
    "AUD_USD": ("forex_aud_usd_h1_full_history.csv", "forex_aud_usd_m15_full_history.csv"),
    "USD_CAD": ("forex_usd_cad_h1_full_history.csv", "forex_usd_cad_m15_full_history.csv"),
    "XAU_USD": ("xauusd_h1_full_history.csv",        "forex_xau_usd_m15_full_history.csv"),
}


@dataclass(frozen=True)
class ForexBundle:
    """Four timeframes for one symbol, all naive UTC."""
    symbol: str
    d1: pd.DataFrame   # daily — mid OHLC
    h4: pd.DataFrame   # 4h    — mid OHLC
    h1: pd.DataFrame   # 1h    — mid OHLC
    m15: pd.DataFrame  # 15m   — bid_* / ask_* / mid_* for fill model


def _strip_tz(ts_index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if ts_index.tz is not None:
        return ts_index.tz_convert("UTC").tz_localize(None)
    return ts_index


def _load_h1_mid(symbol: str) -> pd.DataFrame:
    h1_file, _ = _SYMBOL_TO_FILES[symbol]
    df = pd.read_csv(_DATA_DIR / h1_file, parse_dates=["timestamp"])
    df.index = _strip_tz(pd.DatetimeIndex(df["timestamp"]))
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.columns = ["mid_open", "mid_high", "mid_low", "mid_close", "volume"]
    return df.sort_index()


def _load_m15(symbol: str) -> pd.DataFrame:
    """Load M15 with bid/ask synthesised from mid ± spread/2."""
    _, m15_file = _SYMBOL_TO_FILES[symbol]
    df = pd.read_csv(_DATA_DIR / m15_file, parse_dates=["timestamp"])
    df.index = _strip_tz(pd.DatetimeIndex(df["timestamp"]))
    df = df.sort_index()
    spread = df["spread"].fillna(0.0).clip(lower=0.0)
    half = spread / 2.0
    out = pd.DataFrame(index=df.index)
    out["mid_open"]  = df["open"]
    out["mid_high"]  = df["high"]
    out["mid_low"]   = df["low"]
    out["mid_close"] = df["close"]
    out["bid_open"]  = df["open"]  - half
    out["bid_high"]  = df["high"]  - half
    out["bid_low"]   = df["low"]   - half
    out["bid_close"] = df["close"] - half
    out["ask_open"]  = df["open"]  + half
    out["ask_high"]  = df["high"]  + half
    out["ask_low"]   = df["low"]   + half
    out["ask_close"] = df["close"] + half
    out["volume"]    = df["volume"]
    return out


def _resample(h1_mid: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate H1 mid OHLC up to H4 or D1.

    pandas resample default is left-closed/left-labelled. We use that:
    the bar timestamp = bar START. Strategies that need bar-end semantics
    convert via `+ offset`.

    H4 alignment: hours [00, 04, 08, 12, 16, 20] UTC. This matches
    JustMarkets / OANDA H4 dailyAlignment=0 convention; bearishharry's
    "4h" ostensibly means the same.
    """
    out = h1_mid.resample(rule, label="left", closed="left").agg({
        "mid_open":  "first",
        "mid_high":  "max",
        "mid_low":   "min",
        "mid_close": "last",
        "volume":    "sum",
    }).dropna(subset=["mid_open"])
    return out


def _load_brent_via_rnd_gateway() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load Brent BCO_USD D1+H1+M3 from R&D's sealed gateway, then resample
    M3 → M15. Brent CSVs already have bid_*/ask_*/mid_* columns so M15 is
    fill-model ready out of the box.
    """
    import sys as _sys
    _rnd = Path(__file__).resolve().parent.parent.parent / "R&D"
    if str(_rnd) not in _sys.path:
        _sys.path.insert(0, str(_rnd))
    from data_split import Phase as _Phase, get_data as _get_data  # type: ignore

    d1, h1, m3 = _get_data(_Phase.DEVELOPMENT, "BCO_USD")
    # All three have tz-aware index from R&D gateway; strip to naive UTC
    for df in (d1, h1, m3):
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

    # Make d1/h1 mid-only column-style consistent with forex side
    h1_mid = h1[["mid_open", "mid_high", "mid_low", "mid_close", "volume"]].copy()
    d1_mid = d1[["mid_open", "mid_high", "mid_low", "mid_close", "volume"]].copy()

    # Resample M3 → M15 (5 M3 bars per M15)
    agg = {
        "bid_open":"first","bid_high":"max","bid_low":"min","bid_close":"last",
        "ask_open":"first","ask_high":"max","ask_low":"min","ask_close":"last",
        "mid_open":"first","mid_high":"max","mid_low":"min","mid_close":"last",
        "volume":"sum",
    }
    m15 = m3.resample("15min", label="left", closed="left").agg(agg).dropna(subset=["mid_open"])
    return d1_mid, h1_mid, m15


def get_forex(symbol: str, phase: ForexPhase = ForexPhase.DEVELOPMENT) -> ForexBundle:
    """Load + slice one symbol's D1/H4/H1/M15 for the requested phase."""
    if symbol == "BCO_USD":
        # Brent oil: load via R&D gateway, resample M3→M15
        start, end = _PHASE_BOUNDS[phase]
        d1_mid, h1_mid, m15 = _load_brent_via_rnd_gateway()
        h4 = _resample(h1_mid, "4h")
        # Replace daily resample if the loaded D1 doesn't cover; but R&D already
        # gives us the canonical D1 — use it directly
        return ForexBundle(
            symbol="BCO_USD",
            d1=d1_mid.loc[start:end],
            h4=h4.loc[start:end],
            h1=h1_mid.loc[start:end],
            m15=m15.loc[start:end],
        )

    if symbol not in _SYMBOL_TO_FILES:
        raise KeyError(f"unknown symbol {symbol!r}; valid: {list(_SYMBOL_TO_FILES) + ['BCO_USD']}")

    start, end = _PHASE_BOUNDS[phase]

    h1_mid = _load_h1_mid(symbol)
    m15    = _load_m15(symbol)

    h4 = _resample(h1_mid, "4h")
    d1 = _resample(h1_mid, "1D")

    # Slice to phase window
    h1_mid = h1_mid.loc[start:end]
    h4     = h4.loc[start:end]
    d1     = d1.loc[start:end]
    m15    = m15.loc[start:end]

    return ForexBundle(symbol=symbol, d1=d1, h4=h4, h1=h1_mid, m15=m15)


SYMBOLS = list(_SYMBOL_TO_FILES.keys()) + ["BCO_USD"]


def _self_test() -> None:
    """Sanity-check shapes + tz across pairs. Run via:
        python -m Labs.shared.data_forex
    """
    for sym in SYMBOLS:
        b = get_forex(sym)
        assert b.d1.index.tz is None
        assert b.h4.index.tz is None
        assert b.h1.index.tz is None
        assert b.m15.index.tz is None
        # Sanity: dev window is 4 years 3 months. Expect:
        # - D1 ≈ 1100 bars (weekdays only)
        # - H4 ≈ 6500 bars
        # - H1 ≈ 26000 bars
        # - M15 ≈ 100000 bars
        # Forex doesn't trade weekends; allow loose bounds.
        assert len(b.d1)  > 800,   f"{sym} D1  too short: {len(b.d1)}"
        assert len(b.h4)  > 4000,  f"{sym} H4  too short: {len(b.h4)}"
        assert len(b.h1)  > 20000, f"{sym} H1  too short: {len(b.h1)}"
        assert len(b.m15) > 80000, f"{sym} M15 too short: {len(b.m15)}"
        # M15 must have bid/ask
        assert "bid_high" in b.m15.columns
        assert "ask_low" in b.m15.columns
        print(f"  ✓ {sym}: D1={len(b.d1)} H4={len(b.h4)} H1={len(b.h1)} M15={len(b.m15):,}")
        print(f"      first M15: {b.m15.index[0]}  last M15: {b.m15.index[-1]}")
    print()
    print("data_forex self-test pass.")


if __name__ == "__main__":
    _self_test()
