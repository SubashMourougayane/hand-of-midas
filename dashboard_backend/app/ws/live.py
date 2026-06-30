"""WebSocket /ws/live — server-pushes Postgres NOTIFY events to clients.

Wiring:
  - One asyncpg connection per FastAPI process LISTENs on 4 channels.
  - Each incoming WebSocket connection registers itself with a fanout broker.
  - When NOTIFY fires, broker pushes the parsed JSON envelope to all clients
    whose `run_id` filter matches (or whose filter is None = listen-all).

Envelope shape:
  {channel: "journal"|"signal"|"trade"|"account", run_id, ts, payload}
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..deps import get_dsn_for_asyncpg

log = logging.getLogger(__name__)

router = APIRouter()

# Channel name → output `channel` label.
_CHANNEL_MAP = {
    "bt_journal_events": "journal",
    "bt_signals": "signal",
    "bt_trades": "trade",
    "bt_account_snapshot": "account",
}


class _Broker:
    """Fans out NOTIFY events to connected WebSocket clients."""

    def __init__(self) -> None:
        self._clients: set[tuple[WebSocket, Optional[UUID]]] = set()
        self._lock = asyncio.Lock()
        self._conn: asyncpg.Connection | None = None
        self._listen_task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        if self._conn is not None:
            return
        dsn = get_dsn_for_asyncpg()
        self._conn = await asyncpg.connect(dsn)
        for channel in _CHANNEL_MAP:
            await self._conn.add_listener(channel, self._on_notify)
        log.info("ws broker LISTENING on %s", list(_CHANNEL_MAP))

    async def stop(self) -> None:
        self._stopped = True
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _on_notify(self, _conn, _pid, channel, payload):
        # asyncpg callback runs synchronously on the listener task — fan out
        # via a scheduled task so we don't block.
        asyncio.create_task(self._fanout(channel, payload))

    async def _fanout(self, channel: str, payload: str) -> None:
        try:
            row = json.loads(payload)
        except Exception:
            log.exception("bad notify payload: %r", payload)
            return
        ch_label = _CHANNEL_MAP.get(channel, channel)
        # NOTIFY payload contains run_id/ts as strings — pass through.
        ts = row.get("ts") or datetime.now(timezone.utc).isoformat()
        run_id_str = row.get("run_id")
        envelope = {
            "channel": ch_label,
            "run_id": run_id_str,
            "ts": ts,
            "payload": row,
        }
        encoded = json.dumps(envelope, default=str)
        dead: list[tuple[WebSocket, Optional[UUID]]] = []
        async with self._lock:
            clients = list(self._clients)
        for ws, rid_filter in clients:
            if rid_filter is not None and run_id_str != str(rid_filter):
                continue
            try:
                await ws.send_text(encoded)
            except Exception:
                dead.append((ws, rid_filter))
        if dead:
            async with self._lock:
                for d in dead:
                    self._clients.discard(d)

    async def add(self, ws: WebSocket, run_id: Optional[UUID]) -> None:
        async with self._lock:
            self._clients.add((ws, run_id))

    async def remove(self, ws: WebSocket, run_id: Optional[UUID]) -> None:
        async with self._lock:
            self._clients.discard((ws, run_id))


broker = _Broker()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket, run_id: Optional[UUID] = None) -> None:
    await websocket.accept()
    await broker.add(websocket, run_id)
    try:
        # Send hello so client knows connection is up.
        await websocket.send_text(json.dumps({
            "channel": "hello",
            "run_id": str(run_id) if run_id else None,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": {"server": "dashboard_backend", "version": "0.1.0"},
        }))
        while True:
            # Keep the connection open; ignore client messages (read-only push).
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({
                    "channel": "pong",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "payload": {},
                }))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_live client error")
    finally:
        await broker.remove(websocket, run_id)
