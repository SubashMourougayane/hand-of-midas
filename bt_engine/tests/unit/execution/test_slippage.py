"""Unit tests for slippage models."""
from __future__ import annotations

from bt_engine.execution.slippage import FixedBpsSlippage, ZeroSlippage


def test_zero_slippage() -> None:
    assert ZeroSlippage().bps() == 0.0


def test_fixed_slippage() -> None:
    assert FixedBpsSlippage(value_bps=5.0).bps() == 5.0
