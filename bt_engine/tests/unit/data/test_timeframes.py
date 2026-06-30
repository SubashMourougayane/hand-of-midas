"""Unit tests for timeframe utilities."""
from __future__ import annotations

import pytest

from bt_engine.data.timeframes import (
    dwx_bars_filename,
    dwx_symbol_token,
    is_valid_timeframe,
    pandas_rule,
    seconds,
)


def test_is_valid_timeframe_accepts_m15() -> None:
    assert is_valid_timeframe("M15")


def test_is_valid_timeframe_rejects_bogus() -> None:
    assert not is_valid_timeframe("Q9")


def test_pandas_rule_m15() -> None:
    assert pandas_rule("M15") == "15min"


def test_pandas_rule_h1() -> None:
    assert pandas_rule("H1") == "1h"


def test_pandas_rule_raises_for_unknown() -> None:
    with pytest.raises(ValueError):
        pandas_rule("Q9")


def test_seconds_m15() -> None:
    assert seconds("M15") == 900


def test_seconds_d1() -> None:
    assert seconds("D1") == 86400


def test_dwx_symbol_token_dot_replacement() -> None:
    assert dwx_symbol_token("XAUUSD.ecn") == "XAUUSD_ecn"


def test_dwx_bars_filename() -> None:
    assert dwx_bars_filename("XAUUSD.ecn", "M15") == "bars_XAUUSD_ecn_M15.json"
