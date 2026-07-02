"""Live price streamer — tails the DWX market_data.json and fans out a `price`
envelope over the same WebSocket broker as DB NOTIFY events.

Real-desk feel: instead of the frontend HTTP-polling for price every 15s, the
server watches the broker's live quote dump and pushes bid/ask to every client
the instant it changes. Read-only: never touches strategy/engine/live code —
just reads the JSON file the DWX EA already writes ~every tick.

Envelope shape (matches ws/live.py convention):
  {channel: "price", run_id: null, ts, payload: {symbol, bid, ask, mid, time}}

run_id is null (price is symbol-global, not per-leg) — listen-all clients and
per-run clients both receive it (the broker only run_id-filters non-null rids).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DWX_DIR = Path(os.environ.get(
    "DWX_DIR",
    str(Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5"
        "/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"),
))
MARKET_FILE = DWX_DIR / "market_data.json"
ACCOUNT_FILE = DWX_DIR / "account_info.json"

# Absolute price floors per symbol (base name, pre-suffix). A quote below this
# is a torn/partial read (leading digits dropped), not a real tick.
_PRICE_FLOOR = {
    "XAUUSD": 1000.0,   # gold has been >$1000 the whole modern era
    "EURUSD": 0.5,
    "GBPUSD": 0.5,
    "BTCUSD": 1000.0,
}

# Poll the local file this often. The FILE is updated by the EA ~every tick;
# this is a local filesystem read (sub-ms), so 1s gives near-instant push
# without hammering. Only fans out when a quote actually CHANGES.
POLL_S = 1.0


class PriceStreamer:
    """Background task: reads market_data.json, pushes changed quotes to broker."""

    def __init__(self, broker) -> None:
        self._broker = broker
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._last: dict[str, tuple[float, float]] = {}  # symbol -> (bid, ask)
        self._last_acct: tuple | None = None  # (balance, equity, profit)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run())
        log.info("price streamer started (watching %s)", MARKET_FILE)

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                await self._tick()
            except Exception:
                log.debug("price tick failed", exc_info=True)
            try:
                await self._acct_tick()
            except Exception:
                log.debug("acct tick failed", exc_info=True)
            await asyncio.sleep(POLL_S)

    async def _acct_tick(self) -> None:
        """Push live account balance/equity/open-profit (broker truth) so the
        cockpit P&L moves tick-by-tick, not on the M15 bar-close DB snapshot.
        Channel 'account_live' (distinct from the DB 'account' NOTIFY channel)."""
        if not ACCOUNT_FILE.is_file():
            return
        try:
            a = json.loads(ACCOUNT_FILE.read_text())
        except Exception:
            return
        if not isinstance(a, dict):
            return
        bal = _f(a.get("balance"))
        eq = _f(a.get("equity"))
        profit = _f(a.get("profit"))
        # Torn-read guard: reject if equity jumps >20% vs last good (partial write).
        if self._last_acct is not None and eq is not None:
            prev_eq = self._last_acct[1]
            if prev_eq and prev_eq > 0 and abs(eq - prev_eq) / prev_eq > 0.20:
                return
        key = (bal, eq, profit)
        if self._last_acct == key:
            return
        self._last_acct = key
        await self._broker.broadcast({
            "channel": "account_live",
            "run_id": None,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "balance": bal,
                "equity": eq,
                "open_pnl": profit,   # MT5 'profit' = open floating P&L
                "margin": _f(a.get("margin")),
                "free_margin": _f(a.get("free_margin")),
            },
        })

    async def _tick(self) -> None:
        if not MARKET_FILE.is_file():
            return
        try:
            raw = json.loads(MARKET_FILE.read_text())
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for symbol, q in raw.items():
            if not isinstance(q, dict):
                continue
            bid = _f(q.get("bid"))
            ask = _f(q.get("ask"))
            if bid is None and ask is None:
                continue
            # Torn-read guard. The EA writes market_data.json non-atomically; a
            # mid-write read can drop leading digits (4070.55 -> 70.55) on BOTH
            # bid and ask together. Two defenses:
            #  (a) spread sanity: bid/ask within 5% of each other, and
            #  (b) per-symbol absolute plausibility band vs the last GOOD value:
            #      once we have a good price P, reject anything <0.5*P or >2*P.
            ref = bid if bid is not None else ask
            if ref is None or ref <= 0:
                continue
            # Torn-read guard. EA writes non-atomically; a mid-write read drops
            # leading digits (4070.55 -> 70.55). Absolute per-symbol floor is the
            # only bulletproof filter (relative-to-last poisons on a corrupt first
            # read). XAU has traded >1000 for the entire era; a sub-floor value is
            # definitionally a partial read.
            floor = _PRICE_FLOOR.get(symbol.split(".")[0], 0.0)
            if ref < floor:
                continue
            # Spread sanity (both bid+ask present): reject absurd spreads.
            if bid is not None and ask is not None and abs(ask - bid) / ref > 0.05:
                continue
            # Torn-read guard: the EA writes market_data.json non-atomically, so
            # a read mid-write can yield a truncated number (e.g. 4070.55 -> 70.55).
            # Reject a quote that jumps >20% vs the last known good value — real
            # XAU never moves that far tick-to-tick; that's a corrupt partial read.
            prev = self._last.get(symbol)
            if prev is not None and bid is not None:
                prev_bid = prev[0]
                if prev_bid > 0 and abs(bid - prev_bid) / prev_bid > 0.20:
                    continue  # corrupt / torn read — skip this tick
            key = (bid or 0.0, ask or 0.0)
            if self._last.get(symbol) == key:
                continue  # unchanged — don't spam
            self._last[symbol] = key
            mid = None
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
            elif bid is not None:
                mid = bid
            elif ask is not None:
                mid = ask
            envelope = {
                "channel": "price",
                "run_id": None,
                "ts": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "symbol": symbol,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "broker_time": q.get("time"),
                },
            }
            await self._broker.broadcast(envelope)


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
