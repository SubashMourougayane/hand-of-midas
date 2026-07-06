"""HTML message formatters for the Hand of Midas Telegram notifier.

Every function returns a Telegram-HTML string (parse_mode=HTML). Templates were
reviewed + approved by the user 2026-07-06. Numbers are formatted defensively —
any None renders as "—" rather than crashing the sender.
"""
from __future__ import annotations

from typing import Any

# Contract size per symbol root (for $ risk estimate on entries).
_CONTRACT = {"XAUUSD": 100.0, "BRENT": 1000.0, "EURUSD": 100_000.0,
             "GBPUSD": 100_000.0, "USDJPY": 100_000.0}


def _sym(symbol: str | None) -> str:
    return (symbol or "").replace(".ecn", "").replace(".ECN", "") or "?"


def _contract(symbol: str | None) -> float:
    return _CONTRACT.get(_sym(symbol), 100.0)


def _f(v: Any, nd: int = 2) -> str:
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _money(v: Any, nd: int = 2) -> str:
    try:
        x = float(v)
        return f"{'+' if x >= 0 else '−'}${abs(x):,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _r(v: Any) -> str:
    try:
        x = float(v)
        return f"{'+' if x >= 0 else ''}{x:.2f}R"
    except (TypeError, ValueError):
        return "—"


def _side_label(side: Any) -> tuple[str, str]:
    """Return (emoji, word) for a numeric side."""
    try:
        s = int(side)
    except (TypeError, ValueError):
        s = 0
    return ("🟢", "LONG") if s > 0 else ("🔴", "SHORT")


def _held(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    m = int(minutes)
    h, mm = divmod(m, 60)
    return f"{h}h {mm:02d}m" if h else f"{mm}m"


def _leg_short(leg: str | None) -> str:
    if not leg:
        return "?"
    if "_a" in leg or leg.endswith("a"):
        return "A"
    if "_d" in leg or leg.endswith("d"):
        return "D"
    return leg


# ── event templates ─────────────────────────────────────────────────────────

def entry(t: dict) -> str:
    emoji, word = _side_label(t.get("side"))
    sym = _sym(t.get("symbol"))
    entry_px = t.get("entry_price")
    sl = t.get("stop_price")
    tp = t.get("take_profit_price")
    lots = t.get("qty_lots")
    risk_units = t.get("risk_units")
    contract = _contract(t.get("symbol"))
    # $ risk = stop distance × lots × contract
    risk_usd = None
    try:
        if lots and risk_units:
            risk_usd = abs(float(risk_units)) * float(lots) * contract
    except (TypeError, ValueError):
        pass
    # R:R
    rr = None
    try:
        if entry_px is not None and sl is not None and tp is not None and float(entry_px) != float(sl):
            rr = abs((float(tp) - float(entry_px)) / (float(entry_px) - float(sl)))
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    sl_pts = tp_pts = None
    try:
        sl_pts = float(sl) - float(entry_px)
        tp_pts = float(tp) - float(entry_px)
    except (TypeError, ValueError):
        pass
    lines = [
        f"{emoji} <b>{word} · {sym}</b>   <code>#{t.get('broker_ticket', '—')}</code>",
        f"<b>ENTRY</b> filled @ <code>{_f(entry_px)}</code>",
        "",
        f"<code>SL   </code> {_f(sl)}" + (f"   <code>({sl_pts:+.1f} pts)</code>" if sl_pts is not None else ""),
        f"<code>TP   </code> {_f(tp)}" + (f"   <code>({tp_pts:+.1f} pts)</code>" if tp_pts is not None else ""),
        f"<code>Size </code> {_f(lots)} lot   <code>R:R </code> {_f(rr, 1) if rr is not None else '—'}",
        f"<code>Risk </code> {('$'+_f(risk_usd,0)) if risk_usd is not None else '—'}   <code>Leg </code> {_leg_short(t.get('leg'))}",
    ]
    return "\n".join(lines)


def partial(t: dict) -> str:
    emoji, word = _side_label(t.get("side"))
    sym = _sym(t.get("symbol"))
    booked = t.get("booked_usd")
    entry_px = t.get("entry_price")
    tp = t.get("take_profit_price")
    remainder = t.get("remainder_lots")
    return "\n".join([
        f"💰 <b>PARTIAL TP +1R</b>   <code>#{t.get('broker_ticket', '—')}</code>",
        f"{word} · {sym}",
        "",
        f"<code>Booked  </code> <b>{_money(booked)}</b>  (0.5R locked)" if booked is not None
        else "<code>Booked  </code> +1R locked",
        f"<code>SL      </code> → <b>BE</b> {_f(entry_px)}",
        f"<code>Runner  </code> {_f(remainder) if remainder is not None else 'remainder'} lot toward TP {_f(tp)}",
        "",
        "<i>remainder now risk-free</i>",
    ])


_CLOSE_EMOJI = {
    "TP": "✅", "EXIT_TP": "✅",
    "SL": "🛑", "EXIT_SL": "🛑",
    "SL_BE": "⚖️", "EXIT_SL_BE": "⚖️",
    "TIMEOUT": "⏱", "EXIT_TIMEOUT": "⏱",
    "BROKER_CLOSED": "🔻", "EXIT_BROKER_CLOSED": "🔻",
}
_CLOSE_WORD = {
    "TP": "TP HIT", "SL": "STOP", "SL_BE": "BREAKEVEN",
    "TIMEOUT": "TIMEOUT", "BROKER_CLOSED": "BROKER CLOSED",
}


def close(t: dict) -> str:
    reason = str(t.get("exit_reason") or "").replace("EXIT_", "")
    emoji = _CLOSE_EMOJI.get(reason, "◻️")
    word = _CLOSE_WORD.get(reason, reason or "CLOSED")
    _, side_word = _side_label(t.get("side"))
    sym = _sym(t.get("symbol"))
    entry_px = t.get("entry_price")
    exit_px = t.get("exit_price") or t.get("broker_exit_price")
    # total R = partial banked + remainder net_r (mirror dashboard fix)
    net_r = t.get("net_r")
    total_r = net_r
    try:
        if t.get("partial_taken") and t.get("partial_r") is not None and net_r is not None:
            total_r = float(net_r) + float(t.get("partial_r"))
    except (TypeError, ValueError):
        total_r = net_r
    usd = t.get("broker_net_usd")
    held = t.get("held_minutes")
    ptp = "   PTP +0.5R" if t.get("partial_taken") else ""
    balance = t.get("balance")
    lines = [
        f"{emoji} <b>{word}</b>   <code>#{t.get('broker_ticket', '—')}</code>",
        f"{side_word} · {sym}",
        "",
        f"<code>Exit </code> {_f(exit_px)}  (entry {_f(entry_px)})",
        f"<code>Net  </code> <b>{_r(total_r)}</b>   <code>$ </code> <b>{_money(usd)}</b>{ptp}",
        f"<code>Held </code> {_held(held)}",
    ]
    if balance is not None:
        lines.append(f"\n<i>balance → ${_f(balance, 2)}</i>")
    return "\n".join(lines)


def adoption(tickets: list[dict]) -> str:
    lines = ["♻️ <b>Restart — positions adopted</b>"]
    if not tickets:
        lines.append("<i>flat — no open positions</i>")
    else:
        for t in tickets:
            _, word = _side_label(t.get("side"))
            lines.append(f"<code>#{t.get('broker_ticket','—')}</code> {word}  {_f(t.get('qty_lots'))}")
        lines.append("<i>hold-cap seeded from true age · managed</i>")
    return "\n".join(lines)


def anomaly(event_type: str, t: dict) -> str:
    label = {
        "PARTIAL_TP_ORPHANED": "ORPHANED REMAINDER",
        "PARTIAL_TP_SAFE_CLOSED": "PARTIAL SAFE-CLOSED",
        "PARTIAL_TP_MODIFY_FAILED": "SL→BE MODIFY FAILED",
        "PARTIAL_TP_CLOSE_FAILED": "PARTIAL CLOSE FAILED",
        "TIMEOUT_CLOSE_FAILED": "TIMEOUT CLOSE FAILED",
    }.get(event_type, event_type)
    return "\n".join([
        f"🚨 <b>{label}</b>   <code>#{t.get('broker_ticket', '—')}</code>",
        f"<i>{t.get('note', 'manual check required — position may still be open at broker')}</i>",
    ])
