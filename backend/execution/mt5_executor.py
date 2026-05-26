"""
MT5 Executor — DWX Bridge (replaces oanda_executor.py for JustMarkets).

Same interface as oanda_executor.py so scheduler/live_engine can swap without changes.
Reads market data from DWX JSON files written by MT5 EA.
Writes command files for order execution.
"""
import json
import os
import time
import re
from datetime import datetime, timezone
from pathlib import Path

# DWX files directory (MT5 Common Files)
DWX_DIR = os.getenv("DWX_DIR", os.path.expanduser(
    "~/Library/Application Support/net.metaquotes.wine.metatrader5/"
    "drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
))

# Symbol mapping: our internal names → JustMarkets MT5 names
SYMBOL_MAP = {
    "XAU_USD": "XAUUSD.ecn",
    "BCO_USD": "BRENT.ecn",
    "EUR_USD": "EURUSD.ecn",
    "XAG_USD": "XAGUSD.ecn",
    "SPX500_USD": "US500.ecn",
}

SYMBOL_MAP_REVERSE = {v: k for k, v in SYMBOL_MAP.items()}

# Our magic number (to distinguish our trades from other EAs)
MAGIC = 200000


def _read_json(filename):
    """Read a JSON file from DWX directory. Returns None if unavailable."""
    path = os.path.join(DWX_DIR, filename)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return None


def _write_command(cmd_string):
    """Write a command file for the EA to execute."""
    cmd_dir = os.path.join(DWX_DIR, "commands")
    os.makedirs(cmd_dir, exist_ok=True)
    filename = f"cmd_{int(time.time() * 1000)}.txt"
    path = os.path.join(cmd_dir, filename)
    with open(path, "w") as f:
        f.write(cmd_string)
    return filename


def _wait_response(timeout=10):
    """Wait for EA to write last_response.json after a command."""
    path = os.path.join(DWX_DIR, "last_response.json")
    start = time.time()
    initial_mtime = os.path.getmtime(path) if os.path.exists(path) else 0

    while time.time() - start < timeout:
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            if mtime > initial_mtime:
                time.sleep(0.05)
                try:
                    with open(path) as f:
                        return json.load(f)
                except:
                    pass
        time.sleep(0.1)
    return None


def _mt5_symbol(instrument):
    """Convert internal instrument name to MT5 symbol."""
    return SYMBOL_MAP.get(instrument, instrument)


def _parse_mt5_time(time_str):
    """Parse MT5 time string '2026.05.26 11:08:21' to datetime."""
    try:
        return datetime.strptime(time_str, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except:
        return datetime.now(timezone.utc)


# =============================================================================
# PUBLIC API — Same interface as oanda_executor.py
# =============================================================================

def get_current_price(instrument="XAU_USD"):
    """Get current bid/ask/mid for instrument."""
    data = _read_json("market_data.json")
    if not data:
        return None

    symbol = _mt5_symbol(instrument)
    if symbol not in data:
        return None

    tick = data[symbol]
    bid = tick["bid"]
    ask = tick["ask"]
    spread = ask - bid

    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "spread": spread,
        "time": tick.get("time", ""),
        "tradeable": True,
    }


def get_account_summary():
    """Get account balance, equity, margin info."""
    data = _read_json("account_info.json")
    if not data:
        return None

    return {
        "balance": data["balance"],
        "nav": data["equity"],
        "nav_usd": data["equity"],
        "unrealized_pl": data["profit"],
        "margin_used": data["margin"],
        "open_trades": len(get_open_trades() or []),
        "currency": data["currency"],
        "gbp_usd_rate": 1.0,
    }


def get_open_trades(instrument=None):
    """Get list of open positions, optionally filtered by instrument."""
    data = _read_json("open_orders.json")
    if not data:
        return []

    trades = []
    for ticket, pos in data.items():
        if pos.get("magic", 0) != MAGIC:
            continue

        if instrument:
            mt5_sym = _mt5_symbol(instrument)
            if pos["symbol"] != mt5_sym:
                continue

        trades.append({
            "id": str(ticket),
            "instrument": SYMBOL_MAP_REVERSE.get(pos["symbol"], pos["symbol"]),
            "currentUnits": pos["volume"] if pos["type"] == "BUY" else -pos["volume"],
            "price": pos["open_price"],
            "unrealizedPL": pos["profit"],
            "sl": pos["sl"] if pos["sl"] > 0 else None,
            "tp": pos["tp"] if pos["tp"] > 0 else None,
            "openTime": pos.get("open_time", ""),
            "side": "BUY" if pos["type"] == "BUY" else "SELL",
        })

    return trades


def get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA"):
    """Get historical candles from DWX bar data files."""
    symbol = _mt5_symbol(instrument)
    safe_symbol = symbol.replace(".", "_")

    tf_map = {"M3": "M3", "H1": "H1", "D": "D1", "H4": "H4"}
    tf = tf_map.get(granularity, granularity)

    filename = f"bars_{safe_symbol}_{tf}.json"
    data = _read_json(filename)
    if not data:
        return []

    bars = data[-count:] if len(data) > count else data

    candles = []
    for bar in bars:
        t = bar["time"]
        o = bar["open"]
        h = bar["high"]
        l = bar["low"]
        c = bar["close"]
        spread_pts = bar.get("spread", 0)

        # MT5 bars are mid prices. Approximate bid/ask from spread.
        # For Gold, spread is in points (e.g., 10 = $0.10)
        half_spread = spread_pts * 0.005 if "XAU" in symbol else spread_pts * 0.00005

        candles.append({
            "timestamp": t.replace(".", "-").replace(" ", "T") + "Z" if "." in t else t,
            "bid_open": o - half_spread,
            "bid_high": h - half_spread,
            "bid_low": l - half_spread,
            "bid_close": c - half_spread,
            "ask_open": o + half_spread,
            "ask_high": h + half_spread,
            "ask_low": l + half_spread,
            "ask_close": c + half_spread,
            "volume": bar.get("volume", 0),
        })

    return candles


def place_market_order(instrument, units, sl=None, tp=None, comment=""):
    """Place a market order via DWX command file.

    Args:
        instrument: Internal name (e.g., "XAU_USD")
        units: Positive for BUY, negative for SELL
        sl: Stop loss price (0 for none)
        tp: Take profit price (0 for none)
        comment: Order comment

    Returns:
        dict with success, fill_price, trade_id, units, time
    """
    symbol = _mt5_symbol(instrument)
    order_type = "BUY" if units > 0 else "SELL"
    volume = abs(units)

    # Convert units to lots (Gold: 1 lot = 100 oz, we use units = oz)
    if "XAU" in symbol:
        lots = volume / 100.0
    elif "BRENT" in symbol or "BCO" in symbol:
        lots = volume / 1000.0
    else:
        lots = volume / 100000.0

    lots = round(max(lots, 0.01), 2)

    price = 0  # market price
    sl_price = sl if sl else 0
    tp_price = tp if tp else 0

    cmd = f"OPEN|{symbol}|{order_type}|{lots}|{price}|{sl_price}|{tp_price}|{comment}"
    _write_command(cmd)

    response = _wait_response(timeout=10)
    if not response:
        return {"success": False, "error": "Timeout waiting for EA response"}

    if response.get("success"):
        return {
            "success": True,
            "fill_price": response.get("price", 0),
            "trade_id": str(response.get("ticket", 0)),
            "units": volume,
            "time": datetime.now(timezone.utc).isoformat(),
        }
    else:
        return {
            "success": False,
            "error": f"retcode={response.get('retcode')}: {response.get('comment', 'Unknown')}",
        }


def modify_stop_loss(trade_id, new_sl, new_tp=None):
    """Modify the stop loss (and optionally TP) of an existing position."""
    tp_price = new_tp if new_tp else 0
    cmd = f"MODIFY|{trade_id}|{new_sl}|{tp_price}"
    _write_command(cmd)

    response = _wait_response(timeout=10)
    if not response:
        return {"success": False, "error": "Timeout"}

    return {
        "success": response.get("success", False),
        "error": response.get("comment", "") if not response.get("success") else None,
    }


def close_trade(trade_id):
    """Close an open position by ticket."""
    cmd = f"CLOSE|{trade_id}"
    _write_command(cmd)

    response = _wait_response(timeout=10)
    if not response:
        return {"success": False, "error": "Timeout"}

    return {
        "success": response.get("success", False),
        "close_price": response.get("close_price", 0),
        "realized_pl": response.get("profit", 0),
        "error": response.get("comment", "") if not response.get("success") else None,
    }


def get_trade_details(trade_id):
    """Get details of a specific trade. Checks open_orders.json."""
    data = _read_json("open_orders.json")
    if not data or str(trade_id) not in data:
        return None

    pos = data[str(trade_id)]
    return {
        "id": str(trade_id),
        "state": "OPEN",
        "instrument": SYMBOL_MAP_REVERSE.get(pos["symbol"], pos["symbol"]),
        "price": pos["open_price"],
        "realizedPL": "0",
        "currentUnits": pos["volume"] if pos["type"] == "BUY" else -pos["volume"],
    }


# =============================================================================
# HEALTH CHECK
# =============================================================================

def _get_gbp_usd_rate():
    """GBP/USD rate — JustMarkets account is USD, so return 1.0."""
    return 1.0


def is_connected():
    """Check if DWX is active (files being updated within last 30s)."""
    path = os.path.join(DWX_DIR, "market_data.json")
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < 30


def get_dwx_status():
    """Full DWX health report."""
    market = _read_json("market_data.json")
    account = _read_json("account_info.json")
    path = os.path.join(DWX_DIR, "market_data.json")
    age = time.time() - os.path.getmtime(path) if os.path.exists(path) else 999

    return {
        "connected": age < 30,
        "data_age_seconds": round(age, 1),
        "symbols_streaming": list(market.keys()) if market else [],
        "account_name": account.get("name") if account else None,
        "account_server": account.get("server") if account else None,
        "dwx_dir": DWX_DIR,
    }
