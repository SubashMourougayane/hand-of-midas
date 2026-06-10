"""Trade Postmortem — Deterministic data gatherer.

Pulls a closed trade's full timeline from the DB + DWX MT5 files and writes
a markdown postmortem to docs/trades/<trade_ref>.md. No LLM, no analysis —
this is the FACTS layer. The trade-postmortem skill reads the output and
adds the JUDGMENT layer on top.

Usage:
    python scripts/postmortem.py GD-MI-cce2a254
    python scripts/postmortem.py --latest        # most recently closed
    python scripts/postmortem.py --since 1h      # all trades closed in last hour

What this script computes (all from real data, no heuristics):
- Trade levels (entry, SL, TP, after BE if armed)
- Trade timeline (entry / BE armed / exit) with IST/UTC/server timestamps
- M3 price journey through the trade window
- MFE (max favorable excursion) and MAE (max adverse excursion)
- BE trigger detection (was 50% TP reached?)
- TP-after-exit check (would TP have hit if we held?)
- DB ↔ broker P&L sanity check (catches phantom-fill bugs like GD-MI-cce2a254)
- Journal events for the trade (chronological, flagged for anomalies)
- Counterfactual scenarios: BE-stop hit / SL hit / TP hit / held-to-bottom

Output: docs/trades/<trade_ref>.md with structured sections the skill can extend.
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make repo importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(REPO / ".env")

# DWX directory (default macOS path; override via env on Windows VPS)
DWX_DIR = os.getenv("DWX_DIR", os.path.expanduser(
    "~/Library/Application Support/net.metaquotes.wine.metatrader5/"
    "drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
))

# Trade-ref prefix → (system_label, instrument, lot_size_divisor, m3_filename)
SYSTEM_MAP = {
    "GD-AL-": ("Gold Macro",  "XAU_USD", 100,  "bars_XAUUSD_ecn_M3.json"),
    "GD-MI-": ("Gold Micro",  "XAU_USD", 100,  "bars_XAUUSD_ecn_M3.json"),
    "OIL-AS-": ("Oil Macro",  "BCO_USD", 1000, "bars_BRENT_ecn_M3.json"),
    "OIL-MI-": ("Oil Micro",  "BCO_USD", 1000, "bars_BRENT_ecn_M3.json"),
}

DB_URL = os.getenv("DATABASE_URL", "postgresql://subash@localhost:5432/golddigger")


def db_conn():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)


def system_for_trade_ref(trade_ref: str):
    for prefix, info in SYSTEM_MAP.items():
        if trade_ref.startswith(prefix):
            return info
    return ("Unknown", "?", 1, None)


def fetch_trade(trade_ref: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM gd_trades WHERE trade_ref = %s", (trade_ref,))
        row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def fetch_journal(trade_ref: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT timestamp, event_type, price, context "
            "FROM gd_journal WHERE trade_ref = %s ORDER BY timestamp ASC",
            (trade_ref,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def fetch_recent_trades_for_pattern(trade_ref: str, prefix: str, n: int = 10):
    """Last n closed trades matching the same prefix (for pattern comparison)."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT trade_ref, side, entry_price, exit_price, sl_price, tp_price, "
            "       pnl_usd, exit_reason, entry_time, exit_time "
            "FROM gd_trades "
            "WHERE trade_ref LIKE %s "
            "  AND trade_ref != %s "
            "  AND exit_time IS NOT NULL "
            "ORDER BY exit_time DESC LIMIT %s",
            (prefix + "%", trade_ref, n),
        )
        return [dict(r) for r in cur.fetchall()]


def load_m3_bars(m3_filename: str):
    """Load M3 bars from local DWX file. Returns [] if file missing."""
    if not m3_filename:
        return []
    path = os.path.join(DWX_DIR, m3_filename)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def parse_dwx_time(s: str) -> datetime:
    """DWX writes server time as 'YYYY.MM.DD HH:MM:SS' (GMT+3)."""
    return datetime.strptime(s, "%Y.%m.%d %H:%M:%S")


def server_to_utc(server_dt: datetime) -> datetime:
    """MT5 server is GMT+3."""
    return (server_dt - timedelta(hours=3)).replace(tzinfo=timezone.utc)


def utc_to_ist(utc_dt: datetime) -> datetime:
    return utc_dt + timedelta(hours=5, minutes=30)


def filter_bars_in_window(bars, start_utc: datetime, end_utc: datetime, pad_min: int = 6):
    """Return M3 bars (parsed timestamps) within [start - pad, end + pad]."""
    s = start_utc - timedelta(minutes=pad_min)
    e = end_utc + timedelta(minutes=pad_min)
    out = []
    for b in bars:
        try:
            srv = parse_dwx_time(b["time"])
            utc = server_to_utc(srv)
            if s <= utc <= e:
                out.append({"server": srv, "utc": utc, **b})
        except Exception:
            continue
    return out


def compute_excursions(bars, entry_price: float, side: str):
    """Returns dict with mfe, mae, mfe_at, mae_at — all referenced from entry."""
    if not bars:
        return {"mfe_per_oz": 0, "mae_per_oz": 0, "mfe_at": None, "mae_at": None,
                "highest": None, "lowest": None}
    highest_bar = max(bars, key=lambda b: b["high"])
    lowest_bar = min(bars, key=lambda b: b["low"])
    if side.upper() == "SHORT":
        mfe = entry_price - lowest_bar["low"]
        mae = highest_bar["high"] - entry_price
        mfe_at = lowest_bar
        mae_at = highest_bar
    else:
        mfe = highest_bar["high"] - entry_price
        mae = entry_price - lowest_bar["low"]
        mfe_at = highest_bar
        mae_at = lowest_bar
    return {
        "mfe_per_oz": mfe,
        "mae_per_oz": mae,
        "mfe_at": mfe_at,
        "mae_at": mae_at,
        "highest": highest_bar,
        "lowest": lowest_bar,
    }


def compute_50pct_tp_level(entry: float, tp: float):
    return entry - (entry - tp) * 0.5  # works for both LONG/SHORT given correct sign of (entry - tp)


def find_first_bar_crossing(bars, side: str, entry: float, tp: float):
    """For a SHORT, the bar where low <= 50%TP. For LONG, high >= 50%TP."""
    half = compute_50pct_tp_level(entry, tp)
    for b in bars:
        if side.upper() == "SHORT" and b["low"] <= half:
            return b, half
        if side.upper() == "LONG" and b["high"] >= half:
            return b, half
    return None, half


def find_tp_hit_bar(bars, side: str, tp: float):
    for b in bars:
        if side.upper() == "SHORT" and b["low"] <= tp:
            return b
        if side.upper() == "LONG" and b["high"] >= tp:
            return b
    return None


def find_sl_hit_bar(bars, side: str, sl: float):
    for b in bars:
        if side.upper() == "SHORT" and b["high"] >= sl:
            return b
        if side.upper() == "LONG" and b["low"] <= sl:
            return b
    return None


def fmt_ts(dt: datetime, tz_name: str = "UTC"):
    if dt is None:
        return "—"
    if tz_name == "IST":
        dt = utc_to_ist(dt) if dt.tzinfo else utc_to_ist(dt.replace(tzinfo=timezone.utc))
    elif tz_name == "server":
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return (dt.astimezone(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def render_markdown(trade: dict, journal: list, m3_window: list, peers: list,
                    excursions: dict, tp_after_exit, fifty_pct_bar, fifty_pct_level: float,
                    system_label: str, instrument: str) -> str:
    """Build the deterministic markdown postmortem."""
    tr = trade["trade_ref"]
    side = trade["side"]
    units = trade.get("units") or 0
    entry = float(trade["entry_price"])
    sl = float(trade["sl_price"]) if trade.get("sl_price") else None
    tp = float(trade["tp_price"]) if trade.get("tp_price") else None
    exit_price = float(trade["exit_price"]) if trade.get("exit_price") else None
    pnl_usd = float(trade["pnl_usd"]) if trade.get("pnl_usd") is not None else None

    # Times — DB stores TIMESTAMPTZ as aware UTC
    entry_t = trade["entry_time"]
    exit_t = trade["exit_time"]

    fmt_price = lambda p: f"${p:.2f}" if "XAU" in instrument else f"${p:.4f}"

    lines = []
    lines.append(f"# Postmortem — {tr}")
    lines.append("")
    lines.append(f"**System**: {system_label}")
    lines.append(f"**Instrument**: {instrument}")
    lines.append(f"**Strategy**: {trade.get('strategy', '?')}")
    lines.append(f"**Side**: {side} {units} units")
    lines.append(f"**Entry**: {fmt_price(entry)}  |  **SL**: {fmt_price(sl) if sl else '—'}  |  **TP**: {fmt_price(tp) if tp else '—'}")
    if exit_price is not None:
        lines.append(f"**Exit**: {fmt_price(exit_price)}  |  **Exit reason**: {trade.get('exit_reason', '?')}  |  **P&L (DB)**: ${pnl_usd:+.2f}")
    if entry_t and exit_t:
        duration = exit_t - entry_t
        lines.append(f"**Duration**: {duration}")
    lines.append("")

    # Risk math
    if sl and tp:
        risk_per_unit = abs(entry - sl)
        reward_per_unit = abs(tp - entry)
        rr = (reward_per_unit / risk_per_unit) if risk_per_unit > 0 else 0
        lines.append("## Risk Math")
        lines.append("")
        lines.append(f"- Risk: {fmt_price(risk_per_unit)} per unit × {units} = ${risk_per_unit * units:.2f} max loss")
        lines.append(f"- Reward: {fmt_price(reward_per_unit)} per unit × {units} = ${reward_per_unit * units:.2f} max gain")
        lines.append(f"- R:R: {rr:.2f}:1")
        lines.append(f"- 50% to TP level (BE trigger): {fmt_price(fifty_pct_level)}")
        lines.append("")

    # Timeline
    lines.append("## Timeline")
    lines.append("")
    lines.append(f"| Event | UTC | IST | Server (GMT+3) |")
    lines.append(f"|---|---|---|---|")
    if entry_t:
        e_utc = entry_t.astimezone(timezone.utc) if entry_t.tzinfo else entry_t.replace(tzinfo=timezone.utc)
        lines.append(f"| ENTRY | {fmt_ts(e_utc, 'UTC')} | {fmt_ts(e_utc, 'IST')} | {fmt_ts(e_utc, 'server')} |")
    # BE event from journal
    be_event = next((e for e in journal if e["event_type"] == "BREAK_EVEN"), None)
    if be_event:
        be_utc = be_event["timestamp"].astimezone(timezone.utc) if be_event["timestamp"].tzinfo else be_event["timestamp"].replace(tzinfo=timezone.utc)
        lines.append(f"| BREAK_EVEN armed | {fmt_ts(be_utc, 'UTC')} | {fmt_ts(be_utc, 'IST')} | {fmt_ts(be_utc, 'server')} |")
    if exit_t:
        x_utc = exit_t.astimezone(timezone.utc) if exit_t.tzinfo else exit_t.replace(tzinfo=timezone.utc)
        lines.append(f"| EXIT | {fmt_ts(x_utc, 'UTC')} | {fmt_ts(x_utc, 'IST')} | {fmt_ts(x_utc, 'server')} |")
    lines.append("")

    # Excursions
    lines.append("## Excursions (from M3 bars during trade window)")
    lines.append("")
    if excursions["highest"]:
        lines.append(f"- **MFE** (max favorable): {fmt_price(excursions['mfe_per_oz'])}/unit × {units} = ${excursions['mfe_per_oz'] * units:+.2f}")
        if excursions["mfe_at"]:
            mfe_b = excursions["mfe_at"]
            lines.append(f"  - At server {mfe_b['time']} ({fmt_price(mfe_b['low'] if side == 'SHORT' else mfe_b['high'])})")
        lines.append(f"- **MAE** (max adverse): {fmt_price(excursions['mae_per_oz'])}/unit × {units} = ${excursions['mae_per_oz'] * units:+.2f}")
        if excursions["mae_at"]:
            mae_b = excursions["mae_at"]
            lines.append(f"  - At server {mae_b['time']} ({fmt_price(mae_b['high'] if side == 'SHORT' else mae_b['low'])})")
        lines.append("")

        if sl and excursions["mae_per_oz"] < abs(entry - sl):
            distance = abs(entry - sl) - excursions["mae_per_oz"]
            lines.append(f"  → MAE never threatened original SL (was {fmt_price(distance)} away)")
        lines.append("")
    else:
        lines.append("- No M3 bar data available for the trade window.")
        lines.append("")

    # 50% TP / BE trigger reached?
    lines.append("## BE trigger (50% to TP)")
    lines.append("")
    if fifty_pct_bar:
        cross_utc = server_to_utc(parse_dwx_time(fifty_pct_bar["time"]))
        lines.append(f"- 50% TP level **{fmt_price(fifty_pct_level)}** was crossed")
        lines.append(f"- First crossing bar: server {fifty_pct_bar['time']} (UTC {fmt_ts(cross_utc, 'UTC')}, IST {fmt_ts(cross_utc, 'IST')})")
        lines.append(f"- Bar high/low: {fmt_price(fifty_pct_bar['high'])} / {fmt_price(fifty_pct_bar['low'])}")
        if be_event:
            be_utc = be_event["timestamp"].astimezone(timezone.utc) if be_event["timestamp"].tzinfo else be_event["timestamp"].replace(tzinfo=timezone.utc)
            delay = (be_utc - cross_utc).total_seconds()
            lines.append(f"- BREAK_EVEN journal event fired {delay:.0f}s after crossing — {'within expected 60s polling' if 0 < delay <= 90 else '⚠️ unexpectedly slow' if delay > 90 else 'before crossing (anomaly)'}")
        else:
            lines.append("- ⚠️ NO BREAK_EVEN journal event found — BE may not have armed (bug?)")
    else:
        lines.append(f"- 50% TP level **{fmt_price(fifty_pct_level)}** never reached during trade")
    lines.append("")

    # TP-after-exit
    lines.append("## What happened AFTER exit?")
    lines.append("")
    if tp_after_exit and tp:
        tp_utc = server_to_utc(parse_dwx_time(tp_after_exit["time"]))
        lines.append(f"- TP level {fmt_price(tp)} was reached at server {tp_after_exit['time']} (UTC {fmt_ts(tp_utc, 'UTC')})")
        if exit_t:
            x_utc = exit_t.astimezone(timezone.utc) if exit_t.tzinfo else exit_t.replace(tzinfo=timezone.utc)
            delta = (tp_utc - x_utc).total_seconds() / 60
            lines.append(f"- That's {delta:+.1f} minutes from our exit (negative = TP was reached BEFORE we exited)")
    elif tp:
        lines.append(f"- TP level {fmt_price(tp)} was NEVER reached in the M3 bar window we analyzed")
    lines.append("")

    # Counterfactuals
    if sl and tp and units:
        lines.append("## Counterfactual P&L scenarios")
        lines.append("")
        lines.append(f"| Scenario | Per-unit | Total |")
        lines.append(f"|---|---:|---:|")
        if side.upper() == "SHORT":
            lines.append(f"| If hit original SL | {fmt_price(sl - entry)} | ${(sl - entry) * units * -1:+.2f} |")
            lines.append(f"| If hit TP | {fmt_price(entry - tp)} | ${(entry - tp) * units:+.2f} |")
            if excursions["lowest"]:
                lowest = excursions["lowest"]["low"]
                lines.append(f"| If exited at MFE bottom | {fmt_price(entry - lowest)} | ${(entry - lowest) * units:+.2f} |")
        else:
            lines.append(f"| If hit original SL | {fmt_price(entry - sl)} | ${(entry - sl) * units * -1:+.2f} |")
            lines.append(f"| If hit TP | {fmt_price(tp - entry)} | ${(tp - entry) * units:+.2f} |")
            if excursions["highest"]:
                highest = excursions["highest"]["high"]
                lines.append(f"| If exited at MFE top | {fmt_price(highest - entry)} | ${(highest - entry) * units:+.2f} |")
        if pnl_usd is not None:
            lines.append(f"| **ACTUAL (DB)** | — | **${pnl_usd:+.2f}** |")
        lines.append("")

    # Sanity check: DB ↔ broker
    lines.append("## Bug-smell checklist (deterministic)")
    lines.append("")
    smells = []
    # 1. Was exit_price wildly different from sl or tp?
    if exit_price is not None and sl and tp:
        d_sl = abs(exit_price - sl)
        d_tp = abs(exit_price - tp)
        # SL exits should be near sl_price (within slippage); same for TP
        if trade.get("exit_reason") == "SL" and d_sl > 5 * (1 if "XAU" in instrument else 0.05):
            smells.append(f"⚠️ exit_reason=SL but exit_price ({fmt_price(exit_price)}) is far from sl_price ({fmt_price(sl)}) — possible misattribution")
        if trade.get("exit_reason") == "TP" and d_tp > 5 * (1 if "XAU" in instrument else 0.05):
            smells.append(f"⚠️ exit_reason=TP but exit_price ({fmt_price(exit_price)}) is far from tp_price ({fmt_price(tp)}) — possible misattribution")
    # 2. Did journal contain EXIT_AMBIGUOUS?
    if any(e["event_type"] == "EXIT_AMBIGUOUS" for e in journal):
        smells.append("⚠️ Journal has EXIT_AMBIGUOUS events — heuristic fallback fired (DWX OnTradeTransaction may not have written closed_orders.json)")
    # 3. Did P&L sign match exit_reason?
    if pnl_usd is not None and trade.get("exit_reason"):
        if trade["exit_reason"] == "TP" and pnl_usd <= 0:
            smells.append(f"⚠️ exit_reason=TP but pnl_usd is non-positive (${pnl_usd:+.2f}) — investigate")
        if trade["exit_reason"] == "SL" and pnl_usd >= 0 and excursions.get("mae_per_oz", 0) > 0:
            # Note: SL exits CAN be slightly positive when BE armed and BE-stop hit. Don't flag.
            pass
    # 4. Was P&L = (entry - exit) × units within 1% tolerance?
    if exit_price is not None and pnl_usd is not None and units:
        expected = (entry - exit_price) * units if side.upper() == "SHORT" else (exit_price - entry) * units
        if abs(expected - pnl_usd) > max(1.0, abs(pnl_usd) * 0.01):
            smells.append(f"⚠️ P&L math doesn't reconcile: stored {pnl_usd:+.2f} vs computed {expected:+.2f} from price levels")
    # 5. MFE wildly larger than realized P&L (possible BE-too-tight)
    if pnl_usd is not None and excursions.get("mfe_per_oz", 0) > 0 and units:
        mfe_total = excursions["mfe_per_oz"] * units
        if mfe_total > 100 and pnl_usd < mfe_total * 0.1:
            smells.append(f"ℹ️ MFE was ${mfe_total:+.2f} but we kept ${pnl_usd:+.2f} ({pnl_usd/mfe_total*100:.0f}% of peak). Note for BE-timing analysis.")

    if smells:
        for s in smells:
            lines.append(f"- {s}")
    else:
        lines.append("- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly")
    lines.append("")

    # Pattern vs recent trades
    lines.append("## Pattern vs recent peers")
    lines.append("")
    if peers:
        lines.append(f"Last {len(peers)} closed trades for {system_label}:")
        lines.append("")
        lines.append(f"| trade_ref | side | entry | exit | reason | P&L |")
        lines.append(f"|---|---|---:|---:|---|---:|")
        wins = sum(1 for p in peers if (p.get("pnl_usd") or 0) > 0)
        for p in peers[:10]:
            ep = float(p["entry_price"]) if p["entry_price"] else 0
            xp = float(p["exit_price"]) if p["exit_price"] else 0
            pp = float(p["pnl_usd"]) if p["pnl_usd"] is not None else 0
            lines.append(f"| {p['trade_ref']} | {p['side']} | {fmt_price(ep)} | {fmt_price(xp)} | {p.get('exit_reason','?')} | ${pp:+.2f} |")
        lines.append("")
        lines.append(f"Recent W/L: {wins}/{len(peers) - wins}")
        total_pnl = sum(float(p["pnl_usd"] or 0) for p in peers)
        lines.append(f"Recent net P&L (excluding this trade): ${total_pnl:+.2f}")
    else:
        lines.append("No peer trades to compare.")
    lines.append("")

    # Journal events
    lines.append("## Journal events (chronological)")
    lines.append("")
    if journal:
        lines.append(f"| timestamp (UTC) | event | price | context |")
        lines.append(f"|---|---|---:|---|")
        for e in journal:
            ts = e["timestamp"]
            ts_utc = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            ctx = e.get("context")
            if isinstance(ctx, dict):
                # Compact context
                ctx_str = ", ".join(f"{k}={v}" for k, v in list(ctx.items())[:6])
            else:
                ctx_str = str(ctx)[:100] if ctx else ""
            price_s = f"{e.get('price', '—'):.2f}" if e.get("price") else "—"
            lines.append(f"| {fmt_ts(ts_utc, 'UTC')} | {e['event_type']} | {price_s} | {ctx_str} |")
    else:
        lines.append("- No journal events for this trade.")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("_This file is the deterministic facts layer. The trade-postmortem skill appends judgment + analysis below this line._")
    lines.append("")

    return "\n".join(lines)


def gather_and_write(trade_ref: str) -> str:
    """Main entrypoint. Returns the path to the written postmortem."""
    trade = fetch_trade(trade_ref)
    if not trade:
        raise SystemExit(f"trade_ref {trade_ref} not found in gd_trades")
    if trade.get("exit_time") is None:
        raise SystemExit(f"trade_ref {trade_ref} is still OPEN (no exit_time). Postmortem only runs on closed trades.")

    system_label, instrument, lot_div, m3_filename = system_for_trade_ref(trade_ref)
    journal = fetch_journal(trade_ref)
    bars_all = load_m3_bars(m3_filename)

    # Window: from entry to exit, padded
    entry_t = trade["entry_time"].astimezone(timezone.utc) if trade["entry_time"].tzinfo else trade["entry_time"].replace(tzinfo=timezone.utc)
    exit_t = trade["exit_time"].astimezone(timezone.utc) if trade["exit_time"].tzinfo else trade["exit_time"].replace(tzinfo=timezone.utc)
    bars_window = filter_bars_in_window(bars_all, entry_t, exit_t, pad_min=10)

    entry_price = float(trade["entry_price"])
    side = trade["side"]
    excursions = compute_excursions(bars_window, entry_price, side)

    tp = float(trade["tp_price"]) if trade.get("tp_price") else None
    sl = float(trade["sl_price"]) if trade.get("sl_price") else None

    fifty_pct_bar, fifty_pct_level = (None, None)
    if tp is not None:
        fifty_pct_bar, fifty_pct_level = find_first_bar_crossing(bars_window, side, entry_price, tp)

    # Bars AFTER exit (next 30 min): did TP get hit?
    bars_after_exit = filter_bars_in_window(bars_all, exit_t, exit_t + timedelta(minutes=30), pad_min=0)
    tp_after_exit = find_tp_hit_bar(bars_after_exit, side, tp) if tp else None

    # Peers
    prefix = trade_ref.split("-", 2)[0] + "-" + trade_ref.split("-", 2)[1] + "-"
    peers = fetch_recent_trades_for_pattern(trade_ref, prefix, n=10)

    md = render_markdown(trade, journal, bars_window, peers, excursions,
                         tp_after_exit, fifty_pct_bar, fifty_pct_level,
                         system_label, instrument)

    out_dir = REPO / "docs" / "trades"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{trade_ref}.md"
    out_path.write_text(md)
    return str(out_path)


def latest_closed_trade():
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT trade_ref FROM gd_trades "
            "WHERE exit_time IS NOT NULL ORDER BY exit_time DESC LIMIT 1"
        )
        row = cur.fetchone()
    return dict(row)["trade_ref"] if row else None


def trades_since(duration_str: str):
    """duration_str like '1h', '30m', '2d'."""
    unit = duration_str[-1]
    n = int(duration_str[:-1])
    if unit == "h":
        delta = timedelta(hours=n)
    elif unit == "m":
        delta = timedelta(minutes=n)
    elif unit == "d":
        delta = timedelta(days=n)
    else:
        raise SystemExit(f"unknown duration unit '{unit}' (use h/m/d)")
    cutoff = datetime.now(timezone.utc) - delta
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT trade_ref FROM gd_trades "
            "WHERE exit_time IS NOT NULL AND exit_time >= %s "
            "ORDER BY exit_time ASC",
            (cutoff,),
        )
        return [dict(r)["trade_ref"] for r in cur.fetchall()]


def main():
    p = argparse.ArgumentParser(description="Build deterministic trade postmortems")
    p.add_argument("trade_ref", nargs="?", help="trade_ref like GD-MI-cce2a254")
    p.add_argument("--latest", action="store_true", help="postmortem the most recently closed trade")
    p.add_argument("--since", help="postmortem all trades closed in this window (e.g. 1h, 30m, 2d)")
    args = p.parse_args()

    refs: list[str] = []
    if args.latest:
        ref = latest_closed_trade()
        if not ref:
            raise SystemExit("no closed trades in DB")
        refs = [ref]
    elif args.since:
        refs = trades_since(args.since)
        if not refs:
            print(f"no closed trades in last {args.since}")
            return
    elif args.trade_ref:
        refs = [args.trade_ref]
    else:
        p.print_help()
        sys.exit(1)

    for ref in refs:
        try:
            path = gather_and_write(ref)
            print(f"✓ wrote {path}")
        except Exception as e:
            print(f"✗ {ref}: {e}")


if __name__ == "__main__":
    main()
