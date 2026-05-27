"""Shared test fixtures for Hand Of Midas test harness."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OIL_BACKEND_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "backend-oil"))

# Order matters: insert in reverse priority order (last insert(0) = highest priority).
# Oil path inserted LAST so it's at position 0 → 'from scanner.live_engine' resolves to Oil's version.
# Gold tests use 'from backend.scanner.live_engine' (fully qualified) which is unambiguous.
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, OIL_BACKEND_PATH)

TEST_DB_URL = os.getenv("TEST_DB_URL", "postgresql://postgres:postgres@localhost:5432/golddigger_test")


@pytest.fixture(autouse=True)
def seed_random():
    import numpy as np
    np.random.seed(42)


@pytest.fixture(autouse=True)
def patch_db_to_test():
    """Route all DB calls to test database."""
    import psycopg2

    def _test_conn():
        return psycopg2.connect(TEST_DB_URL)

    with patch("backend.db.get_conn", side_effect=_test_conn):
        yield


@pytest.fixture
def test_db():
    """Connect to test DB, truncate tables before each test."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("TRUNCATE gd_trades, gd_signals, gd_journal, gd_dd_state RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity) VALUES (1, 0, 0, 5000, 5000) ON CONFLICT (id) DO UPDATE SET consecutive_losses=0, pause_counter=0, equity=5000, peak_equity=5000")
    cur.execute("INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity) VALUES (2, 0, 0, 5000, 5000) ON CONFLICT (id) DO UPDATE SET consecutive_losses=0, pause_counter=0, equity=5000, peak_equity=5000")
    yield conn
    conn.close()


def _make_oanda_mocks(success=True):
    """Create mock functions for all OANDA operations."""
    if success:
        place = MagicMock(return_value={
            "success": True, "trade_id": "12345", "fill_price": 2620.50,
            "units": 100, "time": "2026-05-22T10:00:00Z",
        })
        acct = MagicMock(return_value={
            "balance": 98755.0, "nav": 98755.0, "nav_usd": 132000.0,
            "unrealized_pl": 0.0, "open_trades": 0, "currency": "GBP", "gbp_usd_rate": 1.337,
        })
        close = MagicMock(return_value={
            "success": True, "close_price": 2630.0, "realized_pl": 50.0, "time": "2026-05-22T12:00:00Z",
        })
        modify = MagicMock(return_value={"success": True})
        details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 50.0, "price": 2640.0, "close_time": "2026-05-22T12:00:00Z",
        })
    else:
        place = MagicMock(return_value={"success": False, "error": "MARKET_HALTED"})
        acct = MagicMock(return_value={
            "balance": 98755.0, "nav": 98755.0, "nav_usd": 132000.0, "currency": "GBP", "gbp_usd_rate": 1.337,
        })
        close = MagicMock(return_value={"success": False, "error": "TRADE_NOT_FOUND"})
        modify = MagicMock(return_value={"success": False, "error": "INVALID_STOP_LOSS"})
        details = MagicMock(return_value=None)

    open_trades = MagicMock(return_value=[])
    price = MagicMock(return_value={
        "bid": 2620.0, "ask": 2621.0, "mid": 2620.5, "spread": 1.0, "tradeable": True,
    })
    rate = MagicMock(return_value=1.337)
    candles = MagicMock(return_value=[])

    return {
        "place": place, "account": acct, "open_trades": open_trades,
        "price": price, "close": close, "modify": modify,
        "details": details, "rate": rate, "candles": candles,
    }


@pytest.fixture
def mock_oanda_success(monkeypatch):
    """Mock OANDA that fills orders successfully."""
    import backend.scanner.live_engine as gold_le
    import backend.execution as execution_mod

    mocks = _make_oanda_mocks(success=True)

    monkeypatch.setattr(gold_le, "place_market_order", mocks["place"])
    monkeypatch.setattr(gold_le, "get_account_summary", mocks["account"])
    monkeypatch.setattr(gold_le, "get_open_trades", mocks["open_trades"])
    monkeypatch.setattr(gold_le, "get_current_price", mocks["price"])
    monkeypatch.setattr(gold_le, "close_trade", mocks["close"])
    monkeypatch.setattr(gold_le, "modify_stop_loss", mocks["modify"])
    monkeypatch.setattr(gold_le, "get_trade_details", mocks["details"])
    monkeypatch.setattr(gold_le, "get_candles", mocks["candles"])
    monkeypatch.setattr(gold_le, "_get_gbp_usd_rate", mocks["rate"])
    # Also patch on backend.execution for local re-imports (e.g. max-hold path)
    monkeypatch.setattr(execution_mod, "close_trade", mocks["close"])
    monkeypatch.setattr(execution_mod, "get_trade_details", mocks["details"])

    return mocks


@pytest.fixture
def mock_oanda_failure(monkeypatch):
    """Mock OANDA that returns errors."""
    import backend.scanner.live_engine as gold_le
    import backend.execution as execution_mod

    mocks = _make_oanda_mocks(success=False)

    monkeypatch.setattr(gold_le, "place_market_order", mocks["place"])
    monkeypatch.setattr(gold_le, "get_account_summary", mocks["account"])
    monkeypatch.setattr(gold_le, "get_open_trades", mocks["open_trades"])
    monkeypatch.setattr(gold_le, "get_current_price", mocks["price"])
    monkeypatch.setattr(gold_le, "close_trade", mocks["close"])
    monkeypatch.setattr(gold_le, "modify_stop_loss", mocks["modify"])
    monkeypatch.setattr(gold_le, "get_trade_details", mocks["details"])
    monkeypatch.setattr(gold_le, "get_candles", mocks["candles"])
    monkeypatch.setattr(gold_le, "_get_gbp_usd_rate", mocks["rate"])
    # Also patch on backend.execution for local re-imports
    monkeypatch.setattr(execution_mod, "close_trade", mocks["close"])
    monkeypatch.setattr(execution_mod, "get_trade_details", mocks["details"])

    return mocks


@pytest.fixture
def gold_dd_state(test_db):
    """Helper to set Gold DD state."""
    def _set(consecutive_losses=0, pause_counter=0, equity=5000, peak_equity=5000):
        cur = test_db.cursor()
        cur.execute(
            "UPDATE gd_dd_state SET consecutive_losses=%s, pause_counter=%s, equity=%s, peak_equity=%s WHERE id=1",
            (consecutive_losses, pause_counter, equity, peak_equity)
        )
    return _set


@pytest.fixture
def oil_dd_state(test_db):
    """Helper to set Oil DD state."""
    def _set(consecutive_losses=0, pause_counter=0, equity=5000, peak_equity=5000):
        cur = test_db.cursor()
        cur.execute(
            "UPDATE gd_dd_state SET consecutive_losses=%s, pause_counter=%s, equity=%s, peak_equity=%s WHERE id=2",
            (consecutive_losses, pause_counter, equity, peak_equity)
        )
    return _set


@pytest.fixture
def open_gold_trade(test_db):
    """Insert an open Gold trade into DB."""
    def _create(trade_ref="GD-AL-test1234", strategy="alpha_sweep", side="LONG",
                entry_price=2620.0, sl_price=2610.0, tp_price=2640.0,
                units=100, oanda_trade_id="12345", entry_time=None):
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)
        cur = test_db.cursor()
        cur.execute(
            """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'live', %s)""",
            (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, units/100.0, units, oanda_trade_id)
        )
        return trade_ref
    return _create


@pytest.fixture
def open_oil_trade(test_db):
    """Insert an open Oil trade into DB."""
    def _create(trade_ref="OIL-AS-test1234", strategy="alpha_sweep_oil", side="LONG",
                entry_price=104.50, sl_price=104.00, tp_price=105.50,
                units=500, oanda_trade_id="67890", entry_time=None):
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)
        cur = test_db.cursor()
        cur.execute(
            """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'live', %s)""",
            (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, units/1000.0, units, oanda_trade_id)
        )
        return trade_ref
    return _create


def query_db(conn, sql, params=None):
    """Helper to query test DB."""
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params or ())
    return cur.fetchall()
