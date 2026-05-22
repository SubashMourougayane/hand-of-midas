"""Telegram notifications for Hand Of Midas."""
import os
import threading
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def send(message: str):
    """Send a Telegram notification (non-blocking)."""
    threading.Thread(target=_send, args=(message,), daemon=True).start()


def _send(message: str):
    try:
        httpx.post(API_URL, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
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


def error(message: str):
    send(f"⚠️ <b>ERROR</b>\n{message}")
