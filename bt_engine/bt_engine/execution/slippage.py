"""Slippage models. Default = zero for parity tests."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZeroSlippage:
    def bps(self) -> float:
        return 0.0


@dataclass(frozen=True)
class FixedBpsSlippage:
    value_bps: float

    def bps(self) -> float:
        return self.value_bps
