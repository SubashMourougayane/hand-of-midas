"""GET /api/runs — list recent runs + detail."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text, case
from sqlalchemy.orm import Session

from bt_engine.db.models import BtRun, BtTrade
from bt_engine.data.broker_state import parse_open_positions

from ..deps import get_session
from ..models import RunSummary

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _mt5_open_tickets() -> set[str] | None:
    """MT5 = source of truth for OPEN positions. Set of open tickets, or None if
    the open_orders.json is missing/corrupt (unknown → callers keep DB view, never
    treat as 'all closed'). Shared parser guarantees a bad read is never 'empty'."""
    import json
    from ..ws.price_stream import OPEN_ORDERS_FILE
    try:
        if not OPEN_ORDERS_FILE.is_file():
            return None
        raw = json.loads(OPEN_ORDERS_FILE.read_text())
    except Exception:
        return None
    return {p.ticket for p in parse_open_positions(raw)}


def _run_to_summary(r: BtRun) -> RunSummary:
    return RunSummary(
        run_id=r.run_id,
        run_ref=r.ref,
        mode=r.mode,
        strategy_id=r.strategy_id,
        symbol=r.symbol,
        timeframe=r.timeframe,
        start_ts=r.start_ts,
        end_ts=r.end_ts,
        git_sha=r.git_sha,
    )


@router.get("", response_model=list[RunSummary])
def list_runs(
    limit: int = 50,
    mode: str | None = None,
    s: Session = Depends(get_session),
) -> list[RunSummary]:
    q = select(BtRun).order_by(BtRun.start_ts.desc()).limit(limit)
    if mode:
        q = q.where(BtRun.mode == mode)
    rows = s.execute(q).scalars().all()
    return [_run_to_summary(r) for r in rows]


@router.get("/{run_id}", response_model=dict)
def run_detail(run_id: UUID, s: Session = Depends(get_session)) -> dict:
    r = s.get(BtRun, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="run not found")
    trades_q = select(
        func.count(BtTrade.trade_id).label("n_trades"),
        func.sum(BtTrade.net_r).label("net_r_sum"),
        func.avg(BtTrade.net_r).label("net_r_avg"),
        func.sum(case((BtTrade.net_r > 0, 1), else_=0)).label("wins"),
        func.sum(case((BtTrade.net_r < 0, 1), else_=0)).label("losses"),
        func.count(BtTrade.exit_timestamp).label("closed"),
    ).where(BtTrade.run_id == run_id)
    agg = s.execute(trades_q).one()
    return {
        "run": _run_to_summary(r).model_dump(mode="json"),
        "trades": {
            "n_total": int(agg.n_trades or 0),
            "n_closed": int(agg.closed or 0),
            "n_open": int((agg.n_trades or 0) - (agg.closed or 0)),
            "net_r_sum": float(agg.net_r_sum) if agg.net_r_sum is not None else None,
            "net_r_avg": float(agg.net_r_avg) if agg.net_r_avg is not None else None,
            "wins": int(agg.wins or 0),
            "losses": int(agg.losses or 0),
        },
    }


@router.get("/{run_id}/trades", response_model=dict)
def run_trades(
    run_id: UUID,
    status: str | None = None,  # "open" | "closed" | None
    page: int = 1,
    page_size: int = 100,
    s: Session = Depends(get_session),
) -> dict:
    q = select(BtTrade).where(BtTrade.run_id == run_id)
    if status == "open":
        q = q.where(BtTrade.exit_timestamp.is_(None))
    elif status == "closed":
        q = q.where(BtTrade.exit_timestamp.is_not(None))
    total = s.execute(
        select(func.count(BtTrade.trade_id)).where(BtTrade.run_id == run_id)
    ).scalar_one()
    q = q.order_by(BtTrade.entry_timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = s.execute(q).scalars().all()
    mt5_open = _mt5_open_tickets()  # MT5 truth for open/closed status
    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "items": [_trade_to_dict(t, mt5_open=mt5_open) for t in rows],
    }


def _is_overnight(t: BtTrade) -> bool | None:
    """Overnight = trade held across a UTC calendar-day boundary.

    None if not yet closed. Overnight trades ride to the far extension TP;
    same-day trades mostly resolve at SL (fast retracement failures).
    """
    if t.entry_timestamp is None or t.exit_timestamp is None:
        return None
    return t.entry_timestamp.date() != t.exit_timestamp.date()


def _trade_to_dict(t: BtTrade, *, mt5_open: set[str] | None = None) -> dict:
    # MT5 truth for open/closed. broker_open is:
    #   True  → broker STILL holds this ticket (row is genuinely open, even if a
    #           stale DB row marked it SUPERSEDED/closed).
    #   False → broker no longer holds it (closed at broker).
    #   None  → unknown (MT5 unreadable, or row has no broker_ticket) → trust DB.
    broker_open: bool | None = None
    if mt5_open is not None:
        tkt = (t.broker_ticket or "").strip()
        if tkt:
            broker_open = tkt in mt5_open
    return {
        "trade_id": str(t.trade_id),
        "trade_ref": t.trade_ref,
        "run_id": str(t.run_id),
        "symbol": t.symbol,
        "broker_open": broker_open,
        "direction": t.direction,
        "side": int(t.side),
        "overnight": _is_overnight(t),
        "entry_timestamp": t.entry_timestamp.isoformat() if t.entry_timestamp else None,
        "entry_price": float(t.entry_price) if t.entry_price is not None else None,
        "stop_price": float(t.stop_price) if t.stop_price is not None else None,
        "take_profit_price": float(t.take_profit_price) if t.take_profit_price is not None else None,
        "risk_units": float(t.risk_units) if t.risk_units is not None else None,
        "exit_timestamp": t.exit_timestamp.isoformat() if t.exit_timestamp else None,
        "exit_price": float(t.exit_price) if t.exit_price is not None else None,
        "exit_reason": t.exit_reason,
        "bars_held": int(t.bars_held) if t.bars_held is not None else None,
        "net_r": float(t.net_r) if t.net_r is not None else None,
        "gross_r": float(t.gross_r) if t.gross_r is not None else None,
        "cost_r": float(t.cost_r) if t.cost_r is not None else None,
        "leg": t.leg,
        "regime": t.regime,
        "partial_taken": t.partial_taken,
        "partial_r": float(t.partial_r) if t.partial_r is not None else None,
        # Broker reconciliation (live-only; NULL on BT trades)
        "broker_ticket": t.broker_ticket,
        "broker_gross_usd": float(t.broker_gross_usd) if t.broker_gross_usd is not None else None,
        "broker_commission_usd": float(t.broker_commission_usd) if t.broker_commission_usd is not None else None,
        "broker_swap_usd": float(t.broker_swap_usd) if t.broker_swap_usd is not None else None,
        "broker_net_usd": float(t.broker_net_usd) if t.broker_net_usd is not None else None,
        "broker_exit_price": float(t.broker_exit_price) if t.broker_exit_price is not None else None,
        "broker_exit_reason": t.broker_exit_reason,
        "broker_close_ts": t.broker_close_ts.isoformat() if t.broker_close_ts else None,
        "broker_reconciled_at": t.broker_reconciled_at.isoformat() if t.broker_reconciled_at else None,
        "raw_features": t.raw_features,
    }
