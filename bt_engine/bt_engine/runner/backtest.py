"""run_backtest — full engine BT with buffered persistence.

Two entry points:
- `run_backtest_intraday()`: real BT via `run_engine(mode='bt')` — same code
  path as live. Wires BarWalkJournal, gate-event capture, and Model B equity
  sizer optionally. Buffers all writes and bulk-inserts at the end.
- `run_backtest_frozen_ledger()`: legacy sdr001 replay from a CSV ledger.

Both persist bt_runs / bt_trades / bt_journal_events / bt_bar_walk / bt_signals
so the dashboard renders the same shape regardless of BT origin.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import sessionmaker

from ..core.bar import Bar
from ..core.engine import EngineDeps, run_engine
from ..core.order import OpenTrade
from ..core.recorder import TradeRecorder
from ..data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from ..data.oanda_parquet_provider import OandaParquetProvider
from ..db.engine import make_engine
from ..db.models import BtRun
from ..db.repo import RunRepo
from ..core.order import Fill, Order
from ..execution.simulator import BTExecutionModel
from ..journal.walker import BarWalkJournal
from ..strategies import registry
from ..strategies.sdr001.parity_replay import load_ledger, replay_to_db
from ..strategies.sdr001.summary import HeadlineSummary, headline
from .bulk_persist import (
    BulkAccountSnapshotRepo,
    BulkBarWalkRepo,
    BulkJournalRepo,
    BulkSignalRepo,
    BulkTradeStore,
)
from .equity_sizer import CONTRACT_SIZE, EquitySizer, EquitySizerConfig


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


# ── LEGACY: sdr001 frozen-ledger replay ──


@dataclass
class BacktestResult:
    run_id: str
    run_ref: str
    trades_inserted: int
    headline: HeadlineSummary
    trades_csv: Path
    summary_json: Path


def run_backtest_frozen_ledger(
    *,
    strategy: str = "sdr001",
    ledger_path: str | Path = DEFAULT_LEDGER,
    out_dir: str | Path = "bt_engine/output/run01",
    db_url: str | None = None,
) -> BacktestResult:
    if strategy != "sdr001":
        raise NotImplementedError(f"Frozen-ledger replay only supports sdr001; got {strategy}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    engine = make_engine(db_url) if db_url else make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        result = replay_to_db(session, ledger_path=ledger_path)
        session.commit()
    finally:
        session.close()

    recorder = TradeRecorder(out_dir=out, filename=f"{strategy}_trades.csv")
    df = result.trades.copy()
    r_col = "net_1r_after_cost" if "net_1r_after_cost" in df.columns else "net_r"
    if r_col != "net_r":
        df["net_r"] = df[r_col]
    for _, row in df.iterrows():
        recorder.record(row.to_dict())
    trades_csv = recorder.finalize()

    summary = headline(df, r_col=r_col)
    summary_path = out / f"{strategy}_summary.json"
    summary_path.write_text(json.dumps(asdict(summary), indent=2))

    return BacktestResult(
        run_id=str(result.run_id),
        run_ref=result.run_ref,
        trades_inserted=result.trades_inserted,
        headline=summary,
        trades_csv=trades_csv,
        summary_json=summary_path,
    )


# Back-compat alias.
run_backtest = run_backtest_frozen_ledger


# ── NEW: engine-driven intraday BT ──


@dataclass
class IntradayBacktestResult:
    run_id: str
    run_ref: str
    bars_processed: int
    trades_open: int
    trades_closed: int
    signals: int
    bar_walk_rows: int
    net_r: float
    net_usd: float | None


def run_backtest_intraday(
    *,
    strategy: str,
    m5_parquet: str | Path,
    symbol: str = "XAUUSD.ecn",
    timeframe: str = "M15",
    max_bars_held: int | None = None,
    cost_usd: float = 0.65,
    use_equity_sizer: bool = False,
    start_balance: float = 5000.0,
    risk_pct: float = 0.015,
    max_lot: float = 2.0,
    commission_per_lot_usd: float = 6.50,
    spread_usd_per_lot: float = 9.00,
    entry_slip_pips: float = 0.0,
    sl_slip_pips: float = 0.0,
    tp_slip_pips: float = 0.0,
    swap_long_per_lot_per_night: float = 0.0,
    swap_short_per_lot_per_night: float = 0.0,
    max_open_positions: int | None = 4,
    reject_pct: float = 0.0,
    gap_threshold_seconds: float = 0.0,
    gap_extra_slip_pips: float = 0.0,
    partial_tp_fail_pct: float = 0.0,
    db_url: str | None = None,
    run_ref_prefix: str | None = None,
    max_bars: int | None = None,
) -> IntradayBacktestResult:
    """Run an intraday strategy through `run_engine(mode='bt')`.

    Reads an M5 parquet, resamples to the target timeframe, streams every bar
    through the strategy just like live does. Persists everything (trades,
    journal events, gate signals, bar_walk) in bulk at completion.
    """
    m5_path = Path(m5_parquet)
    if not m5_path.exists():
        raise FileNotFoundError(f"M5 parquet not found: {m5_path}")

    if max_bars_held is None:
        # 12h A / 24h D safety-doubled — the walker caps hold, this only rescues stuck trades.
        max_bars_held = 24 * 4 * 2

    strat_config: dict[str, Any] = {
        "cost_usd": cost_usd,
        "timeframe": timeframe,
        "data_source": f"parquet:{m5_path.name}",
        "max_lot": max_lot,
        "commission_per_lot_usd": commission_per_lot_usd,
        "spread_usd_per_lot": spread_usd_per_lot,
        "entry_slip_pips": entry_slip_pips,
        "sl_slip_pips": sl_slip_pips,
        "tp_slip_pips": tp_slip_pips,
        "swap_long_per_lot_per_night": swap_long_per_lot_per_night,
        "swap_short_per_lot_per_night": swap_short_per_lot_per_night,
        "max_open_positions": max_open_positions,
        "reject_pct": reject_pct,
        "gap_threshold_seconds": gap_threshold_seconds,
        "gap_extra_slip_pips": gap_extra_slip_pips,
        "partial_tp_fail_pct": partial_tp_fail_pct,
    }
    if use_equity_sizer:
        strat_config.update(
            equity_sizer={"start_balance": start_balance, "risk_pct": risk_pct},
        )

    def _per_lot_cost(qty: float) -> float:
        """Real broker cost model. Scales linearly with lot.

        Default JustMarkets Raw Spread XAU: $6.50 commission + $9.00 spread per lot.
        For 0.02 lot trade: $0.31. For 2.0 lot: $31. For 5.0 lot: $77.50.
        vs strategy's flat cost_usd (typically $0.65) which is qty-blind — accurate
        at 0.04 lot only. Diverges at high qty (Model B compounding).
        """
        return float(qty) * (commission_per_lot_usd + spread_usd_per_lot)

    class _BTSizingExecution:
        """Wraps BTExecutionModel — sizes order.qty at submit via sizer, then clamps
        to max_lot. Mirrors live's LiveSafetyBroker._safe_order behavior in BT context.

        Without this, order.qty stays at strategy default (1.0), sizer only tracks
        post-hoc equity via _on_close (see live/live.py:sizer.on_trade_closed).
        Result: qty=1.0 in DB, $ pnl compounded but not reflecting real lot growth.

        With this wrapper: sizer computes lot from equity × risk_pct / (contract ×
        stop_distance), clamped to [MIN_LOT, max_lot]. Order.qty replaced. Fill
        happens at bar.open with sized qty.
        """
        def __init__(self, inner: BTExecutionModel, sizer_ref, max_lot_cap: float,
                     reject_pct: float = 0.0):
            self._inner = inner
            self._sizer_ref = sizer_ref
            self._max_lot = max_lot_cap
            self._reject_pct = reject_pct
            self.MIN_LOT = 0.01

        def slippage_bps(self) -> float:
            return self._inner.slippage_bps()

        def _is_rejected(self, order: Order) -> bool:
            """P2c deterministic requote/reject. Hash order identity → stable 0-99
            bucket. Reject if bucket < reject_pct×100. No random module → reproducible.
            """
            if self._reject_pct <= 0:
                return False
            key = f"{order.tag}|{order.intended_entry_bar}"
            bucket = hash(key) % 10000  # 0-9999 for 0.01% granularity
            return bucket < int(self._reject_pct * 10000)

        def simulate_fill(self, order: Order, next_bar):
            # P2c: deterministic reject → return None, engine skips (no trade).
            if self._is_rejected(order):
                return None
            if self._sizer_ref is None:
                # No sizer configured — pass through with lot cap only.
                capped = min(float(order.qty), self._max_lot)
                if capped != float(order.qty):
                    order = _replace_order_qty(order, capped)
                return self._inner.simulate_fill(order, next_bar)

            stop_distance = float(order.risk_units)
            if stop_distance <= 0:
                return self._inner.simulate_fill(order, next_bar)

            ts = order.intended_entry_bar.to_pydatetime() if hasattr(
                order.intended_entry_bar, "to_pydatetime"
            ) else order.intended_entry_bar

            sized_qty = self._sizer_ref.size_order(
                symbol=order.symbol, stop_distance=stop_distance, ts=ts,
            )
            capped_qty = max(self.MIN_LOT, min(sized_qty, self._max_lot))
            new_order = _replace_order_qty(order, capped_qty)
            return self._inner.simulate_fill(new_order, next_bar)

    # Provider setup
    m5 = pd.read_parquet(m5_path)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    frame = resample_m5_to(m5, timeframe)
    provider = MemoryBarProvider(frame, symbol=symbol, timeframe=timeframe)
    clock = MemoryClock(provider)
    strat = registry.get(strategy, symbol=symbol)

    run_id = uuid.uuid4()
    prefix = run_ref_prefix or f"BT-{strategy.upper()}"
    run_ref = f"{prefix}-{run_id.hex[:8]}"

    engine_db = make_engine(db_url) if db_url else make_engine()
    Session = sessionmaker(bind=engine_db, expire_on_commit=False)

    # Create run first (regular repo — one row, low volume).
    with Session() as s:
        RunRepo(s).create(
            run_id=run_id,
            ref=run_ref,
            mode="bt",
            strategy_id=strategy,
            strategy_config=strat_config,
            symbol=symbol,
            timeframe=timeframe,
            start_ts=datetime.now(timezone.utc),
            data_provider=f"parquet:{m5_path.name}",
        )
        s.commit()

    bulk_session = Session()
    trade_store = BulkTradeStore(bulk_session)
    journal_repo = BulkJournalRepo(bulk_session)
    signal_repo = BulkSignalRepo(bulk_session)
    walk_repo = BulkBarWalkRepo(bulk_session)
    account_repo = BulkAccountSnapshotRepo(bulk_session)
    walk_journal = BarWalkJournal(walk_repo, journal_repo)

    sizer = (
        EquitySizer(EquitySizerConfig(start_balance=start_balance, risk_pct=risk_pct))
        if use_equity_sizer
        else None
    )

    def _on_open(tr: OpenTrade) -> None:
        extra = tr.order.extra or {}
        leg_name = extra.get("leg")
        qty = float(tr.fill.qty)
        contract = CONTRACT_SIZE.get(tr.order.symbol, 100.0)

        raw_features = dict(extra)
        if sizer is not None:
            raw_features.setdefault("equity_at_entry", sizer.state.current_equity)
            raw_features.setdefault("qty_lots", qty)

        trade_store.open(
            dict(
                trade_id=tr.trade_id,
                trade_ref=f"BT-{strategy.upper()}-{tr.trade_id.hex[:12]}",
                run_id=run_id,
                strategy_id=strategy,
                symbol=tr.order.symbol,
                timeframe=timeframe,
                direction="long" if tr.side > 0 else "short",
                side=tr.side,
                entry_timestamp=_to_dt(tr.entry_timestamp),
                entry_price=tr.entry_price,
                stop_price=tr.stop_price,
                take_profit_price=tr.take_profit,
                risk_units=tr.risk_units,
                pivot_lb=extra.get("pivot_lb"),
                regime=extra.get("regime"),
                ext_target_pct=extra.get("ext_target_pct"),
                sl_buffer_pct=extra.get("sl_buffer_pct"),
                fib_diff=extra.get("fib_diff"),
                regime_at_entry=extra.get("regime_at_entry"),
                leg=leg_name,
                partial_tp_at_r=extra.get("partial_tp_at_r"),
                partial_tp_pct=extra.get("partial_tp_pct"),
                cost_r=extra.get("cost_r"),
                raw_features=raw_features,
            )
        )
        journal_repo.insert(
            trade_id=tr.trade_id,
            run_id=run_id,
            ts=_to_dt(tr.entry_timestamp),
            event_type="ENTRY_FILL",
            detail={
                "symbol": tr.fill.symbol,
                "side": tr.fill.side,
                "qty": qty,
                "price": tr.fill.price,
                "tag": tr.order.tag,
                "extra": extra,
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

    def _on_close(tr: OpenTrade, oc) -> None:
        gross_r = oc.bracket_1r_outcome
        # ── Real broker cost: per-lot commission+spread scales with qty ──
        # Overrides strategy's flat cost_usd (which is qty-blind and wrong at
        # non-default lot). At qty=0.02 lot: real cost = $0.31 vs strategy $0.65
        # (overstates). At qty=2.0 lot: real cost = $31 vs strategy $0.65 (67× under).
        # Only accurate at qty ~= 0.04 lot.
        qty_lots = float(tr.fill.qty)
        real_cost_usd = _per_lot_cost(qty_lots)
        cost_r_strategy = float((tr.order.extra or {}).get("cost_r") or 0.0)
        # Convert real_cost_usd to R for strategy-level metric parity.
        # R denominator = qty × contract × stop_dist $ per R.
        contract = CONTRACT_SIZE.get(tr.order.symbol, 100.0)
        r_dollar = qty_lots * contract * float(tr.risk_units)
        cost_r_real = real_cost_usd / r_dollar if r_dollar > 0 else 0.0
        # Use real per-lot cost as the authoritative cost.
        cost_r = cost_r_real
        net_r = gross_r - cost_r
        pnl_usd: float | None = None
        if sizer is not None:
            # Real-money pnl: gross_r × R_dollars − real_cost_usd
            pnl_usd = qty_lots * contract * float(tr.risk_units) * gross_r - real_cost_usd
            sizer.on_trade_closed(pnl_dollars=pnl_usd, close_ts=_to_dt(oc.exit_timestamp))

        close_fields: dict[str, Any] = dict(
            exit_timestamp=_to_dt(oc.exit_timestamp),
            exit_price=oc.exit_price,
            exit_reason=oc.reason,
            bars_held=oc.bars_held,
            bracket_1r_outcome=gross_r,
            cost_r=cost_r,
            gross_r=gross_r,
            net_r=net_r,
            partial_taken=bool(tr.partial_taken),
            partial_r=float(tr.partial_filled_r),
            partial_fill_price=(
                float(tr.partial_fill_price) if tr.partial_fill_price is not None else None
            ),
            partial_fill_ts=(
                _to_dt(tr.partial_fill_timestamp)
                if tr.partial_fill_timestamp is not None
                else None
            ),
        )
        trade_store.close(tr.trade_id, close_fields)
        # Backfill pnl_usd into raw_features so combined-replay + dashboard see it.
        if pnl_usd is not None:
            entry = trade_store.by_id.get(tr.trade_id)
            if entry is not None:
                rf = dict(entry.get("raw_features") or {})
                rf["pnl_usd"] = pnl_usd
                rf["broker_cost_usd_est"] = real_cost_usd
                rf["cost_r_strategy_est"] = cost_r_strategy
                rf["cost_r_real"] = cost_r_real
                rf["qty_lots_at_fill"] = qty_lots
                rf["equity_at_close"] = sizer.state.current_equity if sizer is not None else None
                entry["raw_features"] = rf

        journal_repo.insert(
            trade_id=tr.trade_id,
            run_id=run_id,
            ts=_to_dt(oc.exit_timestamp),
            event_type=oc.event_type,
            detail={**(oc.detail or {}), "exit_price": oc.exit_price, "reason": oc.reason},
        )
        walk_journal.close_walk(tr.trade_id)

    def _on_event(ev) -> None:
        detail = dict(ev.detail or {})
        event_ts = (
            detail.get("bar_ts")
            or detail.get("entry_timestamp")
            or detail.get("bar_timestamp")
        )
        try:
            ts_py = (
                pd.Timestamp(event_ts).to_pydatetime()
                if event_ts is not None
                else datetime.now(timezone.utc)
            )
        except Exception:
            ts_py = datetime.now(timezone.utc)
        is_gate = ev.type.startswith("GATE_")
        zone_id = detail.get("zone_id")
        signal_repo.insert(
            run_id=run_id,
            ts=ts_py,
            status=ev.type,
            zone_id=int(zone_id) if zone_id is not None else None,
            reason=detail.get("reason") if is_gate else None,
            detail={"trade_or_zone_id": ev.trade_or_zone_id, **detail},
        )

    def _on_bar_close(bar: Bar, open_trades: list[OpenTrade]) -> None:
        # For BT, an "account snapshot" is either the sizer's current equity or
        # a flat placeholder — keeps the account timeseries alive so the dashboard
        # equity curve renders even for pre-sizer runs.
        equity = sizer.state.current_equity if sizer is not None else None
        if equity is None:
            return  # skip for non-sizer BT runs; keeps the account table lean
        account_repo.insert(
            run_id=run_id,
            ts=_to_dt(bar.timestamp),
            balance=equity,
            equity=equity,
            open_pnl=None,
            open_position=len(open_trades),
        )

    # BT-side execution wrapper: sizer at submit + max_lot clamp (P0.2/P0.3).
    # Mirrors live's LiveSafetyBroker._safe_order without touching live code.
    # Entry slip (P1a) baked into simulator.
    bt_execution = _BTSizingExecution(
        BTExecutionModel(entry_slip_pips=entry_slip_pips), sizer_ref=sizer, max_lot_cap=max_lot,
        reject_pct=reject_pct,
    )
    # P1b overnight swap: side (+1/-1) → USD/lot/night. Negative = cost.
    swap_map: dict[int, float] | None = None
    if abs(swap_long_per_lot_per_night) > 0 or abs(swap_short_per_lot_per_night) > 0:
        swap_map = {
            +1: swap_long_per_lot_per_night,
            -1: swap_short_per_lot_per_night,
        }
    deps = EngineDeps(
        clock=clock,
        data_provider=provider,
        strategy=strat,
        execution=bt_execution,
        broker=None,
        recorder=None,
        journal=walk_journal,
        on_trade_open=_on_open,
        on_trade_close=_on_close,
        on_strategy_event=_on_event,
        on_bar_close=_on_bar_close,
        max_bars_held=max_bars_held,
        sl_slip_pips=sl_slip_pips,
        tp_slip_pips=tp_slip_pips,
        swap_per_lot_per_night=swap_map,
        max_open_positions=max_open_positions,
        gap_threshold_seconds=gap_threshold_seconds,
        gap_extra_slip_pips=gap_extra_slip_pips,
        partial_tp_fail_pct=partial_tp_fail_pct,
    )

    try:
        result = run_engine(run_id=run_id, deps=deps, mode="bt", max_bars=max_bars)
    finally:
        pass  # bulk_session left open for flush below

    # Flush everything.
    signals = signal_repo.flush()
    trades = trade_store.flush()
    walk_rows = walk_repo.flush()
    journal_events = journal_repo.flush()
    account_rows = account_repo.flush()

    with Session() as s:
        RunRepo(s).close(run_id, end_ts=datetime.now(timezone.utc))
        s.commit()
    bulk_session.close()

    # Aggregate headline for return.
    net_r_sum = 0.0
    net_usd_sum: float | None = 0.0 if sizer is not None else None
    for row in trade_store.by_id.values():  # already flushed but dict emptied — re-query
        pass
    # Trades dict cleared post-flush; pull totals from DB to avoid holding refs.
    with Session() as s:
        from sqlalchemy import func, select
        from ..db.models import BtTrade

        totals = s.execute(
            select(
                func.coalesce(func.sum(BtTrade.net_r), 0.0),
            ).where(BtTrade.run_id == run_id)
        ).one()
        net_r_sum = float(totals[0] or 0.0)
    if sizer is not None:
        skimmed = sum(float(s.get("skim_amount", 0.0)) for s in sizer.state.skim_history)
        net_usd_sum = skimmed + (sizer.state.current_equity - start_balance)

    return IntradayBacktestResult(
        run_id=str(run_id),
        run_ref=run_ref,
        bars_processed=result.bars_processed,
        trades_open=trade_store.stats.trades_open,
        trades_closed=trade_store.stats.trades_closed,
        signals=signals,
        bar_walk_rows=walk_rows,
        net_r=net_r_sum,
        net_usd=net_usd_sum,
    )


def _to_dt(ts) -> datetime:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.to_pydatetime()


def _replace_order_qty(order: Order, new_qty: float) -> Order:
    """Return copy of Order with new qty. Order is frozen so we use dataclass replace."""
    from dataclasses import replace as _dc_replace
    return _dc_replace(order, qty=float(new_qty))
