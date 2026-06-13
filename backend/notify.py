"""Telegram notifications for Hand Of Midas."""
import os
import threading
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def send(message: str):
    """Send a Telegram notification (non-blocking)."""
    threading.Thread(target=_send, args=(message,), daemon=True).start()


def _send(message: str):
    try:
        httpx.post(API_URL, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
    except Exception:
        pass


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
                exit_ambiguous: int = 0):
    """Daily reconciliation summary at 00:00 UTC. Numbers >0 for orphans/errors/
    exit_ambiguous are red flags requiring investigation.

    exit_ambiguous: count of EXIT_AMBIGUOUS events. The Macro phantom-fill fix
    logs one whenever a position vanishes from open_orders.json without a
    matching closed_orders.json entry. Brief race = expected (small numbers).
    Sustained = DWX EA broken; investigate.
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
    flag_str = " | ".join(flags) if flags else "✅ clean"

    send(
        f"📊 <b>Daily Recon — {system} — {date_str}</b>\n"
        f"Trades: {total_trades}\n"
        f"Net P&L: ${net_pnl:+.2f}\n"
        f"Status: {flag_str}"
    )
