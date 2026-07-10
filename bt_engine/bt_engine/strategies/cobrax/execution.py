"""CobraxLimitExecution — BT fill model for COBRAX's resting-limit entries.

COBRAX enters on a LIMIT at the FVG edge, filled when a bar retraces into it. The
default BTExecutionModel fills at next_bar.open (market-on-open) — wrong for a limit.
This model fills at the limit price carried in `order.extra["limit_price"]` (the elvl
the strategy detected the touch against), matching research `entry_px = elvl`.

Causal: limit_price is set from the FVG (formed on a CLOSED bar strictly before the
fill bar); no forward peek. Optional entry_slip_pips worsens the fill (live realism).

LIVE CAVEAT: the DWX bridge submits MARKET orders, so a live COBRAX leg fills at the
touch-bar market price, not a true resting limit at elvl. That BT↔live gap is measured
by the Phase-2 parity check; a true limit needs EA limit-order support.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...core.bar import Bar
from ...core.order import Fill, Order


@dataclass(frozen=True)
class CobraxLimitExecution:
    entry_slip_pips: float = 0.0

    def slippage_bps(self) -> float:
        return 0.0

    def simulate_fill(self, order: Order, next_bar: Bar) -> Fill:
        if next_bar.timestamp != order.intended_entry_bar:
            raise ValueError(
                f"next_bar.timestamp {next_bar.timestamp} != order.intended_entry_bar "
                f"{order.intended_entry_bar}"
            )
        px = float((order.extra or {}).get("limit_price", next_bar.open))
        if self.entry_slip_pips:
            px = px + order.side * abs(self.entry_slip_pips)
        return Fill(
            symbol=order.symbol, side=order.side, qty=order.qty,
            price=px, fill_timestamp=next_bar.timestamp,
        )
