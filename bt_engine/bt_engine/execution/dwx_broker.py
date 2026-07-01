"""DWXBrokerAdapter — submits orders to MT5 via DWX file bridge.

EA command protocol (pipe-separated, .txt in commands/):
    OPEN|SYMBOL|TYPE|VOLUME|PRICE|SL|TP|COMMENT
    MODIFY|TICKET|SL|TP
    CLOSE|TICKET
    CLOSE_ALL|

PRICE is ignored by the EA (uses live bid/ask). Volume is in lots.
"""
from __future__ import annotations

from typing import Iterator, Sequence

import pandas as pd

from ..core.order import Fill, Order
from ..data.dwx_bridge import DwxBridge


class DWXBrokerAdapter:
    """Live broker adapter over the DWX file bridge."""

    def __init__(self, bridge: DwxBridge, *, default_timeout_s: float = 5.0) -> None:
        self.bridge = bridge
        self.default_timeout_s = default_timeout_s
        self._last_ticket: str | None = None
        self._last_response: dict | None = None
        self._last_order: Order | None = None

    def submit_order(self, order: Order) -> str:
        """Submit a market OPEN command. Returns the ticket id (str) or raises."""
        self._last_order = order
        side_str = "BUY" if order.side > 0 else "SELL"
        tp = order.take_profit if order.take_profit is not None else 0.0
        # PRICE field is informational only; EA uses live bid/ask
        cmd = (
            f"OPEN|{order.symbol}|{side_str}|{order.qty}|0.0|"
            f"{order.stop_price}|{tp}|{order.tag}"
        )
        resp = self.bridge.send_command(cmd, wait_response=True, timeout_s=self.default_timeout_s)
        self._last_response = resp or {}
        if not resp or not resp.get("success"):
            raise RuntimeError(f"Order submit failed: {resp}")
        ticket = str(resp.get("ticket"))
        self._last_ticket = ticket
        return ticket

    def cancel(self, order_id: str) -> None:
        cmd = f"CLOSE|{order_id}"
        resp = self.bridge.send_command(cmd, wait_response=True, timeout_s=self.default_timeout_s)
        if not resp or not resp.get("success"):
            raise RuntimeError(f"Order cancel failed: {resp}")

    def modify(self, ticket: str, *, sl: float, tp: float = 0.0) -> None:
        cmd = f"MODIFY|{ticket}|{sl}|{tp}"
        resp = self.bridge.send_command(cmd, wait_response=True, timeout_s=self.default_timeout_s)
        if not resp or not resp.get("success"):
            raise RuntimeError(f"Order modify failed: {resp}")

    def close_partial(self, ticket: str, qty: float) -> None:
        """Close `qty` lots of position `ticket`. EA reduces remaining position."""
        cmd = f"CLOSE_PARTIAL|{ticket}|{qty}"
        resp = self.bridge.send_command(cmd, wait_response=True, timeout_s=self.default_timeout_s)
        if not resp or not resp.get("success"):
            raise RuntimeError(f"Order close_partial failed: {resp}")

    def close_all(self) -> None:
        resp = self.bridge.send_command("CLOSE_ALL|", wait_response=True, timeout_s=self.default_timeout_s)
        if not resp or not resp.get("success"):
            raise RuntimeError(f"Close-all failed: {resp}")

    def last_response(self) -> dict | None:
        return self._last_response

    def fills(self) -> Iterator[Fill]:
        """Yield the latest fill from the last OPEN response, if any."""
        resp = self._last_response or {}
        if not resp.get("success"):
            return
        order = self._last_order
        if order is None:
            return
        price = float(resp.get("price", 0.0))
        ticket = str(resp.get("ticket"))
        if not ticket or price == 0.0:
            return
        # synthesise a Fill (broker writes ticket+price+volume into last_response)
        # ts not available from EA response — use current UTC
        from datetime import datetime, timezone
        yield Fill(
            symbol=order.symbol,
            side=order.side,
            qty=float(resp.get("volume", order.qty) or order.qty),
            price=price,
            fill_timestamp=pd.Timestamp(datetime.now(timezone.utc)),
        )

    def positions(self) -> Sequence[dict]:
        """Snapshot of open positions from open_orders.json."""
        orders = self.bridge.open_orders()
        if not isinstance(orders, dict):
            return []
        return list(orders.values())
