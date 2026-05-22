"""Oil price stream — BCO_USD tick-by-tick for break-even detection."""
import json
import threading
import time
from datetime import datetime, timezone
import httpx
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import OANDA_TOKEN, OANDA_ACCOUNT, OANDA_URL
from backend.execution.oanda_executor import modify_stop_loss
from backend.db import execute

STREAM_URL = OANDA_URL.replace("api-fxpractice", "stream-fxpractice")
HEADERS = {"Authorization": f"Bearer {OANDA_TOKEN}"}

_running = False
_latest_price = {"bid": 0.0, "ask": 0.0}


def _log_journal(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, json.dumps(context) if context else None)
    )


def get_latest_price():
    return _latest_price.copy()


def _on_tick(bid: float, ask: float):
    global _latest_price
    _latest_price = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}

    open_trades = execute(
        "SELECT * FROM gd_trades WHERE strategy='alpha_sweep_oil' AND exit_time IS NULL AND oanda_trade_id IS NOT NULL",
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
                new_sl = entry + 0.01
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": bid, "source": "stream",
                    })
                    print(f"  [OIL STREAM] LONG break-even: SL → {new_sl:.4f}")
                else:
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"), "source": "stream",
                    })
        else:
            if tp >= entry:
                continue
            if sl <= entry:
                continue
            target_50 = entry - (entry - tp) * 0.5
            if ask <= target_50:
                new_sl = entry - 0.01
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": ask, "source": "stream",
                    })
                    print(f"  [OIL STREAM] SHORT break-even: SL → {new_sl:.4f}")
                else:
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"), "source": "stream",
                    })


def _stream_loop():
    global _running
    url = f"{STREAM_URL}/accounts/{OANDA_ACCOUNT}/pricing/stream?instruments=BCO_USD"

    while _running:
        try:
            with httpx.stream("GET", url, headers=HEADERS, timeout=None) as resp:
                if resp.status_code != 200:
                    _log_journal("SYSTEM", "alpha_sweep_oil", "STREAM_ERROR", None, {
                        "status": resp.status_code, "action": "reconnecting",
                    })
                    time.sleep(5)
                    continue
                print(f"  [OIL STREAM] Connected — receiving BCO_USD ticks")
                _log_journal("SYSTEM", "alpha_sweep_oil", "STREAM_CONNECTED", None, {"instrument": "BCO_USD"})
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
                            _on_tick(bid, ask)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except Exception as e:
            if _running:
                print(f"  [OIL STREAM] Disconnected: {e}. Reconnecting...")
                _log_journal("SYSTEM", "alpha_sweep_oil", "STREAM_DISCONNECTED", None, {
                    "error": str(e), "action": "reconnecting",
                })
                time.sleep(3)


def start_stream():
    global _running
    if _running:
        return
    _running = True
    t = threading.Thread(target=_stream_loop, daemon=True, name="oil-price-stream")
    t.start()
    print("Oil price stream started (BCO_USD tick-by-tick)")


def stop_stream():
    global _running
    _running = False
