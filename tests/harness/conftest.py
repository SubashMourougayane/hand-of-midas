"""Shared fixtures for Gold Micro harness tests."""
import sys
import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))


@pytest.fixture(scope="session")
def gold_h1():
    """Load XAU_USD H1 bars (last 30 days for fast tests)."""
    from backend.data.cache import load_candles
    df = load_candles("XAU_USD_H1.csv")
    cutoff = df.index[-1] - pd.Timedelta(days=30)
    return df[df.index >= cutoff]


@pytest.fixture(scope="session")
def gold_m3():
    """Load XAU_USD M3 bars (last 30 days)."""
    from backend.data.cache import load_candles
    df = load_candles("XAU_USD_M3.csv")
    cutoff = df.index[-1] - pd.Timedelta(days=30)
    return df[df.index >= cutoff]


@pytest.fixture(scope="session")
def gold_d():
    """Load XAU_USD Daily bars (full history — small file)."""
    from backend.data.cache import load_candles
    return load_candles("XAU_USD_D.csv")


@pytest.fixture(scope="session")
def daily_bias(gold_d):
    """Build daily bias dict from daily candles (same as production)."""
    bias = {}
    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        prev_range = gold_d["mid_high"].iat[i-1] - gold_d["mid_low"].iat[i-1]
        if prev_range <= 0:
            continue
        body_pct = abs(gold_d["mid_close"].iat[i-1] - gold_d["mid_open"].iat[i-1]) / prev_range
        if body_pct < 0.4:
            bias[d] = "neutral"
        elif gold_d["mid_close"].iat[i-1] > gold_d["mid_open"].iat[i-1]:
            bias[d] = "bullish"
        else:
            bias[d] = "bearish"
    return bias


@pytest.fixture(scope="session")
def gold_7d_h1(gold_h1):
    """Last 7 days of H1 for parity tests."""
    cutoff = gold_h1.index[-1] - pd.Timedelta(days=7)
    return gold_h1[gold_h1.index >= cutoff]


@pytest.fixture(scope="session")
def gold_7d_m3(gold_m3):
    """Last 7 days of M3 for parity tests."""
    cutoff = gold_m3.index[-1] - pd.Timedelta(days=7)
    return gold_m3[gold_m3.index >= cutoff]


@pytest.fixture
def seed_random():
    """Fix random seed for deterministic slippage."""
    np.random.seed(42)
    yield
    np.random.seed(None)


@pytest.fixture
def mock_db():
    """In-memory DB state for execution tests."""
    state = {
        "trades": [],
        "signals": [],
        "journal": [],
        "dd_state": {
            "id": 3,
            "consecutive_losses": 0,
            "pause_counter": 0,
            "equity": 10000.0,
            "peak_equity": 10000.0,
        },
    }

    def mock_execute(sql, params=None, fetch=False):
        sql_lower = sql.strip().lower()
        if "gd_dd_state" in sql_lower and "select" in sql_lower:
            return [state["dd_state"]] if fetch else None
        if "gd_trades" in sql_lower and "exit_time is null" in sql_lower and fetch:
            return [t for t in state["trades"] if t.get("exit_time") is None]
        if "gd_signals" in sql_lower and "order by timestamp desc" in sql_lower and fetch:
            return state["signals"][-1:] if state["signals"] else []
        if "gd_trades" in sql_lower and "count" in sql_lower and fetch:
            today = datetime.now(timezone.utc).date()
            cnt = sum(1 for t in state["trades"]
                     if t.get("entry_time") and t["entry_time"].date() == today)
            return [{"cnt": cnt}]
        if "sum(pnl_usd)" in sql_lower and fetch:
            today_pnl = sum(t.get("pnl_usd", 0) for t in state["trades"]
                          if t.get("exit_time") and t["exit_time"].date() == datetime.now(timezone.utc).date())
            return [{"daily_pnl": today_pnl}]
        if "insert" in sql_lower:
            return None
        if "update" in sql_lower:
            return None
        if fetch:
            return []
        return None

    with patch("backend.db.execute", side_effect=mock_execute):
        yield state


@pytest.fixture
def mock_mt5():
    """Mock MT5/DWX executor functions."""
    mt5_state = {
        "open_orders": {},
        "next_ticket": 2000000,
        "price": {"bid": 4520.0, "ask": 4520.10, "mid": 4520.05, "spread": 0.10,
                  "time": "2026.05.29 12:00:00", "tradeable": True},
        "account": {"balance": 10000.0, "nav": 10000.0, "nav_usd": 10000.0,
                   "unrealized_pl": 0.0, "margin_used": 0.0, "open_trades": 0,
                   "currency": "USD", "gbp_usd_rate": 1.0},
        "commands": [],
    }

    def mock_place_order(instrument, units, sl=None, tp=None, comment=""):
        ticket = mt5_state["next_ticket"]
        mt5_state["next_ticket"] += 1
        fill = mt5_state["price"]["ask"] if units > 0 else mt5_state["price"]["bid"]
        mt5_state["open_orders"][str(ticket)] = {
            "instrument": instrument, "units": units,
            "sl": sl, "tp": tp, "open_price": fill,
        }
        mt5_state["account"]["open_trades"] += 1
        mt5_state["commands"].append(("OPEN", instrument, units, sl, tp))
        return {"success": True, "trade_id": str(ticket), "fill_price": fill,
                "units": abs(units), "time": datetime.now(timezone.utc).isoformat()}

    def mock_modify_sl(trade_id, new_sl):
        if str(trade_id) in mt5_state["open_orders"]:
            mt5_state["open_orders"][str(trade_id)]["sl"] = new_sl
            mt5_state["commands"].append(("MODIFY", trade_id, new_sl))
            return {"success": True}
        return {"success": False, "error": "Trade not found"}

    def mock_close(trade_id):
        tid = str(trade_id)
        if tid in mt5_state["open_orders"]:
            order = mt5_state["open_orders"].pop(tid)
            mt5_state["account"]["open_trades"] -= 1
            fill = mt5_state["price"]["bid"] if order["units"] > 0 else mt5_state["price"]["ask"]
            mt5_state["commands"].append(("CLOSE", trade_id))
            return {"success": True, "close_price": fill,
                    "realized_pl": (fill - order["open_price"]) * order["units"]}
        return {"success": False, "error": "Trade not found"}

    def mock_get_price(instrument="XAU_USD"):
        return dict(mt5_state["price"])

    def mock_get_open():
        trades = []
        for tid, order in mt5_state["open_orders"].items():
            trades.append({"id": tid, "instrument": order["instrument"],
                          "currentUnits": order["units"], "price": order["open_price"],
                          "sl": order["sl"], "tp": order["tp"]})
        return trades

    def mock_get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA"):
        return []

    def mock_get_account():
        return dict(mt5_state["account"])

    def mock_get_details(trade_id):
        return None

    patches = {
        "place_market_order": patch("backend.execution.mt5_executor.place_market_order", side_effect=mock_place_order),
        "modify_stop_loss": patch("backend.execution.mt5_executor.modify_stop_loss", side_effect=mock_modify_sl),
        "close_trade": patch("backend.execution.mt5_executor.close_trade", side_effect=mock_close),
        "get_current_price": patch("backend.execution.mt5_executor.get_current_price", side_effect=mock_get_price),
        "get_open_trades": patch("backend.execution.mt5_executor.get_open_trades", side_effect=mock_get_open),
        "get_candles": patch("backend.execution.mt5_executor.get_candles", side_effect=mock_get_candles),
        "get_account_summary": patch("backend.execution.mt5_executor.get_account_summary", side_effect=mock_get_account),
        "get_trade_details": patch("backend.execution.mt5_executor.get_trade_details", side_effect=mock_get_details),
    }

    started = {k: p.start() for k, p in patches.items()}
    yield mt5_state
    for p in patches.values():
        p.stop()
