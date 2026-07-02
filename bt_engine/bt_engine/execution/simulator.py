"""BTExecutionModel — simulates entry fill at next bar open with deterministic slippage.

No look-ahead: slip is a fixed function of (side, config). No forward-bar peek,
no random. Applied against `next_bar.open` which is the SAME bar-open the engine
already uses as the fill anchor.

Config knobs:
  - entry_slip_pips: extra $ per unit added to fill AGAINST the trade side
    (worse for the trader). Default 0.0 (ideal-fill BT). Realistic: 0.10-0.30
    for XAU (0.5-1.5 pip spread on JM Raw Spread).
  - slippage_bps_value: legacy % slippage; kept for back-compat.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bar import Bar
from ..core.order import Fill, Order


@dataclass(frozen=True)
class BTExecutionModel:
    slippage_bps_value: float = 0.0
    entry_slip_pips: float = 0.0  # abs $ price offset applied against trade side

    def slippage_bps(self) -> float:
        return self.slippage_bps_value

    def simulate_fill(self, order: Order, next_bar: Bar) -> Fill:
        if next_bar.timestamp != order.intended_entry_bar:
            raise ValueError(
                f"next_bar.timestamp {next_bar.timestamp} != order.intended_entry_bar "
                f"{order.intended_entry_bar}"
            )
        # Base: next bar open
        price = next_bar.open
        # Legacy bps slip (multiplicative)
        if self.slippage_bps_value != 0.0:
            price = price * (1.0 + order.side * self.slippage_bps_value / 10000.0)
        # New: fixed pip slip (additive, worse for trader)
        # side=+1 long: entry pushes UP (worse), side=-1 short: entry pushes DOWN (worse)
        if self.entry_slip_pips != 0.0:
            price = price + order.side * abs(self.entry_slip_pips)
        return Fill(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=price,
            fill_timestamp=next_bar.timestamp,
        )
