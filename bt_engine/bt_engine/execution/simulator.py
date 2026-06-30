"""BTExecutionModel — simulates entry fill at next bar open with optional slippage."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bar import Bar
from ..core.order import Fill, Order


@dataclass(frozen=True)
class BTExecutionModel:
    slippage_bps_value: float = 0.0

    def slippage_bps(self) -> float:
        return self.slippage_bps_value

    def simulate_fill(self, order: Order, next_bar: Bar) -> Fill:
        if next_bar.timestamp != order.intended_entry_bar:
            raise ValueError(
                f"next_bar.timestamp {next_bar.timestamp} != order.intended_entry_bar "
                f"{order.intended_entry_bar}"
            )
        price = next_bar.open * (1.0 + order.side * self.slippage_bps_value / 10000.0)
        return Fill(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=price,
            fill_timestamp=next_bar.timestamp,
        )
