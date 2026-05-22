"""
Real-time price stream via OANDA v20 streaming API.
Monitors open positions tick-by-tick for break-even triggers.
No polling — instant detection.
"""
import json
import threading
import time
from datetime import datetime, timezone

import httpx

from backend.config import OANDA_TOKEN, OANDA_ACCOUNT, OANDA_URL
from backend.db import execute
from backend.execution.oanda_executor import modify_stop_loss

STREAM_URL = OANDA_URL.replace("api-fxpractice", "stream-fxpractice")
HEADERS = {"Authorization": f"Bearer {OANDA_TOKEN}"}

_stream_thread = None
_running = False
_latest_price = {"bid": 0.0, "ask": 0.0, "time": ""}


def get_latest_price() -> dict:
    """Get the most recent streamed price (no API call needed)."""
    return _latest_price.copy()


def _on_tick(bid: float, ask: float, tick_time: str):
    """Called on every price tick — check break-even for open Alpha-Sweep trades."""
    global _latest_price
    _latest_price = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "time": tick_time}

    # Check break-even for open Alpha-Sweep trades
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE strategy='alpha_sweep' AND exit_time IS NULL AND oanda_trade_id IS NOT NULL",
        fetch=True
    )

    if not open_trades:
        return

    for trade in open_trades:
        entry = float(trade["entry_price"])
        tp = float(trade["tp_price"]) if trade["tp_price"] else 0
        sl = float(trade["sl_price"])
        side = trade["side"]

        if tp <= 0:
            continue

        if side == "LONG":
            if tp <= entry:
                continue
            if sl >= entry:
                continue
            target_50 = entry + (tp - entry) * 0.5
            if bid >= target_50:
                new_sl = entry + 0.30
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_be(trade["trade_ref"], new_sl, sl, bid)
                    print(f"  [STREAM] LONG break-even: SL {sl:.2f} → {new_sl:.2f} (bid={bid:.2f})")
                else:
                    _log_be_failed(trade["trade_ref"], new_sl, sl, result.get("error", "Unknown"))
        else:  # SHORT
            if tp >= entry:
                continue
            if sl <= entry:
                continue
            target_50 = entry - (entry - tp) * 0.5
            if ask <= target_50:
                new_sl = entry - 0.30
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_be(trade["trade_ref"], new_sl, sl, ask)
                    print(f"  [STREAM] SHORT break-even: SL {sl:.2f} → {new_sl:.2f} (ask={ask:.2f})")
                else:
                    _log_be_failed(trade["trade_ref"], new_sl, sl, result.get("error", "Unknown"))


def _log_be(trade_ref: str, new_sl: float, old_sl: float, trigger_price: float):
    """Log break-even event to journal."""
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, "alpha_sweep", "BREAK_EVEN", new_sl,
         json.dumps({"old_sl": old_sl, "trigger_price": trigger_price, "source": "stream"}))
    )


def _log_be_failed(trade_ref: str, attempted_sl: float, old_sl: float, error: str):
    """Log break-even failure to journal."""
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, "alpha_sweep", "BREAK_EVEN_FAILED", None,
         json.dumps({"old_sl": old_sl, "attempted_sl": attempted_sl, "error": error, "source": "stream"}))
    )


def _log_stream_event(event_type: str, context: dict):
    """Log stream connect/disconnect to journal."""
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        ("SYSTEM", "alpha_sweep", event_type, None, json.dumps(context))
    )


def _stream_loop():
    """Main streaming loop — reconnects on failure."""
    global _running
    url = f"{STREAM_URL}/accounts/{OANDA_ACCOUNT}/pricing/stream?instruments=XAU_USD"

    while _running:
        try:
            with httpx.stream("GET", url, headers=HEADERS, timeout=None) as resp:
                if resp.status_code != 200:
                    print(f"  [STREAM] Error {resp.status_code}, retrying in 5s...")
                    _log_stream_event("STREAM_ERROR", {"status": resp.status_code, "action": "reconnecting"})
                    time.sleep(5)
                    continue

                print(f"  [STREAM] Connected — receiving live XAU/USD ticks")
                _log_stream_event("STREAM_CONNECTED", {"instrument": "XAU_USD"})
                for line in resp.iter_lines():
                    if not _running:
                        break
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") == "PRICE":
                            bid = float(data["bids"][0]["price"])
                            ask = float(data["asks"][0]["price"])
                            _on_tick(bid, ask, data.get("time", ""))
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            if _running:
                print(f"  [STREAM] Disconnected: {e}. Reconnecting in 3s...")
                _log_stream_event("STREAM_DISCONNECTED", {"error": str(e), "action": "reconnecting"})
                time.sleep(3)
        except Exception as e:
            if _running:
                print(f"  [STREAM] Unexpected error: {e}. Reconnecting in 5s...")
                _log_stream_event("STREAM_DISCONNECTED", {"error": str(e), "action": "reconnecting"})
                time.sleep(5)


def start_stream():
    """Start the price streaming thread."""
    global _stream_thread, _running
    if _running:
        return
    _running = True
    _stream_thread = threading.Thread(target=_stream_loop, daemon=True, name="oanda-price-stream")
    _stream_thread.start()
    print("Price stream started (real-time tick-by-tick)")


def stop_stream():
    """Stop the price streaming thread."""
    global _running
    _running = False
    print("Price stream stopped")
