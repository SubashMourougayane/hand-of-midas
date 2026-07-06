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
    """Return the AGGREGATE closed_orders view for `ticket`, or None.

    MT5 writes one row per deal. Partial-close positions get 2+ rows (partial
    close + final close) all sharing the same position_id (EA writes position_id
    as `ticket`). Reconciler must aggregate: sum profit / commission / swap,
    take the LAST close_time + close_price + deal_reason as the final exit.

    Regression: prior single-row lookup (L99 audit suspect #5) captured only the
    partial-close deal for partial-TP trades, understating true broker P&L.
    """
    if not ticket:
        return None
    try:
        rows = bridge.closed_orders()
    except Exception as e:
        log.debug("[RECONCILER] closed_orders read failed: %s", e)
        return None
    target = str(ticket)
    matches = [r for r in rows if str(r.get("ticket")) == target]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Aggregate multiple deals for same position (partial + final close).
    # EA writes rows chronologically — last row is the final exit.
    def _flt(v: Any) -> float:
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    total_profit = sum(_flt(r.get("profit")) for r in matches)
    total_swap = sum(_flt(r.get("swap")) for r in matches)
    total_commission = sum(_flt(r.get("commission")) for r in matches)
    total_volume = sum(_flt(r.get("volume")) for r in matches)
    last = matches[-1]
    aggregated = dict(last)
    aggregated["profit"] = total_profit
    aggregated["swap"] = total_swap
    aggregated["commission"] = total_commission
    aggregated["volume"] = total_volume
    aggregated["_deal_count"] = len(matches)
    return aggregated


# Max age of closed_orders.json before we distrust it. The EA rewrites it on
# each DEAL_ENTRY_OUT; if it hasn't been touched in this long it's stale (we've
# observed it lag >2h behind live), and a "closed" row in it may be a ghost from
# an earlier close event — NOT proof the current position is closed.
CLOSED_ORDERS_MAX_AGE_S = 300.0


def _ticket_still_open(bridge: DwxBridge, ticket: str, *, max_age_s: float = 15.0) -> bool:
    """True if `ticket` is present in a FRESH open_orders.json.

    Guard against reconciling-as-closed a position that is still live: a partial
    close leaves the remainder open under the same ticket, and closed_orders can
    carry a stale ghost row. If open_orders is itself stale we return False
    (can't confirm open) so we don't block a legitimate close.
    """
    try:
        age = time.time() - bridge.mtime("open_orders.json")
        if age > max_age_s:
            return False  # open_orders too stale to trust as proof-of-open
        orders = bridge.open_orders()
    except Exception:
        return False
    if not isinstance(orders, dict):
        return False
    inner = orders.get("orders", orders) if isinstance(orders, dict) else orders
    if not isinstance(inner, dict):
        return False
    return str(ticket) in {str(k) for k in inner}


def _closed_orders_is_fresh(bridge: DwxBridge, *, max_age_s: float = CLOSED_ORDERS_MAX_AGE_S) -> bool:
    """True if closed_orders.json was written recently enough to trust."""
    try:
        age = time.time() - bridge.mtime("closed_orders.json")
    except Exception:
        return False
    return age <= max_age_s


def _ticket_confirmed_gone(bridge: DwxBridge, ticket: str, *, max_age_s: float = 15.0) -> bool:
    """True ONLY if a FRESH open_orders.json positively shows `ticket` is absent.

    This is the strong form of "the position is closed": we have a recent
    open_orders snapshot and the ticket is not in it. Unlike GUARD 2's staleness
    check, this lets us trust a closed_orders match even when closed_orders.json
    is itself a bit old — because MT5 position tickets are unique, so a match in
    closed_orders for a ticket we've PROVEN is not open cannot be a "ghost" that
    would wrongly close a live position. If open_orders is stale or unreadable we
    return False (cannot confirm) and the normal freshness guard still applies.
    """
    try:
        age = time.time() - bridge.mtime("open_orders.json")
        if age > max_age_s:
            return False
        orders = bridge.open_orders()
    except Exception:
        return False
    if not isinstance(orders, dict):
        return False
    inner = orders.get("orders", orders)
    if not isinstance(inner, dict):
        return False
    return str(ticket) not in {str(k) for k in inner}


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

    # GUARD 1: never reconcile-as-closed a ticket that is still live in a fresh
    # open_orders.json. A partial close leaves the remainder open under the same
    # ticket; closed_orders can carry a stale ghost row. (Prevents the 2026-07-02
    # incident where a stale closed_orders marked an open position closed.)
    if _ticket_still_open(bridge, ticket):
        log.info(
            "[RECONCILER] ticket=%s still open in fresh open_orders — defer close",
            ticket,
        )
        return ReconciliationResult(trade_id=trade_id, ticket=ticket, matched=False)

    # GUARD 2: distrust a stale closed_orders.json. If the EA hasn't rewritten it
    # recently, any match may be a ghost from a much earlier close event.
    #
    # EXCEPTION (2026-07-06): on a quiet book closed_orders.json only rewrites when
    # a NEW deal closes, so it can sit stale for days — permanently blocking the $
    # backfill for a trade that closed (e.g. a weekend SL, exit_reason BROKER_CLOSED)
    # during the quiet window. That leaves broker_net_usd NULL forever while net_r
    # is scored (the +$384 dashboard overstatement, ticket 2125844421). Skip the
    # staleness guard when a FRESH open_orders.json POSITIVELY confirms the ticket
    # is gone: closure is then proven independently, and unique MT5 tickets mean a
    # closed_orders match cannot be a ghost that wrongly closes a live position.
    if not _closed_orders_is_fresh(bridge) and not _ticket_confirmed_gone(bridge, ticket):
        log.warning(
            "[RECONCILER] closed_orders.json stale (>%.0fs) and ticket=%s not "
            "confirmed gone — skip, retry later",
            CLOSED_ORDERS_MAX_AGE_S, ticket,
        )
        return ReconciliationResult(trade_id=trade_id, ticket=ticket, matched=False)

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

    # GUARD 3 (F7): never BANK+LOCK a partial-TP position when only part of its
    # volume has closed at the broker. `find_closed_deal` aggregates all deals
    # sharing the ticket, but the partial-close deal and the final-close deal do
    # NOT land in closed_orders.json at the same instant — a reconcile firing in
    # that window sees only the (usually profitable) partial and, without this
    # check, banks it as the whole result and sets broker_reconciled_at forever.
    # That is the +$544-instead-of-+$5 overstatement (ticket 2125574587).
    #
    # We KNOW the full submitted size (raw_features.qty_lots, recorded at order
    # time). If the summed closed volume is materially less than that, only part
    # of the position has settled → defer (matched=False) and retry next bar,
    # accumulating the remaining deal(s) until Σvolume ≈ full size. GUARD 1
    # (_ticket_still_open) already catches this when open_orders is FRESH; this
    # backstop covers the case where open_orders is stale (>15s) so GUARD 1
    # passed through. Unknown full size (old/dry-run rows) → skip the check.
    _VOL_EPS = 1e-6
    full_lots = 0.0
    try:
        full_lots = float((trade.raw_features or {}).get("qty_lots") or 0.0)
    except (TypeError, ValueError):
        full_lots = 0.0
    closed_lots = float(deal.get("volume") or 0.0)
    if full_lots > _VOL_EPS and closed_lots + _VOL_EPS < full_lots:
        log.warning(
            "[RECONCILER] ticket=%s only %.4f/%.4f lots closed at broker "
            "(deals=%s) — partial not fully settled, defer + retry",
            ticket, closed_lots, full_lots, deal.get("_deal_count", 1),
        )
        # Persist broker_ticket so a later sweep re-finds it; do NOT lock.
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
