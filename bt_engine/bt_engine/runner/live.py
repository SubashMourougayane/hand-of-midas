"""run_live — live engine loop against MT5 via DWX bridge.

Wires Mt5LiveBarProvider + LiveClock + DWXBrokerAdapter into run_engine.
Writes bt_runs row with mode='live' + streams trades/journal as bars close.

Dry-run mode: --dry-run skips broker.submit_order (logs only, no real orders).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import sessionmaker

from ..core.bar import Bar
from ..core.clock_live import LiveClock
from ..core.engine import EngineDeps, run_engine
from ..core.ids import make_run_ref, new_run_id
from ..core.order import Fill, OpenTrade, Order
from ..data.dwx_bridge import DwxBridge
from ..data.dwx_live_provider import Mt5LiveBarProvider
from ..db.engine import make_engine
from ..db.models import BtTrade
from ..db.repo import AccountSnapshotRepo, BarWalkRepo, JournalRepo, RunRepo, SignalRepo, TradeRepo
from ..execution.dwx_broker import DWXBrokerAdapter
from .broker_reconciler import (
    reconcile_trade,
    retry_unreconciled_trades,
    _parse_broker_time,
    _to_utc_dt,
)
from .equity_sizer import EquitySizer, EquitySizerConfig
from ..journal.walker import BarWalkJournal
from ..strategies import registry


log = logging.getLogger("bt_engine.live")
DEFAULT_LIVE_KILL_SWITCH = Path(__file__).resolve().parents[3] / "LIVE_DISABLED"


class DryRunBroker:
    """No-op broker for live dry-run: logs orders, returns synthetic fills at bar close."""

    def __init__(self, bridge: DwxBridge | None = None) -> None:
        self.bridge = bridge
        self.submitted: list[Order] = []
        self._next_fill: Fill | None = None
        self._current_bar: Bar | None = None

    def set_current_bar(self, bar: Bar) -> None:
        self._current_bar = bar

    def submit_order(self, order: Order) -> str:
        self.submitted.append(order)
        log.info(
            "[DRY-RUN] order %s %s qty=%s sl=%s tp=%s tag=%s",
            order.symbol, "BUY" if order.side > 0 else "SELL",
            order.qty, order.stop_price, order.take_profit, order.tag,
        )
        price = self._current_bar.close if self._current_bar is not None else order.stop_price
        if price <= 0:
            raise RuntimeError("Dry-run broker has no valid current bar price for fill.")
        fill_ts = self._current_bar.timestamp if self._current_bar is not None else pd.Timestamp(datetime.now(timezone.utc))
        self._next_fill = Fill(
            symbol=order.symbol, side=order.side, qty=order.qty,
            price=price,
            fill_timestamp=fill_ts,
        )
        return f"dryrun-{order.tag}"

    def cancel(self, order_id: str) -> None:
        log.info("[DRY-RUN] cancel %s", order_id)

    def fills(self):
        if self._next_fill is not None:
            yield self._next_fill
            self._next_fill = None

    def positions(self):
        if self.bridge is None:
            return []
        try:
            orders = self.bridge.open_orders()
        except Exception:
            return []
        if not isinstance(orders, dict):
            return []
        return list(orders.values())


@dataclass(frozen=True)
class LiveSafetyConfig:
    require_demo: bool = True
    # max_lot is a HARD SAFETY CEILING against runaway sizer bugs, not a
    # sizing policy. Real sizing is Model B (1.5% × equity / stop / contract).
    # Default 2.0 lets Model B run at any equity up to ~$700k on XAU without
    # tripping — well above any realistic short-term equity growth.
    max_lot: float = 2.0
    # Research validates up to 4 concurrent positions on shared NAV
    # (A LONG + D SHORT hedge + partial-TP overlap). Setting to 1 blocks
    # legitimate D entry once A is open (L99 audit suspect #6).
    max_open_positions: int = 4
    max_spread: float = 0.50
    kill_switch_path: Path = DEFAULT_LIVE_KILL_SWITCH
    # Max acceptable ratio of ACTUAL stop distance (post-fill) vs EXPECTED
    # stop distance (strategy's risk_units). > tolerance => reject the fill
    # by closing the position and emitting ORDER_ENTRY_SLIP_REJECTED.
    # 1.15 = allow 15% risk over-run before rejecting.
    # See L99 audit suspect #1 (2026-07-01) — trade 2116651769 filled at
    # ratio 3.34x, real risk = 3.3x intended.
    max_entry_slip_ratio: float = 1.15


class LiveSafetyBroker:
    """Guardrail wrapper for real DWX execution.

    Optional `sizer` (EquitySizer) replaces order.qty with equity-based lot size
    at order-submit time. Strategy emits placeholder qty=1.0; sizer computes the
    real lot from current equity × risk_pct / (stop_distance × contract_size).
    """

    def __init__(
        self,
        broker: DWXBrokerAdapter,
        bridge: DwxBridge,
        config: LiveSafetyConfig,
        sizer: "EquitySizer | None" = None,
    ) -> None:
        self.broker = broker
        self.bridge = bridge
        self.config = config
        self.sizer = sizer  # optional Model B equity sizer
        self.last_submitted_order: Order | None = None
        # Set when an OPEN slow-acks: the underlying broker's fills() yields
        # nothing (its last_response has success=False), so we synthesise the
        # fill from the recovered broker position and yield it from fills().
        self._recovered_fill: Fill | None = None
        self._recovered_ticket: str | None = None

    def set_current_bar(self, bar: Bar) -> None:
        if hasattr(self.broker, "set_current_bar"):
            self.broker.set_current_bar(bar)  # type: ignore[attr-defined]

    def submit_order(self, order: Order) -> str:
        safe_order = self._safe_order(order)
        self.last_submitted_order = safe_order
        self._recovered_fill = None
        self._recovered_ticket = None
        try:
            return self.broker.submit_order(safe_order)
        except Exception as e:
            # Slow-ack recovery: JustMarkets' EA sometimes fills the OPEN but
            # acks slower than the 5s command timeout. A bare raise here would
            # crash the engine loop AND orphan a live position the DB never
            # records (observed 2026-07-02: ticket 2123464608). Before failing,
            # check whether the broker actually opened a position for this tag.
            import time as _t
            tag = str(safe_order.tag or "")
            for _ in range(6):  # ~3s of polling for the EA to publish the fill
                tk = _find_ticket_by_tag(self.bridge, tag)
                if tk:
                    log.warning(
                        "[SUBMIT] OPEN ack timed out (%s) but broker filled tag=%s "
                        "as ticket=%s — slow-ack recovered", e, tag, tk,
                    )
                    # The underlying broker's fills() will yield nothing (its
                    # last_response failed), so synthesise the fill from the
                    # broker's actual open position — else on_open never fires
                    # and the position is orphaned (no DB row, unmanaged;
                    # observed 2026-07-03: ticket 2126588609).
                    self._recovered_ticket = tk
                    pos = _live_position(self.bridge, tk)
                    if pos is not None:
                        fill_px = _float_or_none(pos.get("open_price")) or safe_order.stop_price
                        fill_qty = _float_or_none(pos.get("volume")) or safe_order.qty
                        self._recovered_fill = Fill(
                            symbol=safe_order.symbol, side=safe_order.side,
                            qty=fill_qty, price=fill_px,
                            fill_timestamp=pd.Timestamp(datetime.now(timezone.utc)),
                        )
                    return tk
                _t.sleep(0.5)
            # Genuinely not opened — re-raise so the engine drops the order.
            # (Engine-level guard below also prevents a crash.)
            log.error("[SUBMIT] OPEN failed and no matching position found: %s", e)
            raise

    def cancel(self, order_id: str) -> None:
        self.broker.cancel(order_id)

    def modify(self, ticket: str, *, sl: float, tp: float = 0.0) -> None:
        self.broker.modify(ticket, sl=sl, tp=tp)

    def close_partial(self, ticket: str, qty: float) -> None:
        self.broker.close_partial(ticket, qty)

    def close_all(self) -> None:
        self.broker.close_all()

    def last_response(self) -> dict | None:
        resp = self.broker.last_response()
        # On slow-ack recovery the underlying response has no ticket; surface
        # the recovered one so the engine can persist broker_ticket.
        if self._recovered_ticket and (not isinstance(resp, dict) or not resp.get("ticket")):
            return {"success": True, "ticket": self._recovered_ticket, "recovered": True}
        return resp

    def fills(self):
        """Yield each fill after validating actual slip vs expected risk.

        If the actual stop distance (|fill.price - order.stop_price|) exceeds
        the configured tolerance vs expected risk_units, we CLOSE the position
        we just opened and yield nothing — the engine treats this as no fill
        and drops the order.

        Rationale: SL is set at absolute price by the strategy. Favorable slip
        on entry pushes the fill AWAY from SL, inflating real stop distance.
        Sizer already computed qty based on expected risk. Real risk =
        qty × contract × actual_stop_distance = can be many multiples of
        intended if slip is large. Rejecting is safer than accepting.
        """
        order = self.last_submitted_order
        yielded_any = False
        for fill in self.broker.fills():
            yielded_any = True
            if order is None:
                yield fill
                continue

            expected = float(order.risk_units)
            actual = abs(float(fill.price) - float(order.stop_price))
            if expected <= 0:
                yield fill
                continue
            ratio = actual / expected
            tol = float(self.config.max_entry_slip_ratio)
            if ratio > tol:
                # Reject by immediately closing the just-opened position.
                ticket = None
                resp = self.broker.last_response() or {}
                if isinstance(resp, dict):
                    ticket = resp.get("ticket")
                log.error(
                    "[SLIP-REJECT] fill=%.5f stop=%.5f expected_risk=%.4f actual_risk=%.4f "
                    "ratio=%.2fx tol=%.2fx ticket=%s — closing position",
                    fill.price, order.stop_price, expected, actual, ratio, tol, ticket,
                )
                if ticket is not None:
                    try:
                        self.broker.cancel(str(ticket))
                    except Exception as e:
                        log.error("[SLIP-REJECT] close failed for ticket=%s: %s", ticket, e)
                # Do not yield — engine sees "no fill" and drops the order.
                continue
            # Accept.
            log.info(
                "[SLIP-OK] fill=%.5f stop=%.5f actual_risk=%.4f expected=%.4f ratio=%.2fx",
                fill.price, order.stop_price, actual, expected, ratio,
            )
            yield fill
        # Slow-ack recovery: underlying broker yielded nothing (its OPEN command
        # errored) but the position IS live at the broker. Yield the synthesised
        # fill so the engine creates + persists the trade. Skip slip-reject — the
        # position already exists; the on_bar reconciler manages it from here.
        if not yielded_any and self._recovered_fill is not None:
            log.warning(
                "[SLIP-SKIP] yielding recovered slow-ack fill ticket=%s (position "
                "already open at broker; not slip-checked)", self._recovered_ticket,
            )
            yield self._recovered_fill
            self._recovered_fill = None

    def positions(self):
        return self.broker.positions()

    def _safe_order(self, order: Order) -> Order:
        _assert_live_safety(self.bridge, order.symbol, self.config)

        # ─── Equity sizer (if configured): replace placeholder qty=1.0 with equity-based lot ───
        # Causality: sizer reads current equity (closed-trade pnl only) + order's
        # stop_distance (from current bar's open). NO future peek.
        target_qty = float(order.qty)
        if self.sizer is not None:
            stop_distance = abs(float(order.stop_price) - float(order.intended_entry_bar.value if hasattr(order.intended_entry_bar, "value") else 0))
            # Use risk_units (price-units stop distance) instead — already computed in strategy
            stop_distance = float(order.risk_units)
            ts = order.intended_entry_bar.to_pydatetime() if hasattr(order.intended_entry_bar, "to_pydatetime") else order.intended_entry_bar
            sized_qty = self.sizer.size_order(
                symbol=order.symbol, stop_distance=stop_distance, ts=ts,
            )
            if sized_qty <= 0:
                raise RuntimeError(
                    f"Sizer rejected order: lot=0 (equity=${self.sizer.equity():.2f}, "
                    f"stop=${stop_distance:.4f}, symbol={order.symbol})"
                )
            log.info(
                "[SIZER] order.qty %.4f -> %.4f (equity=$%.2f stop=$%.4f)",
                target_qty, sized_qty, self.sizer.equity(), stop_distance,
            )
            target_qty = sized_qty

        # ─── max_lot cap (hard safety) ───
        safe_qty = min(target_qty, self.config.max_lot)
        if safe_qty <= 0:
            raise RuntimeError("Live safety rejected order: max_lot must be positive")
        if safe_qty != order.qty:
            log.warning(
                "[LIVE-SAFETY] Adjusting order qty %.4f -> %.4f for %s tag=%s",
                order.qty,
                safe_qty,
                order.symbol,
                order.tag,
            )
            return replace(order, qty=safe_qty)
        return order


@dataclass
class LiveResult:
    run_id: str
    run_ref: str
    bars_processed: int
    closed_trades: int


def run_live(
    *,
    strategy: str,
    symbol: str,
    timeframe: str,
    max_ticks: int | None = None,
    poll_interval_s: float = 1.0,
    dry_run: bool = False,
    db_url: str | None = None,
    bridge: DwxBridge | None = None,
    strategy_kwargs: dict[str, Any] | None = None,
    live_safety: LiveSafetyConfig | None = None,
    max_wait_s: float | None = None,
    equity_sizer: EquitySizer | None = None,
) -> LiveResult:
    log.info("Starting live run strategy=%s symbol=%s tf=%s dry_run=%s", strategy, symbol, timeframe, dry_run)
    bridge = bridge or DwxBridge()
    if not bridge.is_alive():
        raise RuntimeError("DWX bridge not alive (account_info.json stale or missing)")
    live_safety = live_safety or LiveSafetyConfig()
    if not dry_run:
        _assert_live_safety(bridge, symbol, live_safety)
        log.info(
            "[LIVE-SAFETY] demo_required=%s max_lot=%.4f max_open_positions=%s max_spread=%.4f kill_switch=%s",
            live_safety.require_demo,
            live_safety.max_lot,
            live_safety.max_open_positions,
            live_safety.max_spread,
            live_safety.kill_switch_path,
        )

    server_utc_offset_hours = _infer_server_utc_offset_hours(bridge, symbol)
    log.info("[DWX] inferred server_utc_offset_hours=%s for %s", server_utc_offset_hours, symbol)
    provider = Mt5LiveBarProvider(
        bridge,
        symbol=symbol,
        timeframe=timeframe,
        server_utc_offset_hours=server_utc_offset_hours,
    )
    live_start_ts = None
    if not dry_run:
        live_start_ts = provider.latest_closed_timestamp()
        if live_start_ts is not None:
            provider.mark_yielded_through(live_start_ts)
            log.info("[LIVE-START] Skipping already-closed DWX backlog through %s", live_start_ts)
    # For smoke testing, cap per-tick wait so the bounded loop returns even when
    # broker has not produced a new closed bar yet.
    per_tick_max = None if max_ticks is None else (5.0 if max_wait_s is None else max_wait_s)
    clock = LiveClock(provider, poll_interval_s=poll_interval_s, max_wait_s=per_tick_max)

    strat_kwargs = dict(strategy_kwargs or {})
    strat_kwargs.setdefault("symbol", symbol)
    if live_start_ts is not None:
        strat_kwargs.setdefault("ignore_events_before", live_start_ts)
    strat = registry.get(strategy, **strat_kwargs)
    if hasattr(strat, "validate_for_live"):
        strat.validate_for_live(timeframe=timeframe)  # type: ignore[attr-defined]

    # ── Warmup pivot tracker / regime / swing from historical bars ──
    # Without this, the strategy starts cold: PivotTracker(lb=N) needs 2N+1
    # bars before its first emit, last_H/L stay None, no setups can spawn.
    # We replay the broker's last N bars THROUGH on_bar, then DISCARD the
    # resulting StepResult (no orders propagate, no events persist, no fills).
    # All that survives is the strategy's internal state.
    #
    # Causality: the bars we replay are STRICTLY BEFORE live_start_ts. Any
    # signal_passed they'd generate would queue a "pending entry" on the
    # state, but we ALSO clear pending_entries after warmup so live trading
    # only fires on signals generated by NEW bars yielded post-launch.
    warmup_state = None
    if not dry_run and live_start_ts is not None:
        try:
            hist = provider.history_up_to(live_start_ts)
            # Cap warmup to last 200 bars (more than enough for lb=5 pivot + D1 regime)
            warmup_bars = hist.tail(200).reset_index(drop=True) if len(hist) > 200 else hist
            if len(warmup_bars) > 0:
                log.info(
                    "[WARMUP] replaying %d historical M15 bars through strategy (%s → %s) "
                    "to seed pivot tracker / regime / prev-bar cache",
                    len(warmup_bars),
                    warmup_bars["timestamp"].iloc[0],
                    warmup_bars["timestamp"].iloc[-1],
                )
                state = strat.initial_state()
                from ..core.bar import Bar as _Bar
                events_emitted = 0
                for i in range(len(warmup_bars)):
                    row = warmup_bars.iloc[i]
                    bar = _Bar(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=row["timestamp"],
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0)),
                    )
                    # Use all-prior-bars-as-history slice for the strategy's
                    # internal history-window lookups (regime, swing).
                    history_slice = warmup_bars.iloc[: i + 1]
                    step = strat.on_bar(state, bar, history_slice)
                    state = step.state
                    events_emitted += len(step.new_events)
                # Clear any pending entries that the warmup queued — those
                # signals belong to past bars, not the upcoming live bar.
                if hasattr(state, "pending_entries"):
                    state.pending_entries = []
                warmup_state = state
                log.info(
                    "[WARMUP] done. emitted %d events (DISCARDED — not persisted). "
                    "state ready: pivots seeded, last_H=%s last_L=%s prev_close=%s",
                    events_emitted,
                    getattr(state, "last_H", None),
                    getattr(state, "last_L", None),
                    getattr(state, "prev_close", None),
                )
                # Patch initial_state so the engine uses our warmed state.
                # Single-threaded process — safe.
                _seeded_state = warmup_state
                strat.initial_state = lambda: _seeded_state  # type: ignore[method-assign]
        except Exception as e:
            log.warning("[WARMUP] failed: %s (continuing with cold state)", e)

    # broker: real DWX or dry-run
    if dry_run:
        broker = DryRunBroker(bridge)
    else:
        broker = LiveSafetyBroker(DWXBrokerAdapter(bridge), bridge, live_safety, sizer=equity_sizer)

    # DB run record
    engine_db = make_engine(db_url) if db_url else make_engine()
    Session = sessionmaker(bind=engine_db, expire_on_commit=False)
    s = Session()
    run_id = new_run_id()
    run_ref = f"{make_run_ref(strategy.upper(), 'live', seq=1)}-{run_id.hex[:8]}"
    try:
        # A force-killed prior runner (NSSM restart) never closed its run, which
        # would inflate the dashboard's live-strategy count. End any orphaned
        # open live runs for THIS strategy before opening the fresh one.
        _stale = RunRepo(s).close_stale_live_runs(strategy, datetime.now(timezone.utc))
        if _stale:
            log.info("[RUN] closed %d stale open live run(s) for %s on startup", _stale, strategy)
        RunRepo(s).create(
            run_id=run_id,
            ref=run_ref,
            mode="live",
            strategy_id=strategy,
            strategy_config={
                "symbol": symbol,
                "timeframe": timeframe,
                "dry_run": dry_run,
                "server_utc_offset_hours": server_utc_offset_hours,
                "live_safety": {
                    "require_demo": live_safety.require_demo,
                    "max_lot": live_safety.max_lot,
                    "max_open_positions": live_safety.max_open_positions,
                    "max_spread": live_safety.max_spread,
                    "kill_switch_path": str(live_safety.kill_switch_path),
                } if not dry_run else None,
            },
            symbol=symbol,
            timeframe=timeframe,
            start_ts=datetime.now(timezone.utc),
            data_provider="dwx-live",
        )
        s.commit()
        log.info(
            "[RUN] created run_id=%s run_ref=%s strategy=%s symbol=%s timeframe=%s dry_run=%s",
            run_id,
            run_ref,
            strategy,
            symbol,
            timeframe,
            dry_run,
        )
    finally:
        s.close()

    live_session = Session()
    trade_repo = TradeRepo(live_session)
    journal_repo = JournalRepo(live_session)
    signal_repo = SignalRepo(live_session)
    account_repo = AccountSnapshotRepo(live_session)
    walk_journal = BarWalkJournal(BarWalkRepo(live_session), journal_repo)
    closed: list = []

    def on_open(tr: OpenTrade) -> None:
        broker_ticket = None
        if hasattr(broker, "last_response"):
            resp = broker.last_response()
            if isinstance(resp, dict):
                broker_ticket = resp.get("ticket")
        log.info(
            "[ENTRY_FILL] trade_id=%s broker_ticket=%s symbol=%s side=%s qty=%.4f price=%.5f sl=%.5f tp=%s tag=%s",
            tr.trade_id,
            broker_ticket,
            tr.fill.symbol,
            tr.fill.side,
            tr.fill.qty,
            tr.entry_price,
            tr.stop_price,
            tr.take_profit,
            tr.order.tag,
        )
        trade_repo.upsert_open(_bt_trade_from_open(tr, run_id=run_id, strategy_id=strategy, timeframe=timeframe))
        # Adopted position (deterministic uuid5 id) may leave the ORIGINAL live
        # entry row (random id) open on a now-ended run — orphaning it from the
        # active-run dashboard. Close any other still-open row for the same
        # broker ticket so exactly ONE open row survives on the current run.
        ext = tr.order.extra or {}
        tkt = ext.get("broker_ticket") or broker_ticket
        if tkt:
            n = trade_repo.supersede_stale_open_ticket(str(tkt), tr.trade_id, run_id)
            if n:
                log.info("[ADOPT] superseded %d stale open row(s) for ticket %s", n, tkt)
        journal_repo.insert(
            trade_id=tr.trade_id,
            run_id=run_id,
            ts=_to_dt(tr.entry_timestamp),
            event_type="ENTRY_FILL",
            detail={
                "symbol": tr.fill.symbol,
                "side": tr.fill.side,
                "qty": tr.fill.qty,
                "price": tr.fill.price,
                "tag": tr.order.tag,
                "extra": tr.order.extra,
            },
        )
        walk_journal.open_walk(
            trade_id=tr.trade_id,
            run_id=run_id,
            side=tr.side,
            entry_price=tr.entry_price,
            stop_price=tr.stop_price,
            take_profit=tr.take_profit,
            risk_units=tr.risk_units,
        )
        live_session.commit()

    def on_close(tr: OpenTrade, oc):
        closed.append((tr, oc))
        log.info(
            "[EXIT_%s] trade_id=%s exit_ts=%s exit_price=%.5f bars_held=%s gross_r=%.6f",
            oc.reason,
            tr.trade_id,
            oc.exit_timestamp,
            oc.exit_price,
            oc.bars_held,
            oc.bracket_1r_outcome,
        )
        # ─── C1 FIX: walker TIMEOUT has NO server-side equivalent. SL/TP are hard
        # server-side levels (sent on OPEN) so those exits self-close at the broker.
        # But a TIMEOUT (max-hold cap) is a bot-only decision — without this, the DB
        # marks the trade closed while the real MT5 position keeps running unmanaged.
        # Send a REAL close and verify (slow-ack safe). Never route SL/SL_BE/TP here.
        if oc.reason == "TIMEOUT" and not dry_run and tr.broker_ticket:
            ok = _close_live_position_verified(broker, bridge, str(tr.broker_ticket))
            if ok:
                log.info("[TIMEOUT_CLOSE] ticket=%s closed at broker on max-hold exit", tr.broker_ticket)
            else:
                log.error(
                    "[TIMEOUT_CLOSE] FAILED to confirm broker close for ticket=%s — "
                    "position may still be OPEN at broker; reconcile will retry",
                    tr.broker_ticket,
                )
                journal_repo.insert(
                    trade_id=tr.trade_id, run_id=run_id,
                    ts=_to_dt(oc.exit_timestamp),
                    event_type="TIMEOUT_CLOSE_FAILED",
                    detail={"broker_ticket": str(tr.broker_ticket), "reason": oc.reason},
                )
        gross_r = oc.bracket_1r_outcome
        cost_r = float(tr.order.extra.get("cost_r", 0.0))
        # Equity sizer: update with realized $ pnl on every closed trade.
        # Causality: only fires on TRADE EXIT (closed) — no open-trade peek.
        if equity_sizer is not None:
            net_r = gross_r - cost_r
            # Translate R to $: lot × contract × stop_distance × net_r
            from .equity_sizer import CONTRACT_SIZE as _CS
            contract = _CS.get(tr.order.symbol, 100.0)
            dollar_pnl = float(tr.fill.qty) * contract * float(tr.risk_units) * float(net_r)
            equity_sizer.on_trade_closed(
                pnl_dollars=dollar_pnl,
                close_ts=_to_dt(oc.exit_timestamp),
            )
        partial_fill_ts = (
            _to_dt(tr.partial_fill_timestamp)
            if tr.partial_fill_timestamp is not None else None
        )
        trade_repo.close(
            tr.trade_id,
            exit_timestamp=_to_dt(oc.exit_timestamp),
            exit_price=oc.exit_price,
            exit_reason=oc.reason,
            bars_held=oc.bars_held,
            bracket_1r_outcome=oc.bracket_1r_outcome,
            cost_r=cost_r,
            gross_r=gross_r,
            net_r=gross_r - cost_r,
            partial_taken=bool(tr.partial_taken),
            partial_r=float(tr.partial_filled_r),
            partial_fill_price=(
                float(tr.partial_fill_price)
                if tr.partial_fill_price is not None else None
            ),
            partial_fill_ts=partial_fill_ts,
        )
        journal_repo.insert(
            trade_id=tr.trade_id,
            run_id=run_id,
            ts=_to_dt(oc.exit_timestamp),
            event_type=oc.event_type,
            detail={**oc.detail, "exit_price": oc.exit_price, "reason": oc.reason},
        )
        walk_journal.close_walk(tr.trade_id)
        live_session.commit()

        # Reconcile broker deal history (best-effort; retries later on bar_close sweep).
        if tr.broker_ticket:
            try:
                reconcile_trade(
                    bridge=bridge, session=live_session,
                    trade_id=tr.trade_id, ticket=tr.broker_ticket,
                    server_utc_offset_hours=server_utc_offset_hours,
                    max_retries=8, backoff_s=0.25,
                )
            except Exception as e:
                log.warning("[RECONCILER] on_close reconcile failed: %s", e)

    def on_event(ev) -> None:
        detail = dict(ev.detail)
        zone_id = detail.get("zone_id")
        # bar_ts populated by gate-decision events; fall back to entry/bar fields.
        event_ts = (
            detail.get("bar_ts")
            or detail.get("entry_timestamp")
            or detail.get("bar_timestamp")
        )
        is_gate = ev.type.startswith("GATE_")
        log_tag = "[GATE]" if is_gate else "[SIGNAL]"
        log.info(
            "%s type=%s leg=%s ts=%s reason=%s",
            log_tag, ev.type,
            detail.get("leg"), event_ts, detail.get("reason"),
        ) if is_gate else log.info(
            "[SIGNAL] type=%s zone_id=%s ts=%s detail=%s",
            ev.type, zone_id, event_ts, detail,
        )
        signal_repo.insert(
            run_id=run_id,
            ts=_to_dt(pd.Timestamp(event_ts)) if event_ts is not None else datetime.now(timezone.utc),
            status=ev.type,
            zone_id=int(zone_id) if zone_id is not None else None,
            reason=detail.get("reason") if is_gate else None,
            detail={"trade_or_zone_id": ev.trade_or_zone_id, **detail},
        )
        live_session.commit()

    def on_partial_tp(tr: OpenTrade, bar: Bar) -> None:
        """Walker fired partial-TP → tell broker to close half + move SL to BE.

        Called AFTER walker mutated `tr` (partial_taken=True, stop_price=entry).
        Broker must reflect: (a) reduced volume, (b) new SL at entry.

        If either broker call fails, we log + persist a warning event but DO
        NOT re-raise — the walker already updated internal state, so failing
        here would leave BT/live divergent AND crash the whole engine loop.
        Operator gets a persisted event + log line for manual reconciliation.
        """
        ticket = tr.broker_ticket
        if ticket is None:
            log.warning(
                "[PARTIAL_TP] no broker_ticket on trade %s — skip live modify (dry-run?)",
                tr.trade_id,
            )
            return
        pct = float((tr.order.extra or {}).get("partial_tp_pct", 0.5))
        close_qty = float(tr.fill.qty) * pct
        new_sl = float(tr.entry_price)
        tp = float(tr.take_profit) if tr.take_profit is not None else 0.0
        log.info(
            "[PARTIAL_TP] trade_id=%s ticket=%s close_qty=%.4f new_sl=%.5f",
            tr.trade_id, ticket, close_qty, new_sl,
        )

        # Snapshot the broker volume BEFORE the close — used to distinguish a
        # genuinely-failed CLOSE_PARTIAL from one the DWX EA executed but acked
        # slower than the command timeout (observed on JustMarkets: the 5s
        # send_command wait raises TimeoutError while the deal still fills).
        pre = _live_position(bridge, ticket)
        pre_vol = _float_or_none(pre.get("volume")) if pre else None

        # 1) partial close FIRST so remaining position is correct at MODIFY.
        try:
            broker.close_partial(ticket, close_qty)
        except Exception as e:
            # Do NOT trust the raised error — verify against the broker's own
            # open_orders before giving up. Slow-ack ≠ reject. RETRY the read
            # with backoff: the EA rewrites open_orders.json slower than the 5s
            # command wait, so an immediate single read sees stale pre-volume.
            if _close_partial_succeeded_retry(bridge, ticket, pre_vol, close_qty):
                post = _live_position(bridge, ticket)
                if post is None:
                    log.warning(
                        "[PARTIAL_TP] close_partial raised (%s) but ticket %s no longer "
                        "open — treating as closed", e, ticket,
                    )
                    _persist_partial_tp_event(
                        "PARTIAL_TP_CLOSE_RECOVERED", tr, bar, ticket, close_qty, new_sl,
                        f"slow-ack; position gone. cause={e}",
                    )
                    return
                log.warning(
                    "[PARTIAL_TP] close_partial raised (%s) but broker volume dropped "
                    "(pre=%s) — slow-ack, continuing to SL→BE", e, pre_vol,
                )
            else:
                log.error("[PARTIAL_TP] close_partial failed ticket=%s: %s", ticket, e)
                _persist_partial_tp_event(
                    "PARTIAL_TP_CLOSE_FAILED", tr, bar, ticket, close_qty, new_sl, str(e),
                )
                return
        # 2) modify SL → BE on remainder. Retry on failure; on terminal failure
        #    SAFE-CLOSE the remaining position rather than leave it exposed with
        #    the original (further-away) SL.
        modify_ok = False
        last_err: str | None = None
        for attempt in range(3):
            try:
                broker.modify(ticket, sl=new_sl, tp=tp)
                modify_ok = True
                break
            except Exception as e:
                last_err = str(e)
                # Slow-ack guard: the MODIFY may have applied even though the
                # command wait timed out. Confirm against broker's live SL.
                if _sl_at_be(_live_position(bridge, ticket), new_sl):
                    log.warning(
                        "[PARTIAL_TP] modify_sl raised (%s) but live SL already at "
                        "BE — slow-ack, treating as applied", e,
                    )
                    modify_ok = True
                    break
                log.warning(
                    "[PARTIAL_TP] modify_sl attempt %d/3 failed ticket=%s: %s",
                    attempt + 1, ticket, e,
                )
                time_backoff = 0.3 * (attempt + 1)
                time.sleep(time_backoff)

        if not modify_ok:
            log.error(
                "[PARTIAL_TP] modify_sl exhausted retries ticket=%s: %s — SAFE CLOSING remainder",
                ticket, last_err,
            )
            _persist_partial_tp_event(
                "PARTIAL_TP_MODIFY_FAILED", tr, bar, ticket, close_qty, new_sl, last_err,
            )
            try:
                broker.cancel(ticket)
                _persist_partial_tp_event(
                    "PARTIAL_TP_SAFE_CLOSED", tr, bar, ticket, close_qty, new_sl,
                    error=f"modify retries exhausted; safe-closed remainder. cause={last_err}",
                )
            except Exception as e:
                log.critical(
                    "[PARTIAL_TP] safe-close ALSO failed ticket=%s: %s — MANUAL INTERVENTION REQUIRED",
                    ticket, e,
                )
                _persist_partial_tp_event(
                    "PARTIAL_TP_ORPHANED", tr, bar, ticket, close_qty, new_sl,
                    error=f"safe-close failed: {e}; original cause: {last_err}",
                )
            return

        _persist_partial_tp_event(
            "PARTIAL_TP_APPLIED", tr, bar, ticket, close_qty, new_sl, None,
        )

    def _persist_partial_tp_event(
        event_type: str,
        tr: OpenTrade,
        bar: Bar,
        ticket: str,
        close_qty: float,
        new_sl: float,
        error: str | None,
    ) -> None:
        detail: dict[str, Any] = {
            "trade_id": str(tr.trade_id),
            "broker_ticket": ticket,
            "close_qty": close_qty,
            "new_sl": new_sl,
            "entry_price": tr.entry_price,
            "partial_r": tr.partial_filled_r,
            "bar_ts": str(bar.timestamp),
        }
        if error:
            detail["error"] = error
        journal_repo.insert(
            trade_id=tr.trade_id,
            run_id=run_id,
            ts=_to_dt(bar.timestamp),
            event_type=event_type,
            detail=detail,
        )
        live_session.commit()

    def on_bar_close(bar: Bar, open_trades: list[OpenTrade]) -> None:
        account = _safe_account_info(bridge)
        spread = None
        try:
            market = bridge.market_data()
            quote = market.get(symbol) if isinstance(market, dict) else None
            if isinstance(quote, dict):
                spread = quote.get("spread")
        except Exception:
            spread = None
        log.info(
            "[BAR] ts=%s close=%.5f open_trades=%d balance=%s equity=%s spread=%s",
            bar.timestamp,
            bar.close,
            len(open_trades),
            account.get("balance"),
            account.get("equity"),
            spread,
        )
        account_repo.insert(
            run_id=run_id,
            ts=_to_dt(bar.timestamp),
            balance=_float_or_none(account.get("balance")),
            equity=_float_or_none(account.get("equity")),
            open_pnl=_float_or_none(account.get("profit")),
            open_position=len(open_trades),
        )
        live_session.commit()

        # Cheap sweep for previously-unreconciled trades.
        try:
            retry_unreconciled_trades(
                bridge=bridge, session=live_session, run_id=run_id,
                server_utc_offset_hours=server_utc_offset_hours,
                limit=10,
            )
        except Exception as e:
            log.debug("[RECONCILER] sweep failed: %s", e)

    # Wrap the engine: cap by max_ticks if provided
    deps = EngineDeps(
        clock=clock,
        data_provider=provider,
        strategy=strat,
        execution=None,  # live mode uses broker
        broker=broker,
        journal=walk_journal,
        on_trade_open=on_open,
        on_trade_close=on_close,
        on_strategy_event=on_event,
        on_partial_tp=on_partial_tp,
        on_bar_close=on_bar_close,
        # H1 FIX: each bar, detect broker-side closes (intrabar SL/TP wick the
        # close-based walker misses) BEFORE walking → no ghost management.
        on_broker_closed_check=(
            None if dry_run else (lambda ots, bar: _broker_closed_outcomes(ots, bar, bridge))
        ),
        initial_open_trades=_open_trades_from_positions(
            broker.positions(), symbol=symbol, strategy_id=strategy,
            server_utc_offset_hours=server_utc_offset_hours,
            risk_lookup=trade_repo.risk_units_for_ticket,
        ),
    )

    bars_processed = 0
    try:
        result = run_engine(run_id=run_id, deps=deps, mode="live", max_bars=max_ticks)
        bars_processed = result.bars_processed
    finally:
        live_session.close()

    # close run
    s = Session()
    try:
        RunRepo(s).close(run_id, end_ts=datetime.now(timezone.utc))
        s.commit()
        log.info("[RUN] closed run_id=%s bars_processed=%s closed_trades=%s", run_id, bars_processed, len(closed))
    finally:
        s.close()

    return LiveResult(
        run_id=str(run_id), run_ref=run_ref,
        bars_processed=bars_processed, closed_trades=len(closed),
    )


def _assert_live_safety(bridge: DwxBridge, symbol: str, config: LiveSafetyConfig) -> None:
    if config.kill_switch_path.is_file():
        raise RuntimeError(f"Live safety rejected order: kill switch exists at {config.kill_switch_path}")
    account = bridge.account_info()
    server = str(account.get("server", ""))
    if config.require_demo and "demo" not in server.lower():
        raise RuntimeError(f"Live safety rejected order: account server is not demo-like ({server})")
    positions = bridge.open_orders()
    if isinstance(positions, dict) and len(positions) >= config.max_open_positions:
        raise RuntimeError(
            f"Live safety rejected order: open positions {len(positions)} >= max {config.max_open_positions}"
        )
    market = bridge.market_data()
    symbol_quote = market.get(symbol) if isinstance(market, dict) else None
    if not isinstance(symbol_quote, dict):
        raise RuntimeError(f"Live safety rejected order: no market quote for {symbol}")
    spread = float(symbol_quote.get("spread", 0.0))
    if spread <= 0 or spread > config.max_spread:
        raise RuntimeError(
            f"Live safety rejected order: spread {spread} outside allowed range 0..{config.max_spread}"
        )


def _infer_server_utc_offset_hours(bridge: DwxBridge, symbol: str) -> int:
    try:
        market = bridge.market_data()
        quote = market.get(symbol) if isinstance(market, dict) else None
        raw_time = quote.get("time") if isinstance(quote, dict) else None
        if not raw_time:
            return 0
        server_as_utc = pd.Timestamp(raw_time, tz="UTC")
        now_utc = pd.Timestamp(datetime.now(timezone.utc))
        delta_hours = (server_as_utc - now_utc).total_seconds() / 3600.0
        rounded = int(round(delta_hours))
        if -12 <= rounded <= 14 and abs(delta_hours - rounded) <= 0.25:
            return rounded
    except Exception:
        return 0
    return 0

def _to_dt(ts) -> datetime:
    """Convert any timestamp-like to tz-aware datetime in UTC.

    Defensive: live broker fills may carry naive timestamps. We assume naive ==
    UTC (live engine drives UTC bars). This prevents silent tz drift in DB writes.
    """
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.to_pydatetime()


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_account_info(bridge: DwxBridge) -> dict[str, Any]:
    try:
        info = bridge.account_info()
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _live_position(bridge: DwxBridge, ticket: str) -> dict[str, Any] | None:
    """Broker's own view of `ticket` from open_orders.json, or None if not open."""
    try:
        orders = bridge.open_orders()
    except Exception:
        return None
    if not isinstance(orders, dict):
        return None
    pos = orders.get(str(ticket))
    return pos if isinstance(pos, dict) else None


def _find_ticket_by_tag(bridge: DwxBridge, tag: str) -> str | None:
    """Recover a just-opened position's ticket by matching the order tag against
    each open position's `comment` (the EA stores the tag as comment, often
    truncated). Used when OPEN's ack timed out but the EA still filled — a
    slow-ack that would otherwise be mistaken for a failed submit.

    Matches on shared prefix (broker truncates long comments), min 8 chars.
    """
    if not tag:
        return None
    try:
        orders = bridge.open_orders()
    except Exception:
        return None
    inner = orders.get("orders", orders) if isinstance(orders, dict) else None
    if not isinstance(inner, dict):
        return None
    best: str | None = None
    best_len = 0
    for ticket, v in inner.items():
        if not isinstance(v, dict):
            continue
        comment = str(v.get("comment") or "")
        if not comment:
            continue
        # Longest common prefix between tag and comment.
        n = 0
        for a, b in zip(tag, comment):
            if a != b:
                break
            n += 1
        if n >= 8 and n > best_len:
            best_len = n
            best = str(ticket)
    return best


def _close_partial_succeeded(
    pre_vol: float | None, post_pos: dict[str, Any] | None, close_qty: float
) -> bool:
    """Decide whether a CLOSE_PARTIAL actually took effect on the broker,
    IGNORING whether the command ack timed out.

    JustMarkets' DWX EA sometimes fills the partial but acks slower than the
    5s command wait → close_partial() raises TimeoutError even though the deal
    went through. Ground-truth beats ack timing:
      * position gone entirely  → the close (over-)filled → success
      * volume dropped by ≥ half the requested close_qty → success (partial fill)
      * otherwise → genuine failure
    """
    if post_pos is None:
        return True  # position closed out — nothing left, treat as done
    post_vol = _float_or_none(post_pos.get("volume"))
    if pre_vol is None or post_vol is None:
        return False  # can't verify → don't claim success
    return (pre_vol - post_vol) >= close_qty * 0.5


def _close_partial_succeeded_retry(
    bridge: DwxBridge, ticket: str, pre_vol: float | None, close_qty: float,
    *, attempts: int = 4, backoff_s: float = 0.5,
) -> bool:
    """Poll the broker's open_orders a few times before judging a slow-ack
    CLOSE_PARTIAL. The EA fills the partial but can ack — AND rewrite
    open_orders.json — slower than the 5s command wait. A single immediate read
    then sees stale pre-volume and wrongly reports failure (observed 2026-07-03:
    ticket 2125574587 partial filled at broker but runner marked the trade
    SL_BE-closed, orphaning the 0.06 remainder). Re-read with backoff so the
    reduced volume / gone position has time to appear.
    """
    for i in range(attempts):
        post = _live_position(bridge, ticket)
        if _close_partial_succeeded(pre_vol, post, close_qty):
            return True
        if i < attempts - 1:
            time.sleep(backoff_s * (i + 1))
    return False


def _broker_closed_outcomes(
    open_trades, bar, bridge: DwxBridge,
) -> list:
    """H1 detector: return [(trade, BracketOutcome)] for trades the BROKER has
    already closed (server-side SL/TP wick the close-based walker missed).

    MT5 = source of truth for open/closed. If a trade's ticket is no longer in a
    FRESH open_orders.json, the broker closed it → we book it so the engine's
    walker stops managing a ghost. Real P&L is filled in later by reconcile_trade
    (called from on_close); here we mark reason=BROKER_CLOSED with the bar close as
    a provisional exit price. Conservative: only act when open_orders is readable
    (a failed read returns nothing → no spurious closes)."""
    from ..core.bracket import BracketOutcome
    from ..data.broker_state import open_tickets_from_bridge
    # Shared MT5-truth reader. None = read FAILED (unknown) → do nothing (never
    # treat a bad read as 'all closed'). A real empty set = genuinely no positions.
    live_tickets = open_tickets_from_bridge(bridge)
    if live_tickets is None:
        return []
    out = []
    for tr in open_trades:
        tkt = getattr(tr, "broker_ticket", None)
        if not tkt:
            continue  # no ticket to check (never adopted/opened) — leave to walker
        if str(tkt) not in live_tickets:
            # Broker no longer holds it → closed intrabar. Provisional outcome;
            # reconcile_trade (on_close) overwrites with the broker's real fill/P&L.
            side = tr.side
            prov_r = ((bar.close - tr.entry_price) * side / tr.risk_units
                      if tr.risk_units > 0 else 0.0)
            out.append((tr, BracketOutcome(
                exit_timestamp=bar.timestamp,
                exit_price=bar.close,
                reason="BROKER_CLOSED",
                bars_held=tr.bars_held,
                bracket_1r_outcome=prov_r,
                event_type="EXIT_BROKER_CLOSED",
                detail={"broker_ticket": str(tkt), "note": "detected gone from open_orders; real P&L via reconcile"},
            )))
    return out


def _close_live_position_verified(
    broker, bridge: DwxBridge, ticket: str,
    *, attempts: int = 4, backoff_s: float = 0.5,
) -> bool:
    """Send a full CLOSE to the broker for `ticket` and VERIFY it left open_orders.

    Used for walker-decided exits that have NO server-side equivalent — i.e.
    TIMEOUT (the strategy's max-hold cap). SL/TP are already server-side and must
    NOT be routed here. Reuses the slow-ack discipline: DWX may ack (and rewrite
    open_orders.json) slower than the 5s command wait, so a raised error is not a
    reject — re-read the broker with backoff before judging.

    Returns True if the position is confirmed gone at the broker, else False.
    """
    if not ticket:
        return False
    # If it's already not open (e.g. SL/TP hit intrabar), treat as closed.
    if _live_position(bridge, ticket) is None:
        return True
    try:
        broker.cancel(str(ticket))  # DWX: CLOSE|<ticket>
    except Exception as e:
        log.warning("[TIMEOUT_CLOSE] cancel raised for ticket=%s (%s) — verifying", ticket, e)
    for i in range(attempts):
        if _live_position(bridge, ticket) is None:
            return True
        if i < attempts - 1:
            time.sleep(backoff_s * (i + 1))
    return _live_position(bridge, ticket) is None


def _sl_at_be(post_pos: dict[str, Any] | None, new_sl: float, tol: float = 0.01) -> bool:
    """True if the broker's live SL already sits at breakeven (within `tol`).

    Used to recover from a MODIFY whose ack timed out but which the EA applied.
    """
    if post_pos is None:
        return False
    live_sl = _float_or_none(post_pos.get("sl"))
    if live_sl is None:
        return False
    return abs(live_sl - new_sl) <= tol


def _bt_trade_from_open(tr: OpenTrade, *, run_id: uuid.UUID, strategy_id: str, timeframe: str) -> BtTrade:
    extra = dict(tr.order.extra or {})
    direction = str(extra.get("direction") or ("long" if tr.side > 0 else "short"))
    # Record the FULL submitted lot size in raw_features so the reconciler's F7
    # volume-completeness guard can tell a partial-close from a full close. The
    # strategy's order.extra doesn't carry qty (sized at submit); the actual fill
    # qty does. Re-adopted trades already inject qty_lots explicitly upstream.
    if extra.get("qty_lots") is None and tr.fill is not None and tr.fill.qty:
        extra["qty_lots"] = float(tr.fill.qty)
    return BtTrade(
        trade_id=tr.trade_id,
        trade_ref=f"{strategy_id.upper()}-{tr.trade_id.hex[:12]}",
        run_id=run_id,
        strategy_id=strategy_id,
        symbol=tr.order.symbol,
        timeframe=timeframe,
        zone_id=int(extra["zone_id"]) if extra.get("zone_id") is not None else None,
        zone_tf=extra.get("zone_tf"),
        spec_name=extra.get("spec_name"),
        direction=direction,
        side=tr.side,
        upper=_float_or_none(extra.get("upper")),
        lower=_float_or_none(extra.get("lower")),
        entry_timestamp=_to_dt(tr.entry_timestamp),
        entry_price=tr.entry_price,
        stop_price=tr.stop_price,
        take_profit_price=tr.take_profit,
        risk_units=tr.risk_units,
        # Fib V2 columns (alembic 0002) — populated from strategy.order.extra
        pivot_lb=int(extra["pivot_lb"]) if extra.get("pivot_lb") is not None else None,
        regime=extra.get("regime"),
        ext_target_pct=_float_or_none(extra.get("ext_target_pct")),
        sl_buffer_pct=_float_or_none(extra.get("sl_buffer_pct")),
        fib_diff=_float_or_none(extra.get("fib_diff")),
        regime_at_entry=extra.get("regime_at_entry"),
        leg=extra.get("leg"),
        # Partial-TP columns (alembic 0003) — strategy config defaults; live walker fills outcome columns at close.
        partial_tp_at_r=_float_or_none(extra.get("partial_tp_at_r")),
        partial_tp_pct=_float_or_none(extra.get("partial_tp_pct")),
        partial_taken=False,
        partial_r=0.0,
        partial_fill_price=None,
        partial_fill_ts=None,
        broker_ticket=(tr.broker_ticket or (str(extra["broker_ticket"]) if extra.get("broker_ticket") else None)),
        raw_features=extra,
    )


def _leg_owns_position(strategy_id: str | None, pos: dict, side: int) -> bool:
    """Only adopt a broker position that belongs to THIS leg.

    A + D run on the same symbol and share one account, so adopt-by-symbol
    alone would make each leg grab the other's positions → double-management
    (conflicting SL-moves / closes). Match on the position comment's leg tag;
    fall back to side (long-leg = BUY, short-leg = SELL) when comment is absent.
    """
    if not strategy_id:
        return True
    sid = strategy_id.lower()
    comment = str(pos.get("comment") or "").lower()
    # Combined leg → owns everything for the symbol (check first: the id
    # contains 'intraday_a' as a substring).
    if "a_plus_d" in sid or "aplusd" in sid:
        return True
    # Prefer explicit leg tag in the comment.
    if "intraday_a" in sid or sid.endswith("_a"):
        if comment:
            return "intraday_a" in comment or "_long" in comment
        return side > 0
    if "intraday_d" in sid or sid.endswith("_d"):
        if comment:
            return "intraday_d" in comment or "_short" in comment
        return side < 0
    # Combined / unknown leg → adopt everything for the symbol.
    return True


def _open_trades_from_positions(
    positions, *, symbol: str, strategy_id: str | None = None,
    server_utc_offset_hours: int = 0,
    risk_lookup: Callable[[str], float | None] | None = None,
) -> list[OpenTrade]:
    out: list[OpenTrade] = []
    for pos in positions:
        try:
            ticket = str(pos.get("ticket") or pos.get("id") or pos.get("position_id") or pos.get("comment") or uuid.uuid4())
            side = 1 if str(pos.get("type", "")).upper() in {"BUY", "0"} else -1
            if not _leg_owns_position(strategy_id, pos, side):
                continue
            qty = float(pos.get("volume", 0.0))
            entry = float(pos.get("open_price", pos.get("price_open", 0.0)))
            sl = float(pos.get("sl", 0.0))
            tp_raw = pos.get("tp", 0.0)
            tp = float(tp_raw) if tp_raw not in (None, "", 0, "0") else None
            # SL==0 (none set) still needs entry>0 + qty>0 to be a real position.
            if qty <= 0 or entry <= 0:
                continue
            risk = abs(entry - sl) if sl > 0 else 0.0
            if risk <= 0:
                # Broker SL trailed to breakeven (SL==entry) or removed → live
                # stop distance is 0. Do NOT drop the position (that strands it
                # unmanaged on restart). Recover the ORIGINAL risk_units from the
                # DB row for this ticket so the trade stays fully managed.
                recovered = risk_lookup(str(ticket)) if risk_lookup else None
                if recovered and recovered > 0:
                    risk = float(recovered)
                    log.info(
                        "[ADOPT] ticket %s SL at/near breakeven (sl=%.5f entry=%.5f); "
                        "recovered original risk_units=%.5f from DB",
                        ticket, sl, entry, risk,
                    )
                else:
                    log.warning(
                        "[ADOPT] ticket %s has no usable stop distance and no DB "
                        "risk to recover; skipping adoption", ticket,
                    )
                    continue
            trade_id = uuid.uuid5(uuid.NAMESPACE_URL, f"gold-digger-live-position:{ticket}")
            now_ts = pd.Timestamp(datetime.now(timezone.utc))
            # Real entry time from the broker's open_time (server-local, UTC+3),
            # so the hold timer reflects the ACTUAL age — not adoption time.
            ts = now_ts
            ot = str(pos.get("open_time") or "")
            parsed = _parse_broker_time(ot)
            if parsed is not None:
                try:
                    utc = _to_utc_dt(parsed, server_utc_offset_hours)
                    if utc is not None:
                        ts = pd.Timestamp(utc)
                except Exception:
                    ts = now_ts
            # Per-leg max hold (M15 bars): A long = 12h = 48, D short = 24h = 96.
            # Applied from adoption FORWARD only (bars_held starts at 0) — we do
            # NOT retroactively force-close a position that's already past its
            # cap at adoption time (avoids surprise market-closes of existing
            # trades on restart). New over-holds will time-exit normally.
            max_hold_bars = 48 if side > 0 else 96
            order = Order(
                symbol=str(pos.get("symbol") or symbol),
                side=side,
                qty=qty,
                intended_entry_bar=ts,
                stop_price=sl,
                take_profit=tp,
                risk_units=risk,
                tag=str(pos.get("comment") or ticket),
                bracket_kind="reconciled_live",
                trade_id=trade_id,
                extra={
                    "broker_ticket": ticket,
                    "reconciled": True,
                    # Leg label so the UI shows Long/Short (not the fallback
                    # literal "Strategy"). Prefer comment tag, else side.
                    "leg": (
                        "intraday_a_long" if side > 0 else "intraday_d_short"
                    ),
                    "qty_lots": qty,
                    "direction": "long" if side > 0 else "short",
                    "max_hold_bars": max_hold_bars,
                },
            )
            fill = Fill(order.symbol, side, qty, entry, ts)
            adopted = OpenTrade(
                trade_id=trade_id,
                order=order,
                fill=fill,
                entry_price=entry,
                entry_timestamp=ts,
                side=side,
                stop_price=sl,
                take_profit=tp,
                risk_units=risk,
                broker_ticket=str(ticket),
            )
            out.append(adopted)
        except (TypeError, ValueError):
            continue
    return out
