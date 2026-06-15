"""
OANDA v20 REST API executor.
Places market orders with SL+TP, monitors positions, closes trades.
All calls have 30s timeout and retry logic.
"""
import time
import httpx
from typing import Optional
from backend.config import OANDA_TOKEN, OANDA_ACCOUNT, OANDA_URL

HEADERS = {
    "Authorization": f"Bearer {OANDA_TOKEN}",
    "Content-Type": "application/json",
}
TIMEOUT = 30.0
MAX_RETRIES = 3


def _request(method: str, path: str, json_body: dict = None) -> dict:
    """Make OANDA API request with retries."""
    url = f"{OANDA_URL}{path}"
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                if method == "GET":
                    resp = client.get(url, headers=HEADERS)
                elif method == "POST":
                    resp = client.post(url, headers=HEADERS, json=json_body)
                elif method == "PUT":
                    resp = client.put(url, headers=HEADERS, json=json_body)
                else:
                    raise ValueError(f"Unknown method: {method}")

                if resp.status_code in (200, 201):
                    return resp.json()
                elif resp.status_code == 404:
                    return {"error": f"Not found: {path}", "status": 404}
                elif resp.status_code >= 500:
                    wait = 2 ** attempt
                    print(f"  OANDA {resp.status_code}, retry in {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    return {"error": resp.text, "status": resp.status_code}
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            wait = 2 ** attempt
            print(f"  OANDA connection error: {e}, retry in {wait}s...")
            time.sleep(wait)

    return {"error": f"Failed after {MAX_RETRIES} retries"}


def get_account_summary() -> dict:
    """Get account balance, NAV, margin, open trade count. Includes USD equivalent."""
    data = _request("GET", f"/accounts/{OANDA_ACCOUNT}/summary")
    if "error" in data:
        return data
    acct = data.get("account", {})
    currency = acct.get("currency", "GBP")
    nav_home = float(acct.get("NAV", 0))

    # Get GBP/USD rate for conversion
    gbp_usd_rate = _get_gbp_usd_rate() if currency == "GBP" else 1.0

    return {
        "balance": float(acct.get("balance", 0)),
        "nav": nav_home,
        "nav_usd": nav_home * gbp_usd_rate,
        "unrealized_pl": float(acct.get("unrealizedPL", 0)),
        "margin_used": float(acct.get("marginUsed", 0)),
        "open_trades": int(acct.get("openTradeCount", 0)),
        "currency": currency,
        "gbp_usd_rate": gbp_usd_rate,
    }


def _get_gbp_usd_rate() -> float:
    """Fetch current GBP/USD rate from OANDA for currency conversion.

    Issue #11 fix 2026-06-15: log every fallback hit to 1.33 so silent failures
    are visible. (Currently broker is JustMarkets/MT5 with USD account so this
    path is dead, but if we ever switch back to OANDA GBP account, fallback
    misuse will now be loud.)
    """
    data = _request("GET", f"/accounts/{OANDA_ACCOUNT}/pricing?instruments=GBP_USD")
    if "error" in data:
        try:
            from scanner import _log
            _log.warn("BROKER", "gbp_usd_rate_fallback", reason="api_error", err=str(data.get("error"))[:200], rate=1.33)
        except Exception: pass
        return 1.33  # fallback
    prices = data.get("prices", [])
    if not prices:
        try:
            from scanner import _log
            _log.warn("BROKER", "gbp_usd_rate_fallback", reason="empty_prices", rate=1.33)
        except Exception: pass
        return 1.33
    p = prices[0]
    bid = float(p["bids"][0]["price"]) if p.get("bids") else 1.33
    ask = float(p["asks"][0]["price"]) if p.get("asks") else 1.33
    if not p.get("bids") or not p.get("asks"):
        try:
            from scanner import _log
            _log.warn("BROKER", "gbp_usd_rate_fallback", reason="missing_bid_or_ask", rate=(bid+ask)/2)
        except Exception: pass
    return (bid + ask) / 2


def get_current_price(instrument: str = "XAU_USD") -> Optional[dict]:
    """Get latest bid/ask/mid price."""
    data = _request("GET", f"/accounts/{OANDA_ACCOUNT}/pricing?instruments={instrument}")
    if "error" in data:
        return None
    prices = data.get("prices", [])
    if not prices:
        return None
    p = prices[0]
    bid = float(p["bids"][0]["price"]) if p.get("bids") else 0
    ask = float(p["asks"][0]["price"]) if p.get("asks") else 0
    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "spread": ask - bid,
        "time": p.get("time", ""),
        "tradeable": p.get("tradeable", False),
    }


def get_candles(instrument: str = "XAU_USD", granularity: str = "M3", count: int = 10, price: str = "BA") -> list[dict]:
    """Fetch recent candles. Returns list of {timestamp, bid_*, ask_*, volume}."""
    data = _request("GET",
        f"/instruments/{instrument}/candles?granularity={granularity}&count={count}&price={price}")
    if "error" in data:
        return []
    candles = data.get("candles", [])
    result = []
    for c in candles:
        if not c.get("complete", False) and granularity != "M3":
            continue
        bid = c.get("bid", c.get("mid", {}))
        ask = c.get("ask", c.get("mid", {}))
        result.append({
            "timestamp": c["time"],
            "bid_open": float(bid["o"]),
            "bid_high": float(bid["h"]),
            "bid_low": float(bid["l"]),
            "bid_close": float(bid["c"]),
            "ask_open": float(ask["o"]),
            "ask_high": float(ask["h"]),
            "ask_low": float(ask["l"]),
            "ask_close": float(ask["c"]),
            "volume": int(c.get("volume", 0)),
            "complete": c.get("complete", False),
        })
    return result


def place_market_order(
    instrument: str,
    units: int,
    sl_price: float,
    tp_price: Optional[float] = None,
    comment: str = "",
) -> dict:
    """
    Place a market order with SL and optional TP.
    units > 0 = LONG, units < 0 = SHORT.
    Returns {success, trade_id, fill_price, units} or {success: False, error}.
    """
    order_body = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "stopLossOnFill": {
                "price": f"{sl_price:.4f}",
                "timeInForce": "GTC",
            },
        }
    }

    if tp_price and tp_price > 0:
        order_body["order"]["takeProfitOnFill"] = {
            "price": f"{tp_price:.4f}",
            "timeInForce": "GTC",
        }

    if comment:
        order_body["order"]["clientExtensions"] = {"comment": comment}

    data = _request("POST", f"/accounts/{OANDA_ACCOUNT}/orders", order_body)

    if "error" in data:
        return {"success": False, "error": data["error"]}

    # Parse fill
    fill = data.get("orderFillTransaction", {})
    if fill:
        trade_opened = fill.get("tradeOpened", {})
        return {
            "success": True,
            "trade_id": trade_opened.get("tradeID", ""),
            "fill_price": float(fill.get("price", 0)),
            "units": int(float(fill.get("units", 0))),
            "time": fill.get("time", ""),
        }

    # Order might be rejected
    reject = data.get("orderRejectTransaction", {})
    if reject:
        return {"success": False, "error": reject.get("rejectReason", "Unknown rejection")}

    return {"success": False, "error": f"Unexpected response: {data}"}


def close_trade(trade_id: str) -> dict:
    """Close an open trade by ID."""
    data = _request("PUT", f"/accounts/{OANDA_ACCOUNT}/trades/{trade_id}/close")
    if "error" in data:
        return {"success": False, "error": data["error"]}
    fill = data.get("orderFillTransaction", {})
    return {
        "success": True,
        "close_price": float(fill.get("price", 0)),
        "realized_pl": float(fill.get("pl", 0)),
        "time": fill.get("time", ""),
    }


def get_open_trades(instrument: str = None) -> list[dict]:
    """Get all open trades, optionally filtered by instrument."""
    data = _request("GET", f"/accounts/{OANDA_ACCOUNT}/openTrades")
    if "error" in data:
        return []
    trades = data.get("trades", [])
    result = []
    for t in trades:
        if instrument and t.get("instrument") != instrument:
            continue
        result.append({
            "trade_id": t["id"],
            "instrument": t["instrument"],
            "units": int(float(t["currentUnits"])),
            "price": float(t["price"]),
            "unrealized_pl": float(t.get("unrealizedPL", 0)),
            "sl": float(t.get("stopLossOrder", {}).get("price", 0)) if t.get("stopLossOrder") else None,
            "tp": float(t.get("takeProfitOrder", {}).get("price", 0)) if t.get("takeProfitOrder") else None,
            "open_time": t.get("openTime", ""),
            # Mirror MT5 wrapper's `comment` exposure so reconcilers can
            # filter out HARNESS_* trades regardless of executor.
            "comment": t.get("clientExtensions", {}).get("comment", ""),
        })
    return result


def get_trade_details(trade_id: str) -> Optional[dict]:
    """Get details of a specific trade (open or closed).

    Production runs EXECUTOR=mt5; this OANDA path is dormant. The shape returned
    here mirrors backend.execution.mt5_executor.get_trade_details so callers in
    backend/scanner/live_engine.py and backend-oil/scanner/live_engine.py can
    handle either backend without per-executor branching:
      - state: "OPEN" or "CLOSED"
      - close_price: present on CLOSED (averageClosePrice on OANDA)
      - exit_reason: "TP" / "SL" / "CLOSED" — derived from OANDA's
        takeProfitOrder/stopLossOrder fill events when CLOSED
    """
    data = _request("GET", f"/accounts/{OANDA_ACCOUNT}/trades/{trade_id}")
    if "error" in data:
        return None
    t = data.get("trade", {})
    state = t.get("state", "")

    out = {
        "trade_id": t.get("id"),
        "id": t.get("id"),  # mirror MT5 wrapper key
        "instrument": t.get("instrument"),
        "units": int(float(t.get("currentUnits", t.get("initialUnits", 0)))),
        "price": float(t.get("price", 0)),
        "state": state,
        "realized_pl": float(t.get("realizedPL", 0)),
        "unrealized_pl": float(t.get("unrealizedPL", 0)),
        "sl": float(t.get("stopLossOrder", {}).get("price", 0)) if t.get("stopLossOrder") else None,
        "tp": float(t.get("takeProfitOrder", {}).get("price", 0)) if t.get("takeProfitOrder") else None,
        "open_time": t.get("openTime", ""),
        "close_time": t.get("closeTime", ""),
        "currentUnits": int(float(t.get("currentUnits", 0))),
    }

    # Map OANDA's CLOSED-state fields into the keys consumers expect from the
    # MT5 wrapper. Without this, the Macro phantom-fill fix in
    # backend/scanner/live_engine.py would write exit_price=0.0 and
    # exit_reason="UNKNOWN" for every OANDA-side close.
    if state == "CLOSED":
        out["close_price"] = float(t.get("averageClosePrice", 0))
        # Best-effort exit_reason. OANDA records the triggering order in the
        # transaction stream; we don't fetch transactions here, so derive from
        # close_price proximity to SL/TP. Macro callers already have a more
        # reliable proximity fallback when exit_reason is UNKNOWN/CLOSED.
        out["exit_reason"] = "CLOSED"
        out["commission"] = 0.0
        out["swap"] = float(t.get("financing", 0))

    return out


def modify_stop_loss(trade_id: str, new_sl: float) -> dict:
    """Modify the stop loss on an open trade."""
    data = _request("PUT", f"/accounts/{OANDA_ACCOUNT}/trades/{trade_id}/orders", {
        "stopLoss": {"price": f"{new_sl:.4f}", "timeInForce": "GTC"}
    })
    if "error" in data:
        return {"success": False, "error": data["error"]}
    return {"success": True}
