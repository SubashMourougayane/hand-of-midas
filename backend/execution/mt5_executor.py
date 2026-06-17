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
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

# DWX files directory (MT5 Common Files)
DWX_DIR = os.getenv("DWX_DIR", os.path.expanduser(
    "~/Library/Application Support/net.metaquotes.wine.metatrader5/"
    "drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
))

# MT5 server timezone offset from UTC.
# JustMarkets MT5 servers run on GMT+3 year-round (no DST).
# Override via env var for other brokers if needed.
MT5_SERVER_OFFSET_HOURS = int(os.getenv("MT5_SERVER_OFFSET_HOURS", "3"))


def _server_to_utc_iso(t):
    """Convert MT5 server timestamp to real UTC ISO format.

    MT5 EA writes bar timestamps in server local time format like '2026.06.09 11:00:00',
    which is GMT+3 for JustMarkets. Strategy code expects ISO UTC ('2026-06-09T08:00:00Z').

    This helper subtracts the server offset to produce real UTC timestamps.
    """
    if "." not in t:
        return t  # already in ISO format (e.g., from a different source)
    try:
        server_dt = datetime.strptime(t, "%Y.%m.%d %H:%M:%S")
        utc_dt = server_dt - timedelta(hours=MT5_SERVER_OFFSET_HOURS)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        # Fallback: legacy behavior if parsing fails (don't crash on malformed timestamps)
        return t.replace(".", "-").replace(" ", "T") + "Z"


def _server_to_utc_dt(t):
    """Same as _server_to_utc_iso but returns a tz-aware datetime instead of ISO string.

    Returns None if the input is malformed — callers must handle gracefully.
    """
    if not t or "." not in t:
        return None
    try:
        server_dt = datetime.strptime(t, "%Y.%m.%d %H:%M:%S")
        utc_dt = server_dt - timedelta(hours=MT5_SERVER_OFFSET_HOURS)
        return utc_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def compute_time_to_fill(placement_dt, broker_open_time_str):
    """O4 — Filter #27: compute time elapsed between limit-order placement and
    broker fill, return as a compact human-readable string.

    Args:
        placement_dt: tz-aware datetime when we INSERTed the pending row
            (typically gd_trades.entry_time for the pending row, which is the
            wall-clock when the OPEN_PENDING command was issued — NOT the fill).
        broker_open_time_str: MT5 server-time string from open_orders.json
            (format: '2026.06.17 17:42:02', GMT+3 for JustMarkets).

    Returns:
        Compact string. Examples:
            '45s'       (45 seconds)
            '7m12s'     (7 minutes 12 seconds)
            '14m'       (round number)
            'unknown'   (broker_open_time malformed or placement_dt missing)
            'negative'  (broker fill time is BEFORE placement — clock skew or
                         server-time misconfigured)
    """
    if placement_dt is None or not broker_open_time_str:
        return "unknown"
    fill_dt = _server_to_utc_dt(broker_open_time_str)
    if fill_dt is None:
        return "unknown"
    # Make placement_dt tz-aware if it isn't (DB rows return tzinfo, but be safe)
    if placement_dt.tzinfo is None:
        placement_dt = placement_dt.replace(tzinfo=timezone.utc)
    delta = (fill_dt - placement_dt).total_seconds()
    if delta < 0:
        # Negative time = clock skew or wrong MT5_SERVER_OFFSET_HOURS for this broker.
        # Surface explicitly rather than silently rendering "-3m".
        return f"negative({int(delta)}s)"
    seconds = int(delta)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if secs == 0:
        return f"{minutes}m"
    return f"{minutes}m{secs}s"

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


# Logger — try service-local 'scanner._log' first (gold-micro/oil/oil-micro),
# fall back to 'backend.scanner._log' (gold-macro). Each service runs in its own
# Python process, so module caching gives the correct SERVICE_NAME at runtime.
# If neither resolves (e.g. running mt5_executor in isolation for tests), use
# a no-op shim so logging never crashes the executor.
try:
    from scanner import _log  # gold-micro / oil-macro / oil-micro
except ImportError:
    try:
        from backend.scanner import _log  # gold-macro
    except ImportError:
        class _NoOpLog:
            @staticmethod
            def debug(*a, **kw): pass
            @staticmethod
            def info(*a, **kw): pass
            @staticmethod
            def warn(*a, **kw): pass
            @staticmethod
            def error(*a, **kw): pass
            @staticmethod
            def exception(*a, **kw): pass
        _log = _NoOpLog()


def _read_json(filename):
    """Read a JSON file from DWX directory. Retries once on decode error (EA mid-write)."""
    path = os.path.join(DWX_DIR, filename)
    for attempt in range(2):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            if attempt == 0:
                time.sleep(0.05)
                continue
            return None
        except (FileNotFoundError, IOError):
            return None
    return None


_command_lock = threading.Lock()


def _write_command(cmd_string):
    """Write a command file for the EA to execute. Filename includes a
    process-id + counter so concurrent processes never collide on naming."""
    cmd_dir = os.path.join(DWX_DIR, "commands")
    os.makedirs(cmd_dir, exist_ok=True)
    # H2 (2026-06-17): include PID so concurrent processes can't pick the same
    # millisecond. Even if two services hit the same ms, their PIDs differ.
    # Format: cmd_<unix_ms>_<pid>.txt → unique across processes + monotonic
    # within process.
    filename = f"cmd_{int(time.time() * 1000)}_{os.getpid()}.txt"
    path = os.path.join(cmd_dir, filename)
    with open(path, "w") as f:
        f.write(cmd_string)
    return filename


def _wait_response(filename, timeout=10):
    """H2 (2026-06-17): wait for EA to write per-cmd response file
    `responses/<cmd_filename>`.

    Old behavior: poll shared last_response.json by mtime. Race-prone — 4
    processes shared one file, EA's last write won. After H2: each command
    gets its own response file named after the command file. No race possible
    across processes; each process polls only its own filename.

    Backward-compat fallback: if responses/ dir is empty after timeout AND
    the EA is older (pre-v2.13), fall back to last_response.json mtime polling
    so existing flows keep working during EA upgrade. Removed once EA v2.13+
    confirmed live across all environments.

    Args:
        filename: cmd file name returned by _write_command (e.g. cmd_<ms>_<pid>.txt)
        timeout: seconds to wait

    Returns:
        Parsed JSON dict, or None on timeout / parse error.
    """
    resp_dir = os.path.join(DWX_DIR, "responses")
    resp_path = os.path.join(resp_dir, filename)
    last_response_path = os.path.join(DWX_DIR, "last_response.json")
    start = time.time()
    # Track mtime of last_response.json for backward-compat fallback only
    initial_mtime = os.path.getmtime(last_response_path) if os.path.exists(last_response_path) else 0

    while time.time() - start < timeout:
        # H2 canonical path: per-cmd response file
        if os.path.exists(resp_path):
            time.sleep(0.05)  # small wait to ensure file is fully written
            try:
                with open(resp_path) as f:
                    response = json.load(f)
                # H2 cleanup: delete the response file after reading. Prevents
                # `responses/` from accumulating over time. EA recomputes from
                # scratch on next command — this file's job is done.
                try:
                    os.remove(resp_path)
                except OSError:
                    pass  # best-effort; not fatal if cleanup fails
                return response
            except Exception:
                # File exists but not yet flushed — retry next iteration
                pass

        # Backward-compat: if EA is older (pre-v2.13), the per-cmd file will never
        # appear. Detect by checking last_response.json mtime change.
        if os.path.exists(last_response_path):
            mtime = os.path.getmtime(last_response_path)
            if mtime > initial_mtime:
                # H2: only use this fallback if responses/ dir is missing entirely
                # (EA pre-v2.13). If responses/ exists, prefer waiting for our own.
                if not os.path.isdir(resp_dir):
                    time.sleep(0.05)
                    try:
                        with open(last_response_path) as f:
                            response = json.load(f)
                            _log.warn("BROKER", "wait_response_fallback_to_shared",
                                      filename=filename,
                                      note="responses/ dir missing — EA may be pre-v2.13; using shared last_response.json")
                            return response
                    except Exception:
                        pass
        time.sleep(0.1)
    return None


def _send_command(cmd_string, timeout=10):
    """Thread-safe: write command + wait response.

    H2 (2026-06-17): correlation is now by per-cmd response file
    (`responses/<cmd_filename>.txt`) rather than shared last_response.json.
    `_command_lock` is preserved as a sanity-net for in-process serialization
    (DB connection pool, log ordering, etc.) but is no longer required for
    correctness — concurrent processes get correctly-correlated responses
    via the per-cmd file.

    Logs every command's send/receive cycle to BROKER category for full
    traceability when investigating live issues.
    """
    action = cmd_string.split("|", 1)[0] if "|" in cmd_string else cmd_string
    t0 = time.time()
    _log.debug("BROKER", "command_sent", action=action, cmd=cmd_string, timeout=timeout)

    with _command_lock:
        filename = _write_command(cmd_string)
        response = _wait_response(filename, timeout)

    elapsed_ms = int((time.time() - t0) * 1000)

    if response is None:
        _log.warn("BROKER", "command_timeout", action=action, cmd=cmd_string, elapsed_ms=elapsed_ms)
    elif response.get("success"):
        _log.info("BROKER", "command_ack", action=action,
                  elapsed_ms=elapsed_ms, response=response)
    else:
        _log.error("BROKER", "command_rejected", action=action, elapsed_ms=elapsed_ms,
                   retcode=response.get("retcode"),
                   error=response.get("error") or response.get("comment", "Unknown"))

    return response


def _mt5_symbol(instrument):
    """Convert internal instrument name to MT5 symbol."""
    return SYMBOL_MAP.get(instrument, instrument)


def _parse_mt5_time(time_str):
    """Parse MT5 server-time string '2026.05.26 11:08:21' to real UTC datetime.

    MT5 server is GMT+3 (JustMarkets). This subtracts the offset so the returned
    datetime is real UTC, matching everything else in the system.
    """
    try:
        server_dt = datetime.strptime(time_str, "%Y.%m.%d %H:%M:%S")
        utc_dt = server_dt - timedelta(hours=MT5_SERVER_OFFSET_HOURS)
        return utc_dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        # Issue #23 fix 2026-06-15: was bare except + silent fallback to now().
        # If EA ever sends garbage, log so it's visible. Function currently
        # has no callers but retain backward-compat (caller may rely on
        # never-None return, so we still return now() — but loudly).
        try:
            from scanner import _log
            _log.warn("BROKER", "mt5_time_parse_failed", input=str(time_str)[:100], err=str(e))
        except Exception: pass
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
            # Expose comment so callers (e.g. orphan reconciler) can ignore
            # harness/test trades placed with HARNESS_* prefixed comments.
            "comment": pos.get("comment", ""),
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
            "timestamp": _server_to_utc_iso(t),
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

    # Filter #27 slippage attribution: snapshot bid/ask from market_data.json AT order_placing.
    # Lets us decompose slippage post-hoc into (1) calc-error vs (2) network/queue latency
    # vs (3) market-move during roundtrip. snapshot_send.bid/ask is what we THOUGHT the
    # price was when we sent the order; fill_price is what we actually got. The gap is
    # all of (latency + market-move + spread cost). Compare to strategy's calc_entry to
    # isolate calc-error.
    snapshot_send = get_current_price(instrument)
    snapshot_send_bid = snapshot_send["bid"] if snapshot_send else None
    snapshot_send_ask = snapshot_send["ask"] if snapshot_send else None
    snapshot_send_time = snapshot_send.get("time") if snapshot_send else None

    _log.info("BROKER", "place_market_order_start", instrument=instrument, symbol=symbol,
              type=order_type, units=volume, lots=lots, sl=sl_price, tp=tp_price, comment=comment,
              snap_bid=snapshot_send_bid, snap_ask=snapshot_send_ask, snap_time=snapshot_send_time)

    cmd = f"OPEN|{symbol}|{order_type}|{lots}|{price}|{sl_price}|{tp_price}|{comment}"
    response = _send_command(cmd, timeout=10)
    if not response:
        _log.error("BROKER", "place_market_order_timeout", instrument=instrument, units=volume)
        return {"success": False, "error": "Timeout waiting for EA response"}

    if response.get("success"):
        # Issue #7 fix 2026-06-15: validate EA response before treating as success.
        # Prior code defaulted ticket=0 / price=0 silently, allowing malformed
        # EA replies to persist trades with fill_price=0, oanda_trade_id="0".
        # That breaks dedup queries (multiple trades with id="0" collide) and
        # P&L calculations (entry @ $0).
        ticket = response.get("ticket")
        price = response.get("price")
        if not ticket or float(ticket) <= 0 or not price or float(price) <= 0:
            _log.error("BROKER", "place_market_order_malformed_response",
                       instrument=instrument, ticket=ticket, price=price,
                       retcode=response.get("retcode"),
                       comment=response.get("comment", ""),
                       full_response=str(response))
            return {
                "success": False,
                "retcode": response.get("retcode"),
                "comment": response.get("comment", ""),
                "error": f"EA reported success but malformed: ticket={ticket} price={price} retcode={response.get('retcode')}",
            }
        # Filter #27 slippage attribution: snapshot bid/ask AT fill (post-roundtrip)
        # so we can also distinguish "broker price moved during 638ms" from "the bid/ask
        # we saw at send was already stale". snap_at_fill - snap_at_send = market move
        # during the roundtrip; fill_price - snap_at_fill ≈ spread cost; calc_entry -
        # snap_at_send = strategy calc-error. Each component logged separately.
        snapshot_fill = get_current_price(instrument)
        snap_fill_bid = snapshot_fill["bid"] if snapshot_fill else None
        snap_fill_ask = snapshot_fill["ask"] if snapshot_fill else None
        _log.info("BROKER", "place_market_order_filled", instrument=instrument,
                  trade_id=str(ticket), fill_price=price, units=volume,
                  snap_send_bid=snapshot_send_bid, snap_send_ask=snapshot_send_ask,
                  snap_fill_bid=snap_fill_bid, snap_fill_ask=snap_fill_ask)
        return {
            "success": True,
            "fill_price": price,
            "trade_id": str(ticket),
            "units": volume,
            "time": datetime.now(timezone.utc).isoformat(),
        }
    else:
        _log.error("BROKER", "place_market_order_failed", instrument=instrument,
                   retcode=response.get("retcode"), comment=response.get("comment", "Unknown"),
                   snap_send_bid=snapshot_send_bid, snap_send_ask=snapshot_send_ask)
        return {
            "success": False,
            "error": f"retcode={response.get('retcode')}: {response.get('comment', 'Unknown')}",
        }


def place_limit_order(instrument, units, limit_price, sl=None, tp=None,
                      ttl_seconds=900, comment=""):
    """Filter #27: place a pending limit order via DWX command file.

    The order sits at limit_price for at most ttl_seconds. Broker auto-cancels
    after expiration; client-side APScheduler cancel-job is also wired as
    belt-and-suspenders. Fill is detected via OnTradeTransaction's DEAL_ENTRY_IN
    event (writes closed_orders.json — no, writes open_orders.json on next
    poll cycle since the position is now live).

    Args:
        instrument: Internal name (e.g., "XAU_USD")
        units: Positive for BUY_LIMIT, negative for SELL_LIMIT
        limit_price: trigger price for the pending order
        sl: stop loss price (0 / None = no SL on the pending; broker will set
            it once the limit fills)
        tp: take profit price (0 / None = no TP)
        ttl_seconds: how long the limit lives before broker auto-cancels.
            Default 900s (15min) matches Filter #27's ttl15 winning variant.
        comment: passes through to DWX → broker order comment.
            Caller passes "{strategy}|{trade_ref}" so broker logs / open_orders
            preserve our trace identity.

    Returns:
        dict with keys:
            success (bool)
            ticket (str) — broker-assigned pending-order ticket if success
            limit_price (float) — echoed back from EA
            expiration_time (str ISO UTC) — when broker will auto-cancel
            time (str ISO UTC) — when our send completed
            error (str) — only on failure
    """
    symbol = _mt5_symbol(instrument)
    order_type = "BUY_LIMIT" if units > 0 else "SELL_LIMIT"
    volume = abs(units)

    # Same volume → lots conversion as place_market_order. Mirror exactly so
    # parity tests on size match.
    if "XAU" in symbol:
        lots = volume / 100.0
    elif "BRENT" in symbol or "BCO" in symbol:
        lots = volume / 1000.0
    else:
        lots = volume / 100000.0
    lots = round(max(lots, 0.01), 2)

    sl_price = sl if sl else 0
    tp_price = tp if tp else 0

    # Slippage attribution: snapshot bid/ask at send time so post-hoc analysis
    # can compare limit_price vs market price at send vs eventual fill.
    snapshot_send = get_current_price(instrument)
    snapshot_send_bid = snapshot_send["bid"] if snapshot_send else None
    snapshot_send_ask = snapshot_send["ask"] if snapshot_send else None

    _log.info("BROKER", "place_limit_order_start", instrument=instrument, symbol=symbol,
              type=order_type, units=volume, lots=lots, limit_price=limit_price,
              sl=sl_price, tp=tp_price, ttl_seconds=ttl_seconds, comment=comment,
              snap_bid=snapshot_send_bid, snap_ask=snapshot_send_ask)

    # DWX command shape (added to mql5/DWX_Server.mq5 alongside OPEN):
    #   OPEN_PENDING|<symbol>|<BUY_LIMIT|SELL_LIMIT>|<lots>|<price>|<sl>|<tp>|<ttl_seconds>|<comment>
    cmd = (
        f"OPEN_PENDING|{symbol}|{order_type}|{lots}|{limit_price}|"
        f"{sl_price}|{tp_price}|{ttl_seconds}|{comment}"
    )
    response = _send_command(cmd, timeout=10)
    if not response:
        _log.error("BROKER", "place_limit_order_timeout", instrument=instrument,
                   units=volume, limit_price=limit_price)
        return {"success": False, "error": "Timeout waiting for EA response"}

    if response.get("success"):
        ticket = response.get("ticket")
        # Echo the limit price the EA actually placed (broker may round to tick).
        echoed_price = response.get("price", limit_price)
        if not ticket or float(ticket) <= 0:
            _log.error("BROKER", "place_limit_order_malformed_response",
                       instrument=instrument, ticket=ticket,
                       retcode=response.get("retcode"),
                       comment=response.get("comment", ""),
                       full_response=str(response))
            return {
                "success": False,
                "retcode": response.get("retcode"),
                "comment": response.get("comment", ""),
                "error": f"EA reported success but malformed: ticket={ticket} retcode={response.get('retcode')}",
            }
        _log.info("BROKER", "place_limit_order_placed", instrument=instrument,
                  ticket=str(ticket), limit_price=echoed_price,
                  expiration=response.get("expiration"), units=volume)
        return {
            "success": True,
            "ticket": str(ticket),
            "limit_price": echoed_price,
            "expiration_time": response.get("expiration"),
            "units": volume,
            "time": datetime.now(timezone.utc).isoformat(),
        }
    else:
        _log.error("BROKER", "place_limit_order_failed", instrument=instrument,
                   limit_price=limit_price, retcode=response.get("retcode"),
                   comment=response.get("comment", "Unknown"))
        return {
            "success": False,
            "error": f"retcode={response.get('retcode')}: {response.get('comment', 'Unknown')}",
        }


def cancel_pending_order(ticket):
    """Filter #27: cancel a pending limit order by ticket.

    Idempotent: if the broker already filled or cancelled, returns
    success=False with a clear retcode that the caller (the APScheduler
    cancel-job) treats as a no-op rather than an error.

    Args:
        ticket: broker pending-order ticket as returned by place_limit_order

    Returns:
        dict with success / error / retcode
    """
    _log.info("BROKER", "cancel_pending_order_start", ticket=str(ticket))

    cmd = f"CANCEL_PENDING|{ticket}"
    response = _send_command(cmd, timeout=10)
    if not response:
        _log.error("BROKER", "cancel_pending_order_timeout", ticket=str(ticket))
        return {"success": False, "error": "Timeout"}

    if response.get("success"):
        _log.info("BROKER", "cancel_pending_order_ok", ticket=str(ticket))
        return {"success": True}
    else:
        # Common harmless cases: order already filled (DEAL_ENTRY_IN already
        # fired before our cancel arrived), or order already auto-cancelled
        # by broker on TTL expiration. Caller decides whether to treat as
        # error based on retcode.
        retcode = response.get("retcode")
        comment = response.get("comment", "Unknown")
        _log.warn("BROKER", "cancel_pending_order_failed", ticket=str(ticket),
                  retcode=retcode, comment=comment)
        return {
            "success": False,
            "retcode": retcode,
            "error": f"retcode={retcode}: {comment}",
        }


def modify_stop_loss(trade_id, new_sl, new_tp=None):
    """Modify the stop loss (and optionally TP) of an existing position."""
    tp_price = new_tp if new_tp else 0
    _log.info("BROKER", "modify_stop_loss_start", trade_id=str(trade_id),
              new_sl=new_sl, new_tp=tp_price)

    cmd = f"MODIFY|{trade_id}|{new_sl}|{tp_price}"
    response = _send_command(cmd, timeout=10)
    if not response:
        _log.error("BROKER", "modify_stop_loss_timeout", trade_id=str(trade_id), new_sl=new_sl)
        return {"success": False, "error": "Timeout"}

    if response.get("success"):
        _log.info("BROKER", "modify_stop_loss_ok", trade_id=str(trade_id),
                  new_sl=new_sl, new_tp=tp_price)
    else:
        _log.error("BROKER", "modify_stop_loss_failed", trade_id=str(trade_id),
                   new_sl=new_sl, retcode=response.get("retcode"),
                   comment=response.get("comment", ""))

    return {
        "success": response.get("success", False),
        "error": response.get("comment", "") if not response.get("success") else None,
    }


def close_trade(trade_id):
    """Close an open position by ticket."""
    _log.info("BROKER", "close_trade_start", trade_id=str(trade_id))

    cmd = f"CLOSE|{trade_id}"
    response = _send_command(cmd, timeout=10)
    if not response:
        _log.error("BROKER", "close_trade_timeout", trade_id=str(trade_id))
        return {"success": False, "error": "Timeout"}

    if response.get("success"):
        _log.info("BROKER", "close_trade_ok", trade_id=str(trade_id),
                  close_price=response.get("close_price", 0),
                  realized_pl=response.get("profit", 0))
    else:
        _log.error("BROKER", "close_trade_failed", trade_id=str(trade_id),
                   retcode=response.get("retcode"), comment=response.get("comment", ""))

    return {
        "success": response.get("success", False),
        "close_price": response.get("close_price", 0),
        "realized_pl": response.get("profit", 0),
        "error": response.get("comment", "") if not response.get("success") else None,
        "retcode": response.get("retcode"),
    }


def close_partial_trade(trade_id, units_to_close, instrument="XAU_USD"):
    """Filter #7: close PART of an open position.

    Args:
        trade_id: broker ticket (string)
        units_to_close: position units (oz for XAU, barrels for BCO).
                        Converted to lots using same formula as place_market_order.
        instrument: needed for unit→lot conversion. Pass the same instrument
                    that opened the trade (e.g. "XAU_USD" or "BCO_USD").

    Returns:
        dict {success, close_price, closed_units, remaining_units, error}
    """
    symbol = _mt5_symbol(instrument)
    if "XAU" in symbol:
        lots = units_to_close / 100.0
    elif "BRENT" in symbol or "BCO" in symbol:
        lots = units_to_close / 1000.0
    else:
        lots = units_to_close / 100000.0
    lots = round(max(lots, 0.01), 2)

    _log.info("BROKER", "close_partial_start", trade_id=str(trade_id),
              instrument=instrument, units_to_close=units_to_close, lots=lots)

    cmd = f"CLOSE_PARTIAL|{trade_id}|{lots}"
    response = _send_command(cmd, timeout=10)
    if not response:
        _log.error("BROKER", "close_partial_timeout", trade_id=str(trade_id),
                   units_to_close=units_to_close)
        return {"success": False, "error": "Timeout waiting for EA response"}

    if not response.get("success"):
        err = response.get("error") or response.get("comment", "Unknown")
        _log.error("BROKER", "close_partial_failed", trade_id=str(trade_id),
                   units_to_close=units_to_close, retcode=response.get("retcode"), error=err)
        return {
            "success": False,
            "error": err,
            "retcode": response.get("retcode"),
        }

    closed_lots = response.get("closed_volume", lots)
    remaining_lots = response.get("remaining_volume", 0)
    # Convert lots back to units (same formula, inverse direction)
    if "XAU" in symbol:
        units_factor = 100.0
    elif "BRENT" in symbol or "BCO" in symbol:
        units_factor = 1000.0
    else:
        units_factor = 100000.0
    closed_units = int(round(closed_lots * units_factor))
    remaining_units = int(round(remaining_lots * units_factor))

    _log.info("BROKER", "close_partial_ok", trade_id=str(trade_id),
              close_price=response.get("close_price", 0),
              closed_lots=closed_lots, remaining_lots=remaining_lots,
              closed_units=closed_units, remaining_units=remaining_units)

    return {
        "success": True,
        "close_price": response.get("close_price", 0),
        "closed_units": closed_units,
        "remaining_units": remaining_units,
        "error": None,
    }


def get_trade_details(trade_id):
    """Get details of a specific trade. Checks open_orders.json first; if the
    trade is no longer open, falls back to closed_orders.json (written by the
    DWX EA's OnTradeTransaction handler with the AUTHORITATIVE close price/
    reason from MT5's history).

    Returns None if trade ID isn't found in either file. Callers handling None
    should NOT use heuristics to guess the close — see
    docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md for why that broke June 10.
    """
    # First: check if it's still open
    data = _read_json("open_orders.json")
    if data and str(trade_id) in data:
        pos = data[str(trade_id)]
        return {
            "id": str(trade_id),
            "state": "OPEN",
            "instrument": SYMBOL_MAP_REVERSE.get(pos["symbol"], pos["symbol"]),
            "price": pos["open_price"],
            "realizedPL": "0",
            "currentUnits": pos["volume"] if pos["type"] == "BUY" else -pos["volume"],
        }

    # Fall back: check closed_orders.json for the authoritative close record
    closed = _read_json("closed_orders.json")
    if closed:
        # closed_orders.json is a JSON array; find by ticket
        for entry in closed:
            if str(entry.get("ticket")) == str(trade_id):
                return {
                    "id": str(trade_id),
                    "state": "CLOSED",
                    "instrument": SYMBOL_MAP_REVERSE.get(entry["symbol"], entry["symbol"]),
                    "price": entry["open_price"],
                    "close_price": entry["close_price"],
                    "close_time": _server_to_utc_iso(entry["close_time"]),
                    # realized_pl is gross (broker profit only — does NOT include commission/swap)
                    # Caller can subtract commission separately via the field below if needed.
                    "realized_pl": float(entry.get("profit", 0)),
                    "commission": float(entry.get("commission", 0)),
                    "swap": float(entry.get("swap", 0)),
                    # deal_reason: 'TP' / 'SL' / 'CLIENT' / 'SO' / 'EXPERT' / 'UNKNOWN'
                    "exit_reason": entry.get("deal_reason", "UNKNOWN"),
                    "currentUnits": entry["volume"] if entry["type"] == "BUY" else -entry["volume"],
                }

    return None


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
