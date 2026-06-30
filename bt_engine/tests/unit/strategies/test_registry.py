"""Unit tests for strategy registry."""
from __future__ import annotations

import pytest

from bt_engine.strategies import registry
from bt_engine.strategies.ema_cross.strategy import EmaCrossStrategy


def test_registry_lists_builtin_strategies() -> None:
    names = registry.list_strategies()
    assert "ema_cross" in names
    assert "sdr001" in names


def test_registry_returns_ema_cross_instance() -> None:
    s = registry.get("ema_cross")
    assert isinstance(s, EmaCrossStrategy)


def test_registry_unknown_strategy_raises() -> None:
    with pytest.raises(KeyError, match="Unknown strategy"):
        registry.get("xyz_not_real")


def test_registry_double_register_raises() -> None:
    def f():
        return None  # type: ignore
    with pytest.raises(ValueError):
        registry.register("ema_cross", f)  # type: ignore[arg-type]


def test_registry_sdr001_returns_real_strategy() -> None:
    from bt_engine.strategies.sdr001.strategy import SDR001Strategy

    s = registry.get("sdr001")
    assert isinstance(s, SDR001Strategy)
