"""Unit tests for CLI live subcommand parsing + strategies listing."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.order import Order
from bt_engine.core.signal import StepResult
from bt_engine.core.state import StrategyState
from bt_engine.data.dwx_bridge import DwxBridge
from bt_engine.runner.live import (
    DryRunBroker,
    LiveSafetyBroker,
    LiveSafetyConfig,
    _infer_server_utc_offset_hours,
    run_live,
)
from bt_engine.runner.cli import build_parser
from bt_engine.strategies import registry


def test_parser_live_command_defaults() -> None:
    p = build_parser()
    ns = p.parse_args(["live"])
    assert ns.cmd == "live"
    assert ns.strategy == "fib_v2_xau_ensemble"  # Phase 4 default change
    assert ns.symbol == "XAUUSD.ecn"
    assert ns.timeframe == "M5"  # Phase 4 default change
    assert ns.dry_run is False


def test_parser_live_dry_run_flag() -> None:
    p = build_parser()
    ns = p.parse_args(["live", "--dry-run", "--max-ticks", "3", "--max-wait", "60"])
    assert ns.dry_run is True
    assert ns.max_ticks == 3
    assert ns.max_wait == 60


def test_parser_strategies_command() -> None:
    p = build_parser()
    ns = p.parse_args(["strategies"])
    assert ns.cmd == "strategies"


def test_dry_run_broker_fills_at_current_bar_close() -> None:
    broker = DryRunBroker()
    bar = Bar("X", "M1", pd.Timestamp("2026-06-29T00:00:00Z"), 100.0, 101.0, 99.0, 100.75, 1.0)
    order = Order(
        symbol="X", side=1, qty=1.0,
        intended_entry_bar=pd.Timestamp("2026-06-29T00:01:00Z"),
        stop_price=99.0, take_profit=103.0, risk_units=2.0,
        tag="dry", bracket_kind="1R",
    )
    broker.set_current_bar(bar)
    broker.submit_order(order)
    fill = list(broker.fills())[0]
    assert fill.price == 100.75
    assert fill.fill_timestamp == bar.timestamp


def test_dry_run_broker_reads_bridge_positions(tmp_path: Path) -> None:
    (tmp_path / "open_orders.json").write_text(
        json.dumps(
            {
                "123": {
                    "ticket": "123",
                    "symbol": "XAUUSD.ecn",
                    "type": "BUY",
                    "volume": 0.01,
                    "open_price": 100.0,
                    "sl": 90.0,
                    "tp": 120.0,
                    "comment": "restart-test",
                }
            }
        )
    )
    broker = DryRunBroker(DwxBridge(dwx_dir=tmp_path))
    positions = broker.positions()
    assert len(positions) == 1
    assert positions[0]["ticket"] == "123"


class _OneShotState(StrategyState):
    issued: bool = False


class _OneShotStrategy:
    strategy_id = "test_live_one_shot"
    config = {}

    def initial_state(self):
        return _OneShotState()

    def on_bar(self, state, bar, history):
        if state.issued:
            return StepResult(state=state)
        state.issued = True
        order = Order(
            symbol=bar.symbol,
            side=1,
            qty=1.0,
            intended_entry_bar=bar.timestamp + pd.Timedelta(minutes=1),
            stop_price=bar.close - 1.0,
            take_profit=bar.close + 1.0,
            risk_units=1.0,
            tag="one-shot",
            bracket_kind="1R",
            trade_id=uuid.uuid4(),
        )
        return StepResult(state=state, new_orders=(order,))


def _write_live_files(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "account_info.json").write_text(json.dumps({"balance": 5000, "equity": 5000, "profit": 0}))
    (path / "open_orders.json").write_text(json.dumps({}))
    (path / "market_data.json").write_text(json.dumps({"XAUUSD.ecn": {"bid": 100.0, "ask": 100.1, "spread": 0.1}}))
    bars = [
        {
            "time": "2020.01.01 00:00:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "spread": 1,
        }
    ]
    (path / "bars_XAUUSD_ecn_M1.json").write_text(json.dumps(bars))


class _FakeLiveBroker:
    def __init__(self):
        self.submitted = None

    def submit_order(self, order: Order) -> str:
        self.submitted = order
        return "ticket-1"

    def cancel(self, order_id: str) -> None:
        pass

    def modify(self, ticket: str, *, sl: float, tp: float = 0.0) -> None:
        pass

    def close_all(self) -> None:
        pass

    def last_response(self):
        return {"success": True}

    def fills(self):
        return iter(())

    def positions(self):
        return []


def _live_order(qty: float = 1.0) -> Order:
    return Order(
        symbol="XAUUSD.ecn",
        side=1,
        qty=qty,
        intended_entry_bar=pd.Timestamp("2026-06-29T00:00:00Z"),
        stop_price=90.0,
        take_profit=110.0,
        risk_units=10.0,
        tag="safety-test",
        bracket_kind="1R",
    )


def test_live_safety_caps_order_to_max_lot(tmp_path: Path) -> None:
    _write_live_files(tmp_path)
    (tmp_path / "account_info.json").write_text(
        json.dumps({"balance": 5000, "equity": 5000, "profit": 0, "server": "JustMarkets-Demo2"})
    )
    fake = _FakeLiveBroker()
    broker = LiveSafetyBroker(
        fake,  # type: ignore[arg-type]
        DwxBridge(dwx_dir=tmp_path),
        LiveSafetyConfig(max_lot=0.01, kill_switch_path=tmp_path / "LIVE_DISABLED"),
    )
    broker.submit_order(_live_order(qty=1.0))
    assert fake.submitted.qty == 0.01
    assert broker.last_submitted_order.qty == 0.01


def test_live_safety_rejects_non_demo_account(tmp_path: Path) -> None:
    _write_live_files(tmp_path)
    (tmp_path / "account_info.json").write_text(
        json.dumps({"balance": 5000, "equity": 5000, "profit": 0, "server": "RealServer"})
    )
    broker = LiveSafetyBroker(
        _FakeLiveBroker(),  # type: ignore[arg-type]
        DwxBridge(dwx_dir=tmp_path),
        LiveSafetyConfig(kill_switch_path=tmp_path / "LIVE_DISABLED"),
    )
    with pytest.raises(RuntimeError, match="not demo-like"):
        broker.submit_order(_live_order())


def test_live_safety_rejects_existing_position(tmp_path: Path) -> None:
    _write_live_files(tmp_path)
    (tmp_path / "account_info.json").write_text(
        json.dumps({"balance": 5000, "equity": 5000, "profit": 0, "server": "JustMarkets-Demo2"})
    )
    (tmp_path / "open_orders.json").write_text(json.dumps({"123": {"symbol": "XAUUSD.ecn"}}))
    broker = LiveSafetyBroker(
        _FakeLiveBroker(),  # type: ignore[arg-type]
        DwxBridge(dwx_dir=tmp_path),
        LiveSafetyConfig(max_open_positions=1, kill_switch_path=tmp_path / "LIVE_DISABLED"),
    )
    with pytest.raises(RuntimeError, match="open positions"):
        broker.submit_order(_live_order())


def test_infers_mt5_server_utc_offset(tmp_path: Path, monkeypatch) -> None:
    _write_live_files(tmp_path)
    (tmp_path / "market_data.json").write_text(
        json.dumps({"XAUUSD.ecn": {"bid": 100.0, "ask": 100.1, "spread": 0.1, "time": "2026.06.29 10:39:23"}})
    )

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 29, 7, 39, 25, tzinfo=timezone.utc)

    monkeypatch.setattr("bt_engine.runner.live.datetime", _FrozenDateTime)
    assert _infer_server_utc_offset_hours(DwxBridge(dwx_dir=tmp_path), "XAUUSD.ecn") == 3


def test_run_live_max_ticks_uses_engine_execution_path(tmp_path: Path, db_engine, monkeypatch) -> None:
    name = f"test_live_one_shot_{uuid.uuid4().hex}"
    registry.register(name, lambda **kwargs: _OneShotStrategy())
    _write_live_files(tmp_path)
    monkeypatch.setattr("time.time", lambda: datetime.now(timezone.utc).timestamp())
    result = run_live(
        strategy=name,
        symbol="XAUUSD.ecn",
        timeframe="M1",
        max_ticks=1,
        poll_interval_s=0,
        dry_run=True,
        db_url=str(db_engine.url),
        bridge=DwxBridge(dwx_dir=tmp_path),
    )
    assert result.bars_processed == 1
