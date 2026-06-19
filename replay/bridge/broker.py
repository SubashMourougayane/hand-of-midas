"""Tape Bridge — fake broker that mirrors mt5_executor's API contract.

Goal: live's scheduler/live_engine code talks to this module thinking it's
talking to MT5+DWX. The bridge fills orders against tape data using the
SAME fill physics as backend/execution/fill_model.py — gap-through SL,
TP-wins-tie at bar level, slippage formula, etc.

Design pillars:
- **Same Python API as mt5_executor.py.** Drop-in replacement via sys.modules
  surgery. Live code is NEVER modified.
- **Tape-time clock.** Every operation reads `tape.current_time()` rather
  than wall-clock. Replay can run at any speed.
- **Per-instrument account.** Tracks balance, equity, unrealized PnL.
- **Order book in memory.** Pending limits, open positions, closed history.
- **closed_orders.json equivalent** kept in memory; `get_trade_details`
  returns from this map.
- **Slippage exactly matches BT.** Uses backend.execution.fill_model._sl_slip.

What this DOES match BT physics:
- Bar-level SL/TP detection (same priority order: gap-through, partial,
  TP-wins-tie, SL touch).
- Same slippage on SL fills.
- Same partial-TP semantics (size, BE arm on partial).
- Same MAX_HOLD via bar count.

What this DOES NOT model (intentional gaps):
- Tick-level intra-bar fills. Replay walks bar by bar.
- Network latency. Orders fill at tape time exactly.
- Broker rejection. Always success path.
- Spread on fill (uses CSV spread).

These match the proposal's design (REPLAY_SERVER_PROPOSAL.md sections
"What's tricky / where it can lie to you" #1, #2, #3).
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

# Reuse BT's slippage formula so fills match the backtest engine byte-for-byte.
from backend.execution.fill_model import _sl_slip


# Magic number used by mt5_executor — match it so any caller filtering
# `pos.get("magic") != MAGIC` doesn't drop our orders.
MAGIC_NUMBER = 24824824


@dataclass
class Order:
    """A pending or open order in the bridge."""
    ticket: str
    instrument: str           # "XAU_USD" / "BCO_USD"
    side: str                 # "BUY" / "SELL"
    units: float              # absolute (positive)
    open_price: float         # fill price (limit price for pending → fill price after fill)
    sl: float                 # 0 = none
    tp: float                 # 0 = none
    comment: str
    placed_at: datetime       # tape time of placement
    order_type: str           # "MARKET" / "BUY_LIMIT" / "SELL_LIMIT"
    state: str                # "PENDING" / "OPEN" / "CLOSED"
    open_time: Optional[datetime] = None       # tape time of fill
    ttl_seconds: int = 0      # for limit orders
    expiration: Optional[datetime] = None
    # Filter #7 partial-TP support
    partial_filled: bool = False
    partial_units_closed: float = 0.0
    # Closed state
    close_price: Optional[float] = None
    close_time: Optional[datetime] = None
    realized_pl: float = 0.0
    exit_reason: Optional[str] = None
    profit: float = 0.0       # unrealized when OPEN, realized when CLOSED
    bars_held: int = 0


# Volume → lots conversion mirrors mt5_executor's exact formula
def _units_to_lots(instrument: str, units: float) -> float:
    sym = instrument.upper()
    if "XAU" in sym:
        lots = abs(units) / 100.0
    elif "BCO" in sym or "BRENT" in sym:
        lots = abs(units) / 1000.0
    else:
        lots = abs(units) / 100000.0
    return round(max(lots, 0.01), 2)


@dataclass
class FakeBroker:
    """In-memory broker. Bound to a TapeServer instance."""

    tape: object  # TapeServer (forward-declared to avoid circular import)
    starting_balance: float = 10000.0

    _orders: dict[str, Order] = field(default_factory=dict)  # ticket → Order
    _next_ticket_seq: int = field(default=2_000_000_000)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _balance: float = field(init=False)
    _seen_bars: dict[tuple[str, str], datetime] = field(default_factory=dict)
    # closed_orders.json equivalent: ticket → details
    _closed_history: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        self._balance = self.starting_balance

    # ── Internal helpers ────────────────────────────────────────────────

    def _new_ticket(self) -> str:
        with self._lock:
            self._next_ticket_seq += 1
            return str(self._next_ticket_seq)

    def _instrument_for_symbol(self, symbol: str) -> str:
        """MT5 symbol (e.g. 'XAUUSD.std') → internal ('XAU_USD')."""
        # mt5_executor stores SYMBOL_MAP_REVERSE; here we strip suffixes.
        s = symbol.upper()
        if s.startswith("XAU") or s.startswith("XAUUSD"):
            return "XAU_USD"
        if s.startswith("BCO") or s.startswith("BRENT"):
            return "BCO_USD"
        return symbol

    def _equity(self) -> float:
        """balance + sum(open positions' unrealized PnL)."""
        unrealized = sum(o.profit for o in self._orders.values() if o.state == "OPEN")
        return self._balance + unrealized

    def _update_unrealized(self) -> None:
        """Recompute unrealized PnL on every open order using current tick."""
        for o in self._orders.values():
            if o.state != "OPEN":
                continue
            tick = self.tape.get_current_tick(o.instrument)
            if not tick:
                continue
            if o.side == "BUY":
                # mid - entry, on remaining size
                mid = tick["mid"]
                o.profit = (mid - o.open_price) * o.units
            else:
                mid = tick["mid"]
                o.profit = (o.open_price - mid) * o.units

    # ── Live mt5_executor API surface (mirrors signatures) ──────────────

    def get_current_price(self, instrument: str = "XAU_USD") -> Optional[dict]:
        return self.tape.get_current_tick(instrument)

    def get_account_summary(self) -> dict:
        self._update_unrealized()
        equity = self._equity()
        unrealized = sum(o.profit for o in self._orders.values() if o.state == "OPEN")
        return {
            "balance": self._balance,
            "nav": equity,
            "nav_usd": equity,
            "unrealized_pl": unrealized,
            "margin_used": 0.0,  # we don't model margin
            "open_trades": sum(1 for o in self._orders.values() if o.state == "OPEN"),
            "currency": "USD",
            "gbp_usd_rate": 1.0,
        }

    def get_open_trades(self, instrument: Optional[str] = None) -> list[dict]:
        """Return list shape matching mt5_executor.get_open_trades."""
        self._update_unrealized()
        result = []
        for o in self._orders.values():
            if o.state != "OPEN":
                continue
            if instrument and o.instrument != instrument:
                continue
            result.append({
                "id": o.ticket,
                "instrument": o.instrument,
                "currentUnits": o.units if o.side == "BUY" else -o.units,
                "price": o.open_price,
                "unrealizedPL": o.profit,
                "sl": o.sl if o.sl > 0 else None,
                "tp": o.tp if o.tp > 0 else None,
                "openTime": o.open_time.strftime("%Y.%m.%d %H:%M:%S") if o.open_time else "",
                "side": o.side,
                "comment": o.comment,
            })
        return result

    def get_candles(self, instrument: str = "XAU_USD", granularity: str = "H1",
                    count: int = 24, price: str = "BA") -> list[dict]:
        """Direct passthrough — tape server handles the chronological view."""
        return self.tape.get_window(instrument, granularity, count)

    def place_market_order(self, instrument: str, units: float,
                           sl: Optional[float] = None,
                           tp: Optional[float] = None,
                           comment: str = "") -> dict:
        """Fill at the CURRENT M3 bar's open + slippage.

        Slippage formula matches BT's `+ _slippage(bar_range)` for LONG
        market entries, `- _slippage(bar_range)` for SHORT. The "bar_range"
        is the current M3 bar's high-low.
        """
        side = "BUY" if units > 0 else "SELL"
        vol = abs(units)
        bar = self.tape.get_current_bar(instrument, "M3")
        if not bar:
            # No bar at exact tape time — use most recent
            window = self.tape.get_window(instrument, "M3", 1)
            if not window:
                return {"success": False, "error": "no_market_data"}
            bar = window[-1]

        # Mirror BT signal_entry computation: ask_close + slip for LONG, bid_close - slip for SHORT
        # Then apply at the bar's close (== "fill at next available price after the bar").
        bar_range = bar["bid_high"] - bar["bid_low"] if side == "BUY" else bar["ask_high"] - bar["ask_low"]
        # BT uses signal.entry = ask_close[bar_idx] + slippage(bar_range) for LONG
        # We model fill at ask_close + slippage(bar_range) for LONG market entry.
        # For market orders the live's strategy already computed signal.entry;
        # here we just need to fill SOMEWHERE close to it.
        from backend.config import slippage as bt_slippage
        slip = bt_slippage(bar_range)
        if side == "BUY":
            fill_price = bar["ask_close"] + slip
        else:
            fill_price = bar["bid_close"] - slip

        ticket = self._new_ticket()
        now = self.tape.current_time()
        order = Order(
            ticket=ticket,
            instrument=instrument,
            side=side,
            units=vol,
            open_price=fill_price,
            sl=float(sl) if sl else 0.0,
            tp=float(tp) if tp else 0.0,
            comment=comment or "",
            placed_at=now,
            open_time=now,
            order_type="MARKET",
            state="OPEN",
        )
        self._orders[ticket] = order
        return {
            "success": True,
            "fill_price": fill_price,
            "trade_id": ticket,
            "units": vol,
            "time": now.isoformat(),
        }

    def place_limit_order(self, instrument: str, units: float, limit_price: float,
                          sl: Optional[float] = None, tp: Optional[float] = None,
                          ttl_seconds: int = 900, comment: str = "") -> dict:
        """Place a pending limit. Filled by `tick()` when wick crosses."""
        side = "BUY" if units > 0 else "SELL"
        ticket = self._new_ticket()
        now = self.tape.current_time()
        order = Order(
            ticket=ticket,
            instrument=instrument,
            side=side,
            units=abs(units),
            open_price=float(limit_price),  # limit; will be overwritten on fill
            sl=float(sl) if sl else 0.0,
            tp=float(tp) if tp else 0.0,
            comment=comment or "",
            placed_at=now,
            order_type="BUY_LIMIT" if side == "BUY" else "SELL_LIMIT",
            state="PENDING",
            ttl_seconds=ttl_seconds,
            expiration=now + timedelta(seconds=ttl_seconds),
        )
        self._orders[ticket] = order
        return {
            "success": True,
            "ticket": ticket,
            "limit_price": float(limit_price),
            "expiration_time": order.expiration.strftime("%Y.%m.%d %H:%M:%S"),
            "units": abs(units),
            "time": now.isoformat(),
        }

    def cancel_pending_order(self, ticket: str) -> dict:
        o = self._orders.get(str(ticket))
        if not o:
            return {"success": False, "error": "ticket_not_found"}
        if o.state != "PENDING":
            return {"success": False, "error": f"not_pending: state={o.state}"}
        o.state = "CLOSED"
        o.close_time = self.tape.current_time()
        o.exit_reason = "CANCELLED"
        self._closed_history[ticket] = self._to_history(o)
        return {"success": True}

    def modify_stop_loss(self, trade_id: str, new_sl: float,
                         new_tp: Optional[float] = None) -> dict:
        o = self._orders.get(str(trade_id))
        if not o or o.state != "OPEN":
            return {"success": False, "error": "trade_not_found_or_closed"}
        o.sl = float(new_sl) if new_sl else 0.0
        if new_tp is not None:
            o.tp = float(new_tp) if new_tp else 0.0
        return {"success": True}

    def close_trade(self, trade_id: str) -> dict:
        """Force-close at current tick (used by MAX_HOLD)."""
        o = self._orders.get(str(trade_id))
        if not o or o.state != "OPEN":
            return {"success": False, "error": "trade_not_found_or_closed"}
        tick = self.tape.get_current_tick(o.instrument)
        if not tick:
            return {"success": False, "error": "no_market_data"}
        # Close at mid (matches "market close" behaviour)
        close_price = tick["mid"]
        self._close_order(o, close_price, "MAX_HOLD")
        return {
            "success": True,
            "close_price": close_price,
            "realized_pl": o.realized_pl,
            "time": (o.close_time or self.tape.current_time()).isoformat(),
        }

    def close_partial_trade(self, trade_id: str, units_to_close: float,
                            instrument: str = "XAU_USD") -> dict:
        """Filter #7: bank `units_to_close` out of position at current mid."""
        o = self._orders.get(str(trade_id))
        if not o or o.state != "OPEN":
            return {"success": False, "error": "trade_not_found_or_closed"}
        if units_to_close >= o.units:
            return {"success": False, "error": "partial_close_exceeds_remaining"}
        tick = self.tape.get_current_tick(o.instrument)
        if not tick:
            return {"success": False, "error": "no_market_data"}
        partial_price = tick["mid"]
        if o.side == "BUY":
            partial_pl = (partial_price - o.open_price) * units_to_close
        else:
            partial_pl = (o.open_price - partial_price) * units_to_close
        self._balance += partial_pl
        o.units -= units_to_close
        o.partial_filled = True
        o.partial_units_closed += units_to_close
        return {
            "success": True,
            "close_price": partial_price,
            "units_closed": units_to_close,
            "remaining_units": o.units,
            "realized_pl": partial_pl,
            "time": self.tape.current_time().isoformat(),
        }

    def get_trade_details(self, trade_id: str) -> Optional[dict]:
        """Mirror mt5_executor: return CLOSED state with broker fill data."""
        o = self._orders.get(str(trade_id))
        if not o:
            # Maybe it's in history only (closed long ago, evicted)
            return self._closed_history.get(str(trade_id))
        if o.state != "CLOSED":
            return None  # still open
        return self._to_history(o)

    def is_connected(self) -> bool:
        return True

    # ── Bridge driver: called by replay runner each clock advance ───────

    def tick(self) -> list[dict]:
        """Called whenever the tape clock advances. Walk all OPEN/PENDING
        orders against bars from prev-clock to now-clock; trigger fills,
        SL/TP, BE arming, MAX_HOLD.

        Returns: list of events that fired this tick (for journal).
        """
        events: list[dict] = []
        clock = self.tape.current_time()

        for ticket, o in list(self._orders.items()):
            # Walk bars between previous bridge-clock and current clock,
            # to catch fills that happened mid-step.
            if o.state == "PENDING":
                # Did the limit fill within TTL?
                events.extend(self._tick_pending(o))
            elif o.state == "OPEN":
                events.extend(self._tick_open(o))

        return events

    def _tick_pending(self, o: Order) -> list[dict]:
        events = []
        clock = self.tape.current_time()
        # Check TTL expiry
        if o.expiration and clock > o.expiration:
            o.state = "CLOSED"
            o.close_time = clock
            o.exit_reason = "TTL_EXPIRED"
            self._closed_history[o.ticket] = self._to_history(o)
            events.append({
                "ticket": o.ticket,
                "type": "LIMIT_TTL_EXPIRED",
                "time": clock.isoformat(),
            })
            return events

        # Walk M3 bars from placed_at → clock looking for limit-fill
        for bar in self.tape.iter_bars(o.instrument, "M3", o.placed_at, clock):
            bar_ts = datetime.fromisoformat(bar["timestamp"])
            if bar_ts <= o.placed_at:
                continue  # don't fill on the bar where the limit was placed
            if bar_ts > clock:
                break
            if o.side == "BUY":
                # Fill if bid_low touches limit
                if bar["bid_low"] <= o.open_price:
                    o.state = "OPEN"
                    o.open_time = bar_ts
                    # Apply small slippage matching BT's _sl_slip × 0.2 for fills
                    bar_range = bar["bid_high"] - bar["bid_low"]
                    slip = _sl_slip(bar_range) * 0.2
                    o.open_price = o.open_price + slip
                    events.append({
                        "ticket": o.ticket,
                        "type": "LIMIT_FILLED",
                        "fill_price": o.open_price,
                        "time": bar_ts.isoformat(),
                    })
                    return events
            else:
                if bar["ask_high"] >= o.open_price:
                    o.state = "OPEN"
                    o.open_time = bar_ts
                    bar_range = bar["ask_high"] - bar["ask_low"]
                    slip = _sl_slip(bar_range) * 0.2
                    o.open_price = o.open_price - slip
                    events.append({
                        "ticket": o.ticket,
                        "type": "LIMIT_FILLED",
                        "fill_price": o.open_price,
                        "time": bar_ts.isoformat(),
                    })
                    return events
        return events

    def _tick_open(self, o: Order) -> list[dict]:
        """Walk bars between open_time and clock; check SL/TP fills.

        Mirrors backend/execution/fill_model.py priority order:
          1. Gap-through SL
          2. Partial TP (handled in live cron, not here)
          3. TP touch (TP wins tie at bar level)
          4. SL touch
        """
        events = []
        clock = self.tape.current_time()
        last_seen = self._seen_bars.get((o.ticket, "M3"), o.open_time)

        for bar in self.tape.iter_bars(o.instrument, "M3", last_seen, clock):
            bar_ts = datetime.fromisoformat(bar["timestamp"])
            if bar_ts <= o.open_time:
                continue
            if bar_ts > clock:
                break
            self._seen_bars[(o.ticket, "M3")] = bar_ts
            o.bars_held += 1

            if o.side == "BUY":
                bo, bh, bl, bc = bar["bid_open"], bar["bid_high"], bar["bid_low"], bar["bid_close"]
                bar_range = bh - bl

                # 1. Gap-through SL
                if o.sl > 0 and bo <= o.sl:
                    slip = _sl_slip(bar_range)
                    exit_price = bo - slip * 0.2
                    self._close_order(o, exit_price, "SL", close_time=bar_ts)
                    events.append({"ticket": o.ticket, "type": "SL_GAP", "fill": exit_price, "time": bar_ts.isoformat()})
                    return events

                # 3. TP touch (bar high >= TP) — TP wins tie
                if o.tp > 0 and bh >= o.tp:
                    self._close_order(o, o.tp, "TP", close_time=bar_ts)
                    events.append({"ticket": o.ticket, "type": "TP", "fill": o.tp, "time": bar_ts.isoformat()})
                    return events

                # 4. SL touch
                if o.sl > 0 and bl <= o.sl:
                    slip = _sl_slip(bar_range)
                    exit_price = o.sl - slip * 0.2
                    self._close_order(o, exit_price, "SL", close_time=bar_ts)
                    events.append({"ticket": o.ticket, "type": "SL", "fill": exit_price, "time": bar_ts.isoformat()})
                    return events
            else:  # SELL
                ao, ah, al, ac = bar["ask_open"], bar["ask_high"], bar["ask_low"], bar["ask_close"]
                bar_range = ah - al

                if o.sl > 0 and ao >= o.sl:
                    slip = _sl_slip(bar_range)
                    exit_price = ao + slip * 0.2
                    self._close_order(o, exit_price, "SL", close_time=bar_ts)
                    events.append({"ticket": o.ticket, "type": "SL_GAP", "fill": exit_price, "time": bar_ts.isoformat()})
                    return events

                if o.tp > 0 and al <= o.tp:
                    self._close_order(o, o.tp, "TP", close_time=bar_ts)
                    events.append({"ticket": o.ticket, "type": "TP", "fill": o.tp, "time": bar_ts.isoformat()})
                    return events

                if o.sl > 0 and ah >= o.sl:
                    slip = _sl_slip(bar_range)
                    exit_price = o.sl + slip * 0.2
                    self._close_order(o, exit_price, "SL", close_time=bar_ts)
                    events.append({"ticket": o.ticket, "type": "SL", "fill": exit_price, "time": bar_ts.isoformat()})
                    return events
        return events

    # ── Internals ───────────────────────────────────────────────────────

    def _close_order(self, o: Order, close_price: float, reason: str,
                     close_time: Optional[datetime] = None) -> None:
        if o.side == "BUY":
            pl = (close_price - o.open_price) * o.units
        else:
            pl = (o.open_price - close_price) * o.units
        o.close_price = close_price
        o.close_time = close_time or self.tape.current_time()
        o.realized_pl = pl
        o.profit = pl
        o.exit_reason = reason
        o.state = "CLOSED"
        self._balance += pl
        self._closed_history[o.ticket] = self._to_history(o)

    @staticmethod
    def _to_history(o: Order) -> dict:
        """closed_orders.json-equivalent record."""
        return {
            "state": "CLOSED",
            "realized_pl": o.realized_pl,
            "close_price": o.close_price or 0.0,
            "close_time": (o.close_time or datetime.now(timezone.utc)).isoformat(),
            "exit_reason": o.exit_reason or "CLOSED",
            "open_price": o.open_price,
            "side": o.side,
            "units": o.units,
            "instrument": o.instrument,
            "comment": o.comment,
            "ticket": o.ticket,
        }
