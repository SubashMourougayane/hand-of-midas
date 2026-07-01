"""BrokerReconciler — populate bt_trades.broker_* columns from DWX deal history.

The walker exits a trade with a synthetic gross_r + reason (its own view). This
module reconciles that against the broker's actual DEAL_PROFIT / DEAL_COMMISSION
/ DEAL_SWAP + deal_reason. Any divergence indicates execution-parity drift.

Behavior:
- On live trade close, `reconcile_trade(bridge, trade_id, ticket)` polls the
  broker's `closed_orders.json` up to N times with backoff, matches by ticket,
  writes broker_gross_usd + broker_commission_usd + broker_swap_usd + net.
- If no match after N tries, leaves broker_* cols NULL and logs a warning.
  Runner can retry on later bars via `retry_unreconciled_trades()`.
- Idempotent: skips trades where broker_reconciled_at is already set.

The EA writes DEAL_PROFIT as sign-adjusted profit in account currency (USD for
JustMarkets USD accounts). Commission + swap are separate. net = gross + comm
+ swap (comm/swap are already negative when they're a cost).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..data.dwx_bridge import DwxBridge
from ..db.models import BtTrade


log = logging.getLogger("bt_engine.reconciler")


@dataclass(frozen=True)
class ReconciliationResult:
    trade_id: uuid.UUID
    ticket: str
    matched: bool
    broker_gross_usd: float | None = None
    broker_commission_usd: float | None = None
    broker_swap_usd: float | None = None
    broker_net_usd: float | None = None
    broker_exit_price: float | None = None
    broker_exit_reason: str | None = None
    broker_close_ts: datetime | None = None


def _parse_broker_time(raw: str) -> datetime | None:
    """Broker time from EA is server-local `YYYY.MM.DD HH:MM:SS`. Callers must
    convert to UTC using server_utc_offset_hours if needed; here we return the
    parsed timestamp AS-IS (naive) and let the runner apply the offset.
    """
    if not raw:
        return None
    try:
        # EA format: "2026.07.01 12:45:28"
        return datetime.strptime(raw, "%Y.%m.%d %H:%M:%S")
    except ValueError:
        try:
            return pd.Timestamp(raw).to_pydatetime()
        except Exception:
            return None


def find_closed_deal(
    bridge: DwxBridge, ticket: str,
) -> dict[str, Any] | None:
    """Return the closed_orders entry matching `ticket`, or None."""
    if not ticket:
        return None
    try:
        rows = bridge.closed_orders()
    except Exception as e:
        log.debug("[RECONCILER] closed_orders read failed: %s", e)
        return None
    target = str(ticket)
    for row in rows:
        if str(row.get("ticket")) == target:
            return row
    return None


def _to_utc_dt(naive: datetime | None, server_utc_offset_hours: int) -> datetime | None:
    if naive is None:
        return None
    if naive.tzinfo is not None:
        # already tz-aware; convert to UTC
        return naive.astimezone(timezone.utc)
    # Broker server time = UTC + offset. To get UTC, subtract offset.
    return (naive - pd.Timedelta(hours=server_utc_offset_hours)).replace(tzinfo=timezone.utc)


def reconcile_trade(
    *,
    bridge: DwxBridge,
    session: Session,
    trade_id: uuid.UUID,
    ticket: str,
    server_utc_offset_hours: int = 0,
    max_retries: int = 20,
    backoff_s: float = 0.25,
) -> ReconciliationResult:
    """Try to find + persist broker's view of the closed trade.

    Retries up to `max_retries` times because MT5 fires DEAL_ENTRY_OUT async
    from CLOSE command — the closed_orders.json write may lag by a tick or two.
    Returns ReconciliationResult; caller decides whether to retry later.
    """
    trade: BtTrade | None = session.get(BtTrade, trade_id)
    if trade is None:
        log.warning("[RECONCILER] trade %s not in DB; skip", trade_id)
        return ReconciliationResult(trade_id=trade_id, ticket=ticket, matched=False)
    if trade.broker_reconciled_at is not None:
        log.debug("[RECONCILER] trade %s already reconciled; skip", trade_id)
        return ReconciliationResult(
            trade_id=trade_id, ticket=ticket, matched=True,
            broker_gross_usd=trade.broker_gross_usd,
            broker_commission_usd=trade.broker_commission_usd,
            broker_swap_usd=trade.broker_swap_usd,
            broker_net_usd=trade.broker_net_usd,
            broker_exit_price=trade.broker_exit_price,
            broker_exit_reason=trade.broker_exit_reason,
            broker_close_ts=trade.broker_close_ts,
        )

    deal: dict[str, Any] | None = None
    for attempt in range(max_retries):
        deal = find_closed_deal(bridge, ticket)
        if deal is not None:
            break
        if attempt < max_retries - 1:
            time.sleep(backoff_s)

    if deal is None:
        log.warning(
            "[RECONCILER] no closed_orders entry for ticket=%s after %d retries; "
            "will retry on next bar", ticket, max_retries,
        )
        # Still write broker_ticket so a later retry can find the trade.
        session.execute(
            update(BtTrade).where(BtTrade.trade_id == trade_id).values(broker_ticket=str(ticket))
        )
        session.commit()
        return ReconciliationResult(trade_id=trade_id, ticket=ticket, matched=False)

    gross = float(deal.get("profit") or 0.0)
    comm = float(deal.get("commission") or 0.0)
    swap = float(deal.get("swap") or 0.0)
    net = gross + comm + swap
    exit_price = float(deal.get("close_price") or 0.0) or None
    exit_reason = str(deal.get("deal_reason") or "") or None
    close_ts_utc = _to_utc_dt(
        _parse_broker_time(str(deal.get("close_time") or "")),
        server_utc_offset_hours,
    )

    session.execute(
        update(BtTrade).where(BtTrade.trade_id == trade_id).values(
            broker_ticket=str(ticket),
            broker_gross_usd=gross,
            broker_commission_usd=comm,
            broker_swap_usd=swap,
            broker_net_usd=net,
            broker_exit_price=exit_price,
            broker_exit_reason=exit_reason,
            broker_close_ts=close_ts_utc,
            broker_reconciled_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    log.info(
        "[RECONCILER] trade_id=%s ticket=%s broker: gross=$%+.2f comm=$%+.2f "
        "swap=$%+.2f NET=$%+.2f exit=%.5f reason=%s close_ts=%s",
        trade_id, ticket, gross, comm, swap, net,
        exit_price or 0.0, exit_reason, close_ts_utc,
    )
    return ReconciliationResult(
        trade_id=trade_id, ticket=ticket, matched=True,
        broker_gross_usd=gross, broker_commission_usd=comm,
        broker_swap_usd=swap, broker_net_usd=net,
        broker_exit_price=exit_price, broker_exit_reason=exit_reason,
        broker_close_ts=close_ts_utc,
    )


def retry_unreconciled_trades(
    *,
    bridge: DwxBridge,
    session: Session,
    run_id: uuid.UUID,
    server_utc_offset_hours: int = 0,
    limit: int = 20,
) -> list[ReconciliationResult]:
    """Sweep bt_trades: for trades in run that closed but have no broker_reconciled_at
    yet, retry once. Callers invoke this from on_bar_close for cheap recovery.
    """
    q = (
        select(BtTrade)
        .where(BtTrade.run_id == run_id)
        .where(BtTrade.exit_timestamp.is_not(None))
        .where(BtTrade.broker_reconciled_at.is_(None))
        .limit(limit)
    )
    pending = list(session.execute(q).scalars())
    results: list[ReconciliationResult] = []
    for tr in pending:
        ticket = tr.broker_ticket
        if not ticket:
            # No ticket recorded (BT trade, dry-run, or old row) — skip.
            continue
        res = reconcile_trade(
            bridge=bridge, session=session,
            trade_id=tr.trade_id, ticket=ticket,
            server_utc_offset_hours=server_utc_offset_hours,
            max_retries=3,  # cheap retry on sweep
            backoff_s=0.1,
        )
        results.append(res)
    return results
