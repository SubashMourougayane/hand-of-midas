"""Hand of Midas — Telegram trade-alert notifier.

A standalone, fully-decoupled service. It LISTENs on the Postgres NOTIFY channels
the DB already fires (bt_journal_events, bt_trades) — the same ones the dashboard
consumes — enriches each event with a DB read, formats via templates.py, and POSTs
to Telegram. It NEVER touches the strategy / engine / live-runner and never blocks
the trade loop (separate process, separate connection).

Events → alerts (all four groups, user-approved 2026-07-06):
  1. ENTRY_FILL (fresh)            → entry card
  2. PARTIAL_TP_APPLIED            → partial + SL→BE card
  3. EXIT_* (via broker_reconciled)→ close card WITH exact broker $ (wait-for-$)
  4. adoption on restart + errors  → summary + 🚨 anomaly cards

Design choices:
  - wait-for-exact-$ on closes: the EXIT journal event marks a trade "closing";
    the actual alert fires when the bt_trades UPDATE NOTIFY carries a populated
    broker_net_usd (reconciled). A watchdog flushes with an estimate if reconcile
    never lands within CLOSE_FALLBACK_S.
  - dedup: a persistent seen-set (entries) + closing/closed sets survive a notifier
    restart via the DB (we query recent state on boot), so restarting the notifier
    never re-alerts already-open or already-closed trades.
  - only live-mode runs alert (join bt_runs.mode='live').
  - send failures never crash the listener (logged + dropped).

Env:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   — required
  BT_ENGINE_DB_URL                        — postgresql URL (asyncpg form)
  TELEGRAM_ENABLED=0                      — kill switch (any value != 1 disables sends)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

import asyncpg
import httpx

# templates.py sits beside this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import templates  # noqa: E402

log = logging.getLogger("midas.notifier")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ENABLED = os.environ.get("TELEGRAM_ENABLED", "1") == "1"
CLOSE_FALLBACK_S = 150.0  # if reconcile $ never lands, flush close with estimate

_CONTRACT = templates._CONTRACT


def _dsn() -> str:
    url = os.environ.get("BT_ENGINE_DB_URL") or os.environ.get("DATABASE_URL") or ""
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def _send(client: httpx.AsyncClient, text: str) -> None:
    """POST to Telegram. Never raises — logs + drops on failure."""
    if not ENABLED:
        log.info("[SEND-DISABLED] %s", text.split(chr(10))[0])
        return
    if not TOKEN or not CHAT_ID:
        log.error("missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — cannot send")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for attempt in range(3):
        try:
            r = await client.post(url, data={
                "chat_id": CHAT_ID,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
                "text": text,
            }, timeout=15.0)
            if r.status_code == 200:
                return
            if r.status_code == 429:
                retry = 2.0 * (attempt + 1)
                log.warning("telegram 429 — backoff %.1fs", retry)
                await asyncio.sleep(retry)
                continue
            log.error("telegram %s: %s", r.status_code, r.text[:200])
            return
        except Exception as e:  # noqa: BLE001
            log.warning("telegram send attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(0.5 * (attempt + 1))
    log.error("telegram send exhausted retries; dropping message")


async def _live_run_ids(conn: asyncpg.Connection) -> set:
    rows = await conn.fetch("SELECT run_id FROM bt_runs WHERE mode = 'live'")
    return {r["run_id"] for r in rows}


async def _trade_row(conn: asyncpg.Connection, trade_id) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT t.trade_id, t.run_id, t.broker_ticket, t.side, t.symbol, t.leg,
               t.entry_price, t.stop_price, t.take_profit_price, t.risk_units,
               t.exit_price, t.exit_reason, t.exit_timestamp, t.entry_timestamp,
               t.bars_held, t.net_r, t.partial_taken, t.partial_r,
               t.broker_net_usd, t.broker_exit_price, t.broker_reconciled_at,
               (t.raw_features->>'qty_lots')  AS qty_lots,
               (t.raw_features->>'partial_booked_usd') AS partial_booked_usd,
               r.mode AS run_mode
        FROM bt_trades t JOIN bt_runs r ON r.run_id = t.run_id
        WHERE t.trade_id = $1
        """,
        trade_id,
    )
    if row is None:
        return None
    d = dict(row)
    for k in ("qty_lots", "partial_booked_usd"):
        try:
            d[k] = float(d[k]) if d[k] is not None else None
        except (TypeError, ValueError):
            d[k] = None
    if d.get("entry_timestamp") and d.get("exit_timestamp"):
        d["held_minutes"] = (d["exit_timestamp"] - d["entry_timestamp"]).total_seconds() / 60.0
    return d


async def _latest_balance(conn: asyncpg.Connection, run_id) -> float | None:
    row = await conn.fetchrow(
        "SELECT balance FROM bt_account_snapshot WHERE run_id = $1 "
        "ORDER BY ts DESC LIMIT 1", run_id,
    )
    return float(row["balance"]) if row and row["balance"] is not None else None


class Notifier:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.seen_entries: set = set()      # trade_ids already entry-alerted
        self.closing: dict = {}             # trade_id -> monotonic deadline (awaiting $)
        self.closed_sent: set = set()       # trade_ids close-alerted
        self.live_runs: set = set()
        self.client = httpx.AsyncClient()
        self.conn: asyncpg.Connection | None = None  # query conn (separate from listen)

    async def _is_live(self, run_id) -> bool:
        if run_id in self.live_runs:
            return True
        # refresh once (a new live run may have started after boot)
        self.live_runs = await _live_run_ids(self.conn)
        return run_id in self.live_runs

    async def _hydrate_boot_state(self) -> None:
        """On boot, seed seen-sets from recent DB state so a notifier restart never
        re-alerts already-open (entry) or already-closed trades."""
        self.live_runs = await _live_run_ids(self.conn)
        if not self.live_runs:
            return
        rows = await self.conn.fetch(
            "SELECT trade_id, exit_timestamp FROM bt_trades "
            "WHERE run_id = ANY($1::uuid[])", list(self.live_runs),
        )
        for r in rows:
            self.seen_entries.add(r["trade_id"])
            if r["exit_timestamp"] is not None:
                self.closed_sent.add(r["trade_id"])
        log.info("[BOOT] hydrated %d known trades across %d live runs",
                 len(self.seen_entries), len(self.live_runs))

    # ── event handlers ──────────────────────────────────────────────────────

    async def on_journal(self, payload: dict) -> None:
        etype = payload.get("event_type")
        trade_id = payload.get("trade_id")
        run_id = payload.get("run_id")
        if trade_id is None or run_id is None:
            return
        tid = _as_uuid(trade_id)
        rid = _as_uuid(run_id)
        if not await self._is_live(rid):
            return

        if etype == "ENTRY_FILL":
            if tid in self.seen_entries:
                return  # adoption re-open or dup
            self.seen_entries.add(tid)
            t = await _trade_row(self.conn, tid)
            if t:
                await _send(self.client, templates.entry(t))

        elif etype == "PARTIAL_TP_APPLIED":
            t = await _trade_row(self.conn, tid)
            if t:
                # booked $ from raw_features fallback; remainder = full - closed(half)
                t["booked_usd"] = t.get("partial_booked_usd")
                q = t.get("qty_lots")
                t["remainder_lots"] = round(q * 0.5, 2) if q else None
                await _send(self.client, templates.partial(t))

        elif etype in ("PARTIAL_TP_ORPHANED", "PARTIAL_TP_SAFE_CLOSED",
                       "PARTIAL_TP_MODIFY_FAILED", "PARTIAL_TP_CLOSE_FAILED",
                       "TIMEOUT_CLOSE_FAILED"):
            t = await _trade_row(self.conn, tid) or {}
            await _send(self.client, templates.anomaly(etype, t))

        elif etype and etype.startswith("EXIT_"):
            # mark closing; the real close alert fires on the reconciled UPDATE
            # (or the watchdog flush). Dedup against already-sent.
            if tid not in self.closed_sent:
                loop = asyncio.get_event_loop()
                self.closing[tid] = loop.time() + CLOSE_FALLBACK_S

    async def on_trade_update(self, payload: dict) -> None:
        """bt_trades INSERT/UPDATE NOTIFY. We use the UPDATE (exit stamped + reconcile)
        to fire the exact-$ close alert."""
        trade_id = payload.get("trade_id")
        run_id = payload.get("run_id")
        if trade_id is None or run_id is None:
            return
        tid = _as_uuid(trade_id)
        rid = _as_uuid(run_id)
        if not await self._is_live(rid):
            return
        if tid in self.closed_sent or tid not in self.closing:
            return
        t = await _trade_row(self.conn, tid)
        if not t or t.get("exit_timestamp") is None:
            return
        # Fire only once broker $ is reconciled (wait-for-exact-$).
        if t.get("broker_net_usd") is not None:
            await self._flush_close(tid, t)

    async def _flush_close(self, tid, t: dict) -> None:
        if tid in self.closed_sent:
            return
        self.closed_sent.add(tid)
        self.closing.pop(tid, None)
        t["balance"] = await _latest_balance(self.conn, t.get("run_id"))
        await _send(self.client, templates.close(t))

    async def watchdog(self) -> None:
        """Flush closes whose broker $ never reconciled within the fallback window,
        using net_r (no exact $). Runs every 15s."""
        while True:
            await asyncio.sleep(15.0)
            loop = asyncio.get_event_loop()
            now = loop.time()
            due = [tid for tid, dl in list(self.closing.items()) if now >= dl]
            for tid in due:
                if tid in self.closed_sent:
                    self.closing.pop(tid, None)
                    continue
                t = await _trade_row(self.conn, tid)
                if t and t.get("exit_timestamp") is not None:
                    t.setdefault("note", "")
                    await self._flush_close(tid, t)  # close() renders — as $ if None
                else:
                    self.closing.pop(tid, None)

    async def run(self) -> None:
        self.conn = await asyncpg.connect(self.dsn)
        await self._hydrate_boot_state()
        listen = await asyncpg.connect(self.dsn)

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _cb(channel):
            def handler(_conn, _pid, _chan, payload):
                loop.call_soon_threadsafe(queue.put_nowait, (channel, payload))
            return handler

        await listen.add_listener("bt_journal_events", _cb("bt_journal_events"))
        await listen.add_listener("bt_trades", _cb("bt_trades"))
        log.info("[LISTEN] bt_journal_events + bt_trades; alerts %s",
                 "ENABLED" if ENABLED else "DISABLED (dry)")

        asyncio.create_task(self.watchdog())

        while True:
            channel, raw = await queue.get()
            try:
                payload = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            try:
                if channel == "bt_journal_events":
                    await self.on_journal(payload)
                elif channel == "bt_trades":
                    await self.on_trade_update(payload)
            except Exception as e:  # noqa: BLE001
                log.exception("handler error on %s: %s", channel, e)


def _as_uuid(v):
    import uuid
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError):
        return v


async def _amain() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    dsn = _dsn()
    if not dsn:
        log.error("no DB URL (BT_ENGINE_DB_URL) — exiting")
        return 1
    n = Notifier(dsn)
    while True:
        try:
            await n.run()
        except Exception as e:  # noqa: BLE001
            log.exception("notifier crashed, restarting in 5s: %s", e)
            await asyncio.sleep(5.0)


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
