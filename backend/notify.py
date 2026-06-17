"""Telegram notifications for Hand Of Midas.

Issue #13 fix 2026-06-15: prior `except Exception: pass` swallowed all
errors silently. If BOT_TOKEN/CHAT_ID were missing or wrong, every alert
disappeared. Now: log every failure with a short message so debug API
+ logs surface the issue. Misconfigured tokens detected at import time.
"""
import os
import sys
import threading
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# Import-time sanity check — print to stderr if unconfigured.
if not BOT_TOKEN or not CHAT_ID:
    print("[NOTIFY] WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — Telegram alerts will be no-ops",
          file=sys.stderr)

# Track failures so spam doesn't drown logs but issues are still visible.
_failure_count = 0
_failure_lock = threading.Lock()


def send(message: str):
    """Send a Telegram notification (non-blocking)."""
    threading.Thread(target=_send, args=(message,), daemon=True).start()


def _send(message: str):
    global _failure_count
    if not BOT_TOKEN or not CHAT_ID:
        with _failure_lock:
            _failure_count += 1
            if _failure_count <= 3 or _failure_count % 50 == 0:
                print(f"[NOTIFY] dropped (no token/chat_id, total dropped: {_failure_count}): {message[:80]}",
                      file=sys.stderr)
        return
    try:
        r = httpx.post(API_URL, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if r.status_code != 200:
            with _failure_lock:
                _failure_count += 1
                if _failure_count <= 3 or _failure_count % 50 == 0:
                    print(f"[NOTIFY] HTTP {r.status_code} (total fail: {_failure_count}): {r.text[:200]}",
                          file=sys.stderr)
    except Exception as e:
        with _failure_lock:
            _failure_count += 1
            if _failure_count <= 3 or _failure_count % 50 == 0:
                print(f"[NOTIFY] exception (total fail: {_failure_count}): {type(e).__name__}: {str(e)[:200]}",
                      file=sys.stderr)


def signal_taken(strategy: str, direction: str, instrument: str, entry: float, sl: float, tp: float, units: int):
    fmt = ".2f" if instrument == "XAU_USD" else ".4f"
    send(
        f"📈 <b>SIGNAL TAKEN</b>\n"
        f"{instrument} | {strategy} | {direction.upper()}\n"
        f"Entry: ${entry:{fmt}}\n"
        f"SL: ${sl:{fmt}} | TP: ${tp:{fmt}}\n"
        f"Units: {units}"
    )


def signal_skipped(strategy: str, direction: str, instrument: str, reason: str):
    send(f"⏭️ Signal skipped: {instrument} {strategy} {direction.upper()}\nReason: {reason}")


def trade_filled(trade_ref: str, instrument: str, direction: str, fill_price: float, units: int, sl: float, tp: float):
    fmt = ".2f" if instrument == "XAU_USD" else ".4f"
    send(
        f"✅ <b>TRADE FILLED</b>\n"
        f"{trade_ref}\n"
        f"{instrument} {direction.upper()} {units} units @ ${fill_price:{fmt}}\n"
        f"SL: ${sl:{fmt}} | TP: ${tp:{fmt}}"
    )


def trade_closed(trade_ref: str, instrument: str, exit_reason: str, pnl_gbp: float, pnl_usd: float):
    emoji = "💰" if pnl_gbp > 0 else "🔴"
    send(
        f"{emoji} <b>TRADE CLOSED</b>\n"
        f"{trade_ref} | {exit_reason}\n"
        f"P&L: £{pnl_gbp:+.2f} (${pnl_usd:+.2f})"
    )


def break_even(trade_ref: str, instrument: str, new_sl: float):
    fmt = ".2f" if instrument == "XAU_USD" else ".4f"
    send(f"🛡️ Break-even: {trade_ref}\nSL moved to ${new_sl:{fmt}}")


def partial_tp(trade_ref: str, instrument: str, units_closed: int, fill_price: float,
               banked_usd: float, units_remaining: int):
    """Filter #7: partial TP fired. Half banked, runner continues."""
    fmt = ".2f" if "XAU" in instrument else ".4f"
    send(
        f"🪓 <b>PARTIAL TP</b>\n"
        f"{trade_ref}\n"
        f"Closed {units_closed} units @ ${fill_price:{fmt}}\n"
        f"Banked: ${banked_usd:+.2f}\n"
        f"Runner: {units_remaining} units (full TP/SL/BE/trail apply)"
    )


def error(message: str):
    send(f"⚠️ <b>ERROR</b>\n{message}")


def max_hold_deferred(trade_ref: str, instrument: str):
    """Fired ONCE per trade when MAX_HOLD close fails because the broker
    market is closed. Subsequent same-cause retries are silent — the
    eventual successful close fires trade_closed(reason='MAX_HOLD (deferred)')
    so the user gets a paired open/close pair."""
    send(
        f"ℹ️ <b>MAX_HOLD DEFERRED</b>\n"
        f"{trade_ref}\n"
        f"{instrument} market closed — will close on reopen."
    )


def limit_placed(trade_ref: str, instrument: str, direction: str,
                 limit_price: float, ttl_seconds: int):
    """Filter #27 live: pending limit order placed at broker.

    Fires once per trade_ref when scheduler successfully places the pending
    order. The lifecycle pair closes with either:
    - `trade_filled` (broker filled — switches to live position)
    - `limit_ttl_expired` (TTL hit, cancelled, never filled)
    """
    fmt = ".2f" if "XAU" in instrument else ".4f"
    send(
        f"📋 <b>LIMIT PLACED</b>\n"
        f"{trade_ref}\n"
        f"{instrument} {direction.upper()} @ ${limit_price:{fmt}} (limit)\n"
        f"TTL: {ttl_seconds}s — fills on touch or cancels."
    )


def limit_ttl_expired(trade_ref: str, instrument: str, limit_price: float,
                      via_grace: bool = False):
    """Filter #27 live: pending limit didn't fill within TTL.

    Two paths produce this:
    - Normal (via_grace=False): broker fired ORDER_DELETE, EA wrote
      cancelled_orders.json, pending_monitor cancel branch caught it. Healthy.
    - Grace fallback (via_grace=True): broker silently auto-expired without
      sending an ORDER_DELETE event. Fix B's TTL+60s grace path resolved
      the row. **This indicates a broker reliability issue** and operator
      should notice the cumulative pattern (high grace-fallback rate =
      degrading broker). M10: distinct suffix on Telegram so the two paths
      are visible from the phone, no SSH needed.

    See [[bias-filter-net-negative]] context: today's GD-MI-1e53d69b
    silent-expire was the trigger event for surfacing this distinction.
    """
    fmt = ".2f" if "XAU" in instrument else ".4f"
    if via_grace:
        send(
            f"⏱ <b>LIMIT EXPIRED</b> (grace fallback)\n"
            f"{trade_ref}\n"
            f"{instrument} did not fill at ${limit_price:{fmt}} — broker silent expire.\n"
            f"Fix B / TTL+60s path resolved row. Investigate if rate climbs."
        )
    else:
        send(
            f"⏱ <b>LIMIT EXPIRED</b>\n"
            f"{trade_ref}\n"
            f"{instrument} did not fill at ${limit_price:{fmt}} — cancelled."
        )


def bad_open_price_persistent(trade_ref: str, instrument: str, ticket: str,
                               intended_limit: float, bad_cycles: int,
                               raw_value):
    """Filter #27 / M13: open_price field has been missing/zero/None for N
    consecutive monitor cycles. H4 protects against transient DWX mid-write
    races, but persistent bad data means EA bug, file corruption, or stuck
    state. After N cycles (default 5 = ~2.5 min), fire alert + force-cancel.

    The pending row will be force-cancelled (broker-side) and marked
    exit_reason='LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED' so operator can
    investigate without losing the trade ledger trail. One-shot — caller
    must throttle (set per-ticket counter to sentinel after escalation)."""
    fmt = ".2f" if "XAU" in instrument else ".4f"
    send(
        f"🐛 <b>BAD OPEN_PRICE PERSISTENT</b>\n"
        f"{trade_ref}\n"
        f"{instrument} ticket={ticket} @ ${intended_limit:{fmt}}\n"
        f"open_price=<code>{raw_value!r}</code> for {bad_cycles} cycles "
        f"(~{bad_cycles * 30}s).\n"
        f"Force-cancelling pending order. Investigate DWX/EA state."
    )


def limit_orphan_warn(trade_ref: str, instrument: str, ticket: str,
                       intended_limit: float, age_seconds: int):
    """Filter #27 live: pending-order ticket can't be found in any DWX file.

    Fires once per ticket (caller is responsible for throttling — typically the
    pending_order_monitor's _orphan_alerted set). Indicates a broker silently
    auto-cancelled the order without a TRADE_TRANSACTION_ORDER_DELETE event,
    OR a DWX file-write race we haven't recovered from yet. Pending_monitor
    grace fallback (60s past TTL) will resolve cleanly; this alert ensures
    we hear about it within 30s of detection rather than after manual grep."""
    fmt = ".2f" if "XAU" in instrument else ".4f"
    send(
        f"⚠️ <b>LIMIT ORPHAN</b>\n"
        f"{trade_ref}\n"
        f"{instrument} ticket={ticket} @ ${intended_limit:{fmt}}\n"
        f"Not in pending/open/cancelled DWX files (age {age_seconds}s).\n"
        f"Grace fallback at TTL+60s will mark TTL_EXPIRED if unresolved."
    )


def orphan_adopted(trade_ref: str, broker_id: str, instrument: str, side: str,
                   units: int, entry_price: float, sl: float, tp: float):
    """Alert when the orphan reconciler adopts an untracked broker position.
    Indicates a bug somewhere upstream — investigate logs immediately."""
    fmt = ".2f" if "XAU" in instrument else ".4f"
    send(
        f"🚨 <b>ORPHAN ADOPTED</b>\n"
        f"Broker had position not in DB!\n"
        f"{trade_ref} (broker_id={broker_id})\n"
        f"{instrument} {side} {units} units @ ${entry_price:{fmt}}\n"
        f"SL: ${sl:{fmt}} | TP: ${tp:{fmt}}\n"
        f"Investigate logs — execute_signal likely raised before persistence."
    )


def daily_recon(system: str, date_str: str, total_trades: int, orphans_adopted: int,
                db_insert_failed: int, journal_errors: int, net_pnl: float,
                exit_ambiguous: int = 0,
                limit_placed: int = 0, limit_filled: int = 0,
                limit_ttl_expired: int = 0, limit_orphan: int = 0,
                limit_bad_open_price: int = 0):
    """Daily reconciliation summary at 00:00 UTC. Numbers >0 for orphans/errors/
    exit_ambiguous are red flags requiring investigation.

    exit_ambiguous: count of EXIT_AMBIGUOUS events. The Macro phantom-fill fix
    logs one whenever a position vanishes from open_orders.json without a
    matching closed_orders.json entry. Brief race = expected (small numbers).
    Sustained = DWX EA broken; investigate.

    O3 — Filter #27 lifecycle counters (default 0 so non-limit-shipped backends
    pass them as zero and the line stays compact):
        limit_placed:          broker accepted the pending order
        limit_filled:          pending fill detected by pending_order_monitor
        limit_ttl_expired:     clean cancel (broker fired ORDER_DELETE OR Fix B grace fallback)
        limit_orphan:          within-grace orphan warn (M8)
        limit_bad_open_price:  M13 force-cancel escalation (DWX wrote bad data ≥5 cycles)

    Fill rate = limit_filled / limit_placed (only printed when limit_placed > 0).
    Orphan rate / bad-open-price are flagged in the status line if non-zero.
    """
    flags = []
    if orphans_adopted > 0:
        flags.append(f"⚠️ {orphans_adopted} orphans")
    if db_insert_failed > 0:
        flags.append(f"⚠️ {db_insert_failed} DB INSERT fails")
    if journal_errors > 0:
        flags.append(f"⚠️ {journal_errors} journal errors")
    if exit_ambiguous > 0:
        flags.append(f"⚠️ {exit_ambiguous} exit-ambiguous")
    if limit_orphan > 0:
        flags.append(f"⚠️ {limit_orphan} limit-orphans")
    if limit_bad_open_price > 0:
        flags.append(f"🐛 {limit_bad_open_price} bad-open-price")
    flag_str = " | ".join(flags) if flags else "✅ clean"

    body = [
        f"📊 <b>Daily Recon — {system} — {date_str}</b>",
        f"Trades: {total_trades}",
        f"Net P&L: ${net_pnl:+.2f}",
    ]
    # Only render the Filter #27 line when at least one limit event happened
    # this day — keeps the message compact for non-limit-shipped backends.
    if limit_placed > 0 or limit_filled > 0 or limit_ttl_expired > 0:
        fill_rate = (limit_filled / limit_placed * 100) if limit_placed else 0.0
        body.append(
            f"Filter #27: placed={limit_placed} filled={limit_filled} "
            f"expired={limit_ttl_expired} (fill rate {fill_rate:.0f}%)"
        )
    body.append(f"Status: {flag_str}")

    send("\n".join(body))
