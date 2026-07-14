"""FakeBridge + SimBrokerAdapter — drive the REAL live broker path in a backtest.

Single-source principle: the live process talks to MT5 through
`execution/dwx_broker.DWXBrokerAdapter`, which itself talks only through a
`DwxBridge` (send_command + open_orders/closed_orders/account_info JSON).

To run the EXACT live code path over historical bars we therefore:
  - keep the REAL `DWXBrokerAdapter` (submit/fills/positions/close_partial logic
    is live code, unchanged), and
  - swap the real `DwxBridge` for `FakeBridge`, which interprets the pipe
    commands the EA would execute and fills/realizes P&L from the current bar.

`FakeBridge` is PHYSICAL by construction: a CLOSE_PARTIAL realizes only the
closed fraction's $ into the running balance, the final CLOSE realizes the
remainder. So `account_info()["balance"]` is the in-BT stand-in for the real
MT5 realized balance — the honest arbiter for the partial-TP $ question.

No look-ahead: every fill/realize uses ONLY the current bar (open for entries,
close for exits) that the engine has already yielded. `set_current_bar` is
called by the engine (core/engine.py `_submit_live_order`) before each submit,
and by the session loop before each bar's walk.
"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..core.bar import Bar
from ..execution.dwx_broker import DWXBrokerAdapter

# XAU contract size (oz per lot). Matches equity_sizer.CONTRACT_SIZE default.
_CONTRACT = {"XAUUSD.ecn": 100.0}
_CLOSED_BUFFER = 60  # mirror the real EA's ~57-deal rolling closed_orders buffer


class FakeBridge:
    """Emulates the DwxBridge surface, backed by historical bars.

    State it maintains (all physical / realized-only):
      balance      running realized balance ($)
      positions    {ticket: {symbol,type,volume,open_price,SL,TP,open_time}}
      closed       rolling list of realized deal dicts (reconciler shape)
    """

    def __init__(self, *, start_balance: float = 5000.0, symbol: str = "XAUUSD.ecn",
                 spread_est: float | None = None) -> None:
        self.balance = float(start_balance)
        self.symbol = symbol
        # Round-trip spread cost in $/unit, charged on close so `balance` is NET of
        # trading cost — a true MT5-realized stand-in (real fills cross bid/ask).
        # Matches the strategy's cost_r ($/unit / risk_units). Default from the
        # per-symbol cost table (XAU = $0.30/oz round trip).
        if spread_est is None:
            try:
                from bt_engine.strategies.fib_v2.config import COST_PER_LOT_DEFAULTS
                spread_est = COST_PER_LOT_DEFAULTS.get(symbol, {}).get("spread_est", 0.30)
            except Exception:
                spread_est = 0.30
        self._spread_est = float(spread_est)
        self.positions: dict[str, dict[str, Any]] = {}
        self.closed: list[dict[str, Any]] = []
        self._seq = 0
        self._bar: Bar | None = None
        self._last_response: dict[str, Any] = {}

    # ---- engine/session wiring ----
    def set_current_bar(self, bar: Bar) -> None:
        self._bar = bar

    def _contract(self) -> float:
        return _CONTRACT.get(self.symbol, 100.0)

    def _deal_pnl(self, side: int, open_price: float, close_price: float, volume: float) -> float:
        return side * (close_price - open_price) * volume * self._contract()

    def _record_close(self, ticket: str, pos: dict, close_price: float, volume: float) -> None:
        side = 1 if pos["type"] == "BUY" else -1
        gross = self._deal_pnl(side, pos["open_price"], close_price, volume)
        cost = self._spread_est * volume * self._contract()  # round-trip spread on this fill
        profit = gross - cost
        self.balance += profit
        self.closed.append({
            "ticket": ticket,
            "symbol": pos["symbol"],
            "type": pos["type"],
            "volume": float(volume),
            "open_price": pos["open_price"],
            "open_time": pos["open_time"],
            "close_price": float(close_price),
            "close_time": self._ts_str(),
            "profit": float(profit),
            "swap": 0.0,
            "commission": 0.0,
            "magic": 0,
            "comment": pos.get("comment", ""),
            "deal_reason": "sim",
        })
        if len(self.closed) > _CLOSED_BUFFER:
            self.closed = self.closed[-_CLOSED_BUFFER:]

    def _ts_str(self) -> str:
        ts = self._bar.timestamp if self._bar is not None else pd.Timestamp(datetime.now(timezone.utc))
        return pd.Timestamp(ts).strftime("%Y.%m.%d %H:%M:%S")

    # ---- DwxBridge surface ----
    def is_alive(self, max_age_s: float = 10.0) -> bool:
        return True

    def mtime(self, name: str) -> float:
        # Every "file" is always fresh in BT — the reconciler's freshness guard
        # (`_closed_orders_is_fresh`) trusts closed_orders immediately, so it
        # matches on the first attempt (no async retry/backoff sleeps).
        return time.time()

    def account_info(self) -> dict[str, Any]:
        floating = 0.0
        if self._bar is not None:
            px = self._bar.close
            for pos in self.positions.values():
                side = 1 if pos["type"] == "BUY" else -1
                floating += self._deal_pnl(side, pos["open_price"], px, pos["volume"])
        return {"balance": self.balance, "equity": self.balance + floating,
                "currency": "USD", "leverage": 100}

    def market_data(self) -> dict[str, Any]:
        # Tight synthetic quote so LiveSafetyBroker._safe_order's spread gate
        # passes in BT (real cost is modeled separately via cost_r on the trade).
        px = float(self._bar.close) if self._bar is not None else 0.0
        return {self.symbol: {"bid": px, "ask": px, "spread": 0.01, "time": self._ts_str()}}

    def open_orders(self) -> dict[str, Any]:
        # DWX open_orders.json is keyed by ticket, each value a dict WITHOUT a
        # nested ticket field (the adapter injects it). Match that shape.
        return {tk: {k: v for k, v in pos.items()} for tk, pos in self.positions.items()}

    def closed_orders(self) -> list[dict[str, Any]]:
        return list(self.closed)

    def last_response(self) -> dict[str, Any]:
        return dict(self._last_response)

    def send_command(self, command: str, *, wait_response: bool = True,
                     timeout_s: float = 5.0) -> dict[str, Any] | None:
        parts = command.split("|")
        op = parts[0]
        bar = self._bar
        if op == "OPEN":
            # OPEN|SYMBOL|TYPE|VOLUME|PRICE|SL|TP|COMMENT
            _, sym, side_str, vol, _price, sl, tp, *rest = parts
            comment = rest[0] if rest else ""
            fill_px = float(bar.open) if bar is not None else 0.0
            self._seq += 1
            ticket = str(self._seq)
            self.positions[ticket] = {
                "symbol": sym, "type": side_str, "volume": float(vol),
                "open_price": fill_px, "SL": float(sl), "TP": float(tp),
                "open_time": self._ts_str(), "comment": comment,
            }
            self._last_response = {"success": True, "ticket": ticket,
                                   "price": fill_px, "volume": float(vol)}
        elif op == "MODIFY":
            _, ticket, sl, tp = parts[:4]
            if ticket in self.positions:
                self.positions[ticket]["SL"] = float(sl)
                if float(tp) != 0.0:
                    self.positions[ticket]["TP"] = float(tp)
            self._last_response = {"success": ticket in self.positions, "ticket": ticket}
        elif op == "CLOSE_PARTIAL":
            _, ticket, qty = parts[:3]
            qty = float(qty)
            pos = self.positions.get(ticket)
            if pos is not None:
                close_px = float(bar.close) if bar is not None else pos["open_price"]
                qty = min(qty, pos["volume"])
                self._record_close(ticket, pos, close_px, qty)
                pos["volume"] -= qty
                if pos["volume"] <= 1e-9:
                    del self.positions[ticket]
                self._last_response = {"success": True, "ticket": ticket, "volume": qty}
            else:
                self._last_response = {"success": False, "ticket": ticket}
        elif op in ("CLOSE", "CLOSE_PARTIAL_ALL"):
            _, ticket = parts[:2]
            pos = self.positions.pop(ticket, None)
            if pos is not None:
                close_px = float(bar.close) if bar is not None else pos["open_price"]
                self._record_close(ticket, pos, close_px, pos["volume"])
                self._last_response = {"success": True, "ticket": ticket}
            else:
                self._last_response = {"success": False, "ticket": ticket}
        elif op == "CLOSE_ALL":
            close_px = float(bar.close) if bar is not None else 0.0
            for ticket, pos in list(self.positions.items()):
                self._record_close(ticket, pos, close_px, pos["volume"])
                del self.positions[ticket]
            self._last_response = {"success": True}
        else:
            self._last_response = {"success": False, "error": f"unknown command {op}"}
        return dict(self._last_response)


class SimBrokerAdapter(DWXBrokerAdapter):
    """Real DWXBrokerAdapter over a FakeBridge, plus the engine's bar hook.

    The engine calls `set_current_bar(bar)` on the broker before each submit
    (core/engine.py `_submit_live_order`). The real adapter has no such method,
    so we add it here and forward to the bridge. Everything else — submit_order,
    fills, positions, modify, close_partial — is inherited UNCHANGED (live code).
    """

    def set_current_bar(self, bar: Bar) -> None:
        if isinstance(self.bridge, FakeBridge):
            self.bridge.set_current_bar(bar)

    def fills(self):
        """Same as the live adapter, but stamp the fill with the BAR timestamp
        (historical) rather than `datetime.now()`. The parent DWXBrokerAdapter
        uses now() because a live fill really happens ~now; in BT the fill
        happens at the bar being replayed, so entry_timestamp must be the bar's
        time (else every trade persists as 'today' and per-year/equity-curve
        analysis breaks)."""
        bar = getattr(self.bridge, "_bar", None)
        for f in super().fills():
            yield replace(f, fill_timestamp=bar.timestamp) if bar is not None else f
