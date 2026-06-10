"""Trade Postmortem — Deterministic data gatherer (LOCAL ONLY).

Pulls a closed trade's full timeline from the VPS REST API + LOCAL DWX MT5
files, writes a markdown postmortem to docs/trades/<trade_ref>.md.

No LLM, no analysis — this is the FACTS layer. The trade-postmortem skill
reads the output and adds the JUDGMENT layer on top.

DESIGN: this script is meant to run on the user's local Mac, NOT on the VPS.
- All trade/journal data fetched via HTTPS to https://midas.subashtrades.in
- M3 bars come from local MT5's DWX directory (same JustMarkets feed as VPS)
- No DB connection, no SSH, nothing run remotely

Usage:
    python scripts/postmortem.py GD-MI-cce2a254
    python scripts/postmortem.py --latest        # most recently closed across all 4 systems
    python scripts/postmortem.py --since 1h      # all trades closed in last hour

What this script computes (all from real data, no heuristics):
- Trade levels (entry, SL, TP, after BE if armed)
- Trade timeline (entry / BE armed / exit) with IST/UTC/server timestamps
- M3 price journey through the trade window
- MFE (max favorable excursion) and MAE (max adverse excursion)
- BE trigger detection (was 50% TP reached?)
- TP-after-exit check (would TP have hit if we held?)
- Bug-smell scan (catches phantom-fill bugs like GD-MI-cce2a254)
- Journal events for the trade (chronological, flagged for anomalies)
- Counterfactual scenarios: BE-stop hit / SL hit / TP hit / held-to-MFE

Output: docs/trades/<trade_ref>.md with structured sections the skill can extend.
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# VPS REST endpoint — read-only, no auth needed for trades/journal/state
API_BASE = os.getenv("MIDAS_API_BASE", "https://midas.subashtrades.in")

# Local MT5 DWX directory (where THIS Mac's MT5 writes bar data)
# Same JustMarkets data feed as the VPS, just running on local MT5.
DWX_DIR = os.getenv("DWX_DIR", os.path.expanduser(
    "~/Library/Application Support/net.metaquotes.wine.metatrader5/"
    "drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
))

# Trade-ref prefix → (system_label, api_path_suffix, instrument, lot_size_divisor, m3_filename)
SYSTEM_MAP = {
    "GD-AL-": ("Gold Macro",  "gold",      "XAU_USD", 100,  "bars_XAUUSD_ecn_M3.json"),
    "GD-MI-": ("Gold Micro",  "micro",     "XAU_USD", 100,  "bars_XAUUSD_ecn_M3.json"),
    "OIL-AS-": ("Oil Macro",  "oil",       "BCO_USD", 1000, "bars_BRENT_ecn_M3.json"),
    "OIL-MI-": ("Oil Micro",  "oil-micro", "BCO_USD", 1000, "bars_BRENT_ecn_M3.json"),
}


# =============================================================================
# HTTP fetch helpers (no external deps)
# =============================================================================

def http_get(url: str, timeout: int = 15):
    """Fetch a URL, return parsed JSON. Raises on non-2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": "midas-postmortem/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        body = resp.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Some endpoints (e.g., gold journal/events) wrap in {"events": [...]}
        # Some return a bare list. Try to be helpful.
        return body


def fetch_trades(api_suffix: str, limit: int = 200):
    """Get trades for a system. Different routes return different shapes —
    handle both bare list and {"trades": [...]} wrapped form."""
    url = f"{API_BASE}/api/{api_suffix}/trades?limit={limit}"
    data = http_get(url)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("trades", [])
    return []


def fetch_journal(api_suffix: str, limit: int = 500):
    """Journal endpoint shape varies: gold uses /journal/events, the others use /journal."""
    if api_suffix == "gold":
        url = f"{API_BASE}/api/{api_suffix}/journal/events?limit={limit}"
    else:
        url = f"{API_BASE}/api/{api_suffix}/journal?limit={limit}"
    data = http_get(url)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("events", [])
    return []


def fetch_state(api_suffix: str):
    return http_get(f"{API_BASE}/api/{api_suffix}/state")


# =============================================================================
# Trade lookup
# =============================================================================

def system_for_trade_ref(trade_ref: str):
    for prefix, info in SYSTEM_MAP.items():
        if trade_ref.startswith(prefix):
            return prefix, info
    return None, ("Unknown", None, "?", 1, None)


def find_trade(trade_ref: str):
    """Look up a single trade across all 4 systems' /trades endpoints."""
    prefix, (label, api_suffix, instr, lot_div, m3) = system_for_trade_ref(trade_ref)
    if not api_suffix:
        return None, label, instr, lot_div, m3
    trades = fetch_trades(api_suffix, limit=500)
    for t in trades:
        if t.get("trade_ref") == trade_ref:
            return t, label, instr, lot_div, m3
    return None, label, instr, lot_div, m3


def find_journal_for_trade(trade_ref: str):
    """Pull journal events for the system that owns this trade and filter."""
    prefix, (label, api_suffix, instr, lot_div, m3) = system_for_trade_ref(trade_ref)
    if not api_suffix:
        return []
    events = fetch_journal(api_suffix, limit=500)
    # Some events have trade_ref="SYSTEM" (e.g. ERROR/CLEAN_SLATE_RESET) — skip those for per-trade view
    return [e for e in events if e.get("trade_ref") == trade_ref]


def latest_closed_trade():
    """Across all 4 systems, find the trade with the most recent exit_time."""
    best = None
    for prefix, (label, api_suffix, *_rest) in SYSTEM_MAP.items():
        try:
            trades = fetch_trades(api_suffix, limit=20)
        except Exception as e:
            print(f"  warning: {api_suffix} fetch failed: {e}", file=sys.stderr)
            continue
        for t in trades:
            if not t.get("exit_time"):
                continue
            if best is None or t["exit_time"] > best["exit_time"]:
                best = t
    return best.get("trade_ref") if best else None


def trades_since(duration_str: str):
    """Across all 4 systems, return trade_refs closed within the last duration."""
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
    refs = []
    for prefix, (label, api_suffix, *_rest) in SYSTEM_MAP.items():
        try:
            trades = fetch_trades(api_suffix, limit=50)
        except Exception:
            continue
        for t in trades:
            if not t.get("exit_time"):
                continue
            try:
                exit_t = datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00"))
                if exit_t.tzinfo is None:
                    exit_t = exit_t.replace(tzinfo=timezone.utc)
                if exit_t.astimezone(timezone.utc) >= cutoff:
                    refs.append((exit_t, t.get("trade_ref")))
            except Exception:
                continue
    refs.sort()
    return [r for _, r in refs]


def fetch_recent_peers(trade_ref: str, n: int = 10):
    """Last n closed trades for the same system (excluding the target)."""
    prefix, (label, api_suffix, *_rest) = system_for_trade_ref(trade_ref)
    if not api_suffix:
        return []
    trades = fetch_trades(api_suffix, limit=n + 5)
    closed = [t for t in trades if t.get("exit_time") and t.get("trade_ref") != trade_ref]
    return closed[:n]


# =============================================================================
# M3 bar handling (LOCAL MT5)
# =============================================================================

def load_m3_bars(m3_filename: str):
    if not m3_filename:
        return []
    path = os.path.join(DWX_DIR, m3_filename)
    if not os.path.exists(path):
        print(f"  warning: M3 file not found at {path} — excursion analysis will be limited", file=sys.stderr)
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  warning: M3 file unreadable ({e})", file=sys.stderr)
        return []


def parse_dwx_time(s: str) -> datetime:
    """DWX writes server time as 'YYYY.MM.DD HH:MM:SS' (GMT+3)."""
    return datetime.strptime(s, "%Y.%m.%d %H:%M:%S")


def server_to_utc(server_dt: datetime) -> datetime:
    return (server_dt - timedelta(hours=3)).replace(tzinfo=timezone.utc)


def utc_to_ist(utc_dt: datetime) -> datetime:
    return utc_dt + timedelta(hours=5, minutes=30)


def parse_iso(s: str) -> datetime:
    """Parse an ISO timestamp string into a tz-aware UTC datetime."""
    if s is None:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filter_bars_in_window(bars, start_utc: datetime, end_utc: datetime, pad_min: int = 6):
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


# =============================================================================
# Analysis
# =============================================================================

def compute_excursions(bars, entry_price: float, side: str):
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
    return entry - (entry - tp) * 0.5


def find_first_bar_crossing(bars, side: str, entry: float, tp: float):
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


def fmt_ts(dt: datetime, tz_name: str = "UTC"):
    if dt is None:
        return "—"
    if tz_name == "IST":
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return utc_to_ist(dt.astimezone(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    if tz_name == "server":
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return (dt.astimezone(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt.tzinfo else dt.strftime("%Y-%m-%d %H:%M:%S")


def render_markdown(trade: dict, journal: list, m3_window: list, peers: list,
                    excursions: dict, tp_after_exit, fifty_pct_bar, fifty_pct_level: float,
                    system_label: str, instrument: str) -> str:
    tr = trade["trade_ref"]
    side = trade["side"]
    units = trade.get("units") or 0
    entry = float(trade["entry_price"]) if trade.get("entry_price") else 0
    sl = float(trade["sl"] or trade.get("sl_price") or 0) if (trade.get("sl") or trade.get("sl_price")) else None
    tp = float(trade["tp"] or trade.get("tp_price") or 0) if (trade.get("tp") or trade.get("tp_price")) else None
    exit_price = float(trade.get("exit_price") or 0) if trade.get("exit_price") else None
    pnl_usd = float(trade["pnl_usd"]) if trade.get("pnl_usd") is not None else None

    entry_t = parse_iso(trade.get("entry_time"))
    exit_t = parse_iso(trade.get("exit_time"))

    is_xau = "XAU" in instrument
    fmt_price = lambda p: f"${p:.2f}" if is_xau else f"${p:.4f}"

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
        lines.append(f"**Duration**: {exit_t - entry_t}")
    lines.append("")

    # Risk math — use ORIGINAL SL (from entry) for R:R to reflect what the
    # strategy actually risked at signal time, not the BE-moved SL.
    osl = trade.get("_original_sl") or sl
    if osl and tp and entry:
        risk_per_unit = abs(entry - osl)
        reward_per_unit = abs(tp - entry)
        rr = (reward_per_unit / risk_per_unit) if risk_per_unit > 0 else 0
        lines.append("## Risk Math")
        lines.append("")
        if osl != sl and sl is not None:
            lines.append(f"- _Risk math computed from ORIGINAL SL ({fmt_price(osl)}); current stored sl_price is {fmt_price(sl)} after BE move._")
        lines.append(f"- Risk: {fmt_price(risk_per_unit)}/unit × {units} = ${risk_per_unit * units:.2f} max loss")
        lines.append(f"- Reward: {fmt_price(reward_per_unit)}/unit × {units} = ${reward_per_unit * units:.2f} max gain")
        lines.append(f"- R:R: {rr:.2f}:1")
        lines.append(f"- 50% to TP level (BE trigger): {fmt_price(fifty_pct_level)}")
        lines.append("")

    # Timeline
    lines.append("## Timeline")
    lines.append("")
    lines.append("| Event | UTC | IST | Server (GMT+3) |")
    lines.append("|---|---|---|---|")
    if entry_t:
        lines.append(f"| ENTRY | {fmt_ts(entry_t, 'UTC')} | {fmt_ts(entry_t, 'IST')} | {fmt_ts(entry_t, 'server')} |")
    be_event = next((e for e in journal if e.get("event_type") == "BREAK_EVEN"), None)
    if be_event:
        be_utc = parse_iso(be_event["timestamp"])
        lines.append(f"| BREAK_EVEN armed | {fmt_ts(be_utc, 'UTC')} | {fmt_ts(be_utc, 'IST')} | {fmt_ts(be_utc, 'server')} |")
    if exit_t:
        lines.append(f"| EXIT | {fmt_ts(exit_t, 'UTC')} | {fmt_ts(exit_t, 'IST')} | {fmt_ts(exit_t, 'server')} |")
    lines.append("")

    # Excursions
    lines.append("## Excursions (M3 bars during trade window — local MT5)")
    lines.append("")
    if excursions["highest"]:
        lines.append(f"- **MFE** (max favorable): {fmt_price(excursions['mfe_per_oz'])}/unit × {units} = ${excursions['mfe_per_oz'] * units:+.2f}")
        if excursions["mfe_at"]:
            mfe_b = excursions["mfe_at"]
            extreme = mfe_b['low'] if side == 'SHORT' else mfe_b['high']
            lines.append(f"  - At server {mfe_b['time']} ({fmt_price(extreme)})")
        lines.append(f"- **MAE** (max adverse): {fmt_price(excursions['mae_per_oz'])}/unit × {units} = ${excursions['mae_per_oz'] * units:+.2f}")
        if excursions["mae_at"]:
            mae_b = excursions["mae_at"]
            extreme = mae_b['high'] if side == 'SHORT' else mae_b['low']
            lines.append(f"  - At server {mae_b['time']} ({fmt_price(extreme)})")
        if sl and entry:
            sl_dist = abs(entry - sl)
            if excursions["mae_per_oz"] < sl_dist:
                lines.append(f"  → MAE never threatened original SL ({fmt_price(sl_dist - excursions['mae_per_oz'])} away)")
        lines.append("")
    else:
        lines.append("- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).")
        lines.append("")

    # 50% TP / BE trigger
    lines.append("## BE trigger (50% to TP)")
    lines.append("")
    if fifty_pct_bar:
        cross_utc = server_to_utc(parse_dwx_time(fifty_pct_bar["time"]))
        lines.append(f"- 50% TP level **{fmt_price(fifty_pct_level)}** was crossed")
        lines.append(f"- First crossing: server {fifty_pct_bar['time']} (UTC {fmt_ts(cross_utc, 'UTC')}, IST {fmt_ts(cross_utc, 'IST')})")
        lines.append(f"- Bar high/low: {fmt_price(fifty_pct_bar['high'])} / {fmt_price(fifty_pct_bar['low'])}")
        if be_event:
            be_utc = parse_iso(be_event["timestamp"])
            delay = (be_utc - cross_utc).total_seconds()
            if 0 < delay <= 90:
                desc = "within expected 60s polling"
            elif delay > 90:
                desc = f"⚠️ {delay:.0f}s delay — slower than expected polling"
            else:
                desc = f"⚠️ BE event timestamp BEFORE crossing ({delay:.0f}s) — anomaly"
            lines.append(f"- BREAK_EVEN journal event fired {delay:.0f}s after crossing — {desc}")
        else:
            lines.append("- ⚠️ NO BREAK_EVEN journal event found — BE may not have armed")
    else:
        lines.append(f"- 50% TP level **{fmt_price(fifty_pct_level)}** was NEVER reached during trade")
    lines.append("")

    # TP-after-exit
    lines.append("## What happened AFTER exit?")
    lines.append("")
    if tp_after_exit and tp:
        tp_utc = server_to_utc(parse_dwx_time(tp_after_exit["time"]))
        lines.append(f"- TP level {fmt_price(tp)} was reached at server {tp_after_exit['time']} (UTC {fmt_ts(tp_utc, 'UTC')})")
        if exit_t:
            delta_min = (tp_utc - exit_t).total_seconds() / 60
            sign = "after" if delta_min > 0 else "before"
            lines.append(f"  → That's {abs(delta_min):.1f} minutes {sign} our exit")
    elif tp:
        lines.append(f"- TP level {fmt_price(tp)} was NOT reached in the 30-min window after exit")
    lines.append("")

    # Counterfactuals — use ORIGINAL SL from ENTRY_FILLED journal if available
    osl = trade.get("_original_sl") or sl
    if osl and tp and units and entry:
        lines.append("## Counterfactual P&L scenarios")
        lines.append("")
        if osl != sl:
            lines.append(f"_Note: original SL at entry was {fmt_price(osl)}; current stored sl_price is {fmt_price(sl)} (probably moved by BE)._")
            lines.append("")
        lines.append("| Scenario | Per-unit | Total |")
        lines.append("|---|---:|---:|")
        # SL loss is always negative for the trader: distance from entry × units, sign flipped
        sl_loss_per_unit = -abs(osl - entry)  # always loss
        tp_gain_per_unit = abs(tp - entry)    # always gain (assuming TP is on right side of entry)
        lines.append(f"| If hit original SL | {fmt_price(sl_loss_per_unit)} | ${sl_loss_per_unit * units:+.2f} |")
        lines.append(f"| If hit TP | {fmt_price(tp_gain_per_unit)} | ${tp_gain_per_unit * units:+.2f} |")
        if side.upper() == "SHORT" and excursions.get("lowest"):
            lowest = excursions["lowest"]["low"]
            lines.append(f"| If exited at MFE bottom | {fmt_price(entry - lowest)} | ${(entry - lowest) * units:+.2f} |")
        elif side.upper() == "LONG" and excursions.get("highest"):
            highest = excursions["highest"]["high"]
            lines.append(f"| If exited at MFE top | {fmt_price(highest - entry)} | ${(highest - entry) * units:+.2f} |")
        if pnl_usd is not None:
            lines.append(f"| **ACTUAL (DB)** | — | **${pnl_usd:+.2f}** |")
        lines.append("")

    # Bug-smell checklist
    lines.append("## Bug-smell checklist (deterministic)")
    lines.append("")
    smells = []
    tol_price = 5.0 if is_xau else 0.05
    if exit_price is not None and sl and trade.get("exit_reason") == "SL":
        if abs(exit_price - sl) > tol_price:
            smells.append(f"⚠️ exit_reason=SL but exit_price ({fmt_price(exit_price)}) is far from sl_price ({fmt_price(sl)}) — possible misattribution")
    if exit_price is not None and tp and trade.get("exit_reason") == "TP":
        if abs(exit_price - tp) > tol_price:
            smells.append(f"⚠️ exit_reason=TP but exit_price ({fmt_price(exit_price)}) is far from tp_price ({fmt_price(tp)}) — possible misattribution")
    if any(e.get("event_type") == "EXIT_AMBIGUOUS" for e in journal):
        smells.append("⚠️ Journal has EXIT_AMBIGUOUS events — heuristic fallback fired (DWX OnTradeTransaction may not have written closed_orders.json)")
    if pnl_usd is not None and trade.get("exit_reason") == "TP" and pnl_usd <= 0:
        smells.append(f"⚠️ exit_reason=TP but pnl_usd is non-positive (${pnl_usd:+.2f}) — investigate")
    if exit_price is not None and pnl_usd is not None and units and entry:
        expected = (entry - exit_price) * units if side.upper() == "SHORT" else (exit_price - entry) * units
        if abs(expected - pnl_usd) > max(1.0, abs(pnl_usd) * 0.01):
            smells.append(f"⚠️ P&L math doesn't reconcile: stored {pnl_usd:+.2f} vs computed {expected:+.2f} from price levels")
    if pnl_usd is not None and excursions.get("mfe_per_oz", 0) > 0 and units:
        mfe_total = excursions["mfe_per_oz"] * units
        if mfe_total > 100 and pnl_usd > 0 and pnl_usd < mfe_total * 0.1:
            smells.append(f"ℹ️ MFE was ${mfe_total:+.2f} but kept ${pnl_usd:+.2f} ({pnl_usd/mfe_total*100:.0f}% of peak) — note for BE-timing analysis")

    if smells:
        for s in smells:
            lines.append(f"- {s}")
    else:
        lines.append("- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly")
    lines.append("")

    # Pattern vs recent peers
    lines.append("## Pattern vs recent peers")
    lines.append("")
    if peers:
        wins = sum(1 for p in peers if (p.get("pnl_usd") or 0) > 0)
        losses = len(peers) - wins
        total_pnl = sum(float(p.get("pnl_usd") or 0) for p in peers)
        lines.append(f"Last {len(peers)} closed trades for {system_label}:")
        lines.append("")
        lines.append("| trade_ref | side | entry | exit | reason | P&L |")
        lines.append("|---|---|---:|---:|---|---:|")
        for p in peers[:10]:
            ep = float(p.get("entry_price") or 0)
            xp = float(p.get("exit_price") or 0)
            pp = float(p.get("pnl_usd") or 0)
            lines.append(f"| {p.get('trade_ref','?')} | {p.get('side','?')} | {fmt_price(ep)} | {fmt_price(xp)} | {p.get('exit_reason','?')} | ${pp:+.2f} |")
        lines.append("")
        lines.append(f"Recent W/L: {wins}/{losses}")
        lines.append(f"Recent net P&L (excluding this trade): ${total_pnl:+.2f}")
    else:
        lines.append("No peer trades to compare.")
    lines.append("")

    # Journal events
    lines.append("## Journal events (chronological)")
    lines.append("")
    if journal:
        sorted_journal = sorted(journal, key=lambda e: e.get("timestamp", ""))
        lines.append("| timestamp (UTC) | event | price | context |")
        lines.append("|---|---|---:|---|")
        for e in sorted_journal:
            ts_utc = parse_iso(e.get("timestamp"))
            ctx = e.get("context")
            if isinstance(ctx, dict):
                ctx_str = ", ".join(f"{k}={v}" for k, v in list(ctx.items())[:6])
            elif ctx is None:
                ctx_str = ""
            else:
                ctx_str = str(ctx)[:120]
            price_v = e.get("price")
            price_s = f"{price_v:.4f}" if isinstance(price_v, (int, float)) else "—"
            lines.append(f"| {fmt_ts(ts_utc, 'UTC')} | {e.get('event_type','?')} | {price_s} | {ctx_str} |")
    else:
        lines.append("- No journal events for this trade.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_This file is the deterministic facts layer. The trade-postmortem skill appends judgment + analysis below this line._")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def gather_and_write(trade_ref: str) -> str:
    trade, system_label, instrument, lot_div, m3_filename = find_trade(trade_ref)
    if not trade:
        raise SystemExit(f"trade_ref {trade_ref} not found via VPS API")
    if not trade.get("exit_time"):
        raise SystemExit(f"trade_ref {trade_ref} is still OPEN (no exit_time). Postmortem only runs on closed trades.")

    journal = find_journal_for_trade(trade_ref)
    bars_all = load_m3_bars(m3_filename)

    entry_t = parse_iso(trade.get("entry_time"))
    exit_t = parse_iso(trade.get("exit_time"))
    bars_window = filter_bars_in_window(bars_all, entry_t, exit_t, pad_min=10) if (entry_t and exit_t) else []

    entry_price = float(trade.get("entry_price") or 0)
    side = trade["side"]
    excursions = compute_excursions(bars_window, entry_price, side)

    tp = float(trade.get("tp") or trade.get("tp_price") or 0) or None
    sl = float(trade.get("sl") or trade.get("sl_price") or 0) or None

    # Pull ORIGINAL SL from ENTRY_FILLED journal context, since stored sl
    # may have been BE-moved or corrected post-trade.
    original_sl = sl
    for e in journal:
        if e.get("event_type") == "ENTRY_FILLED":
            ctx = e.get("context")
            if isinstance(ctx, dict) and ctx.get("sl"):
                try:
                    original_sl = float(ctx["sl"])
                except (TypeError, ValueError):
                    pass
            break
    # Pass original_sl into trade dict so render uses it
    trade = dict(trade)  # don't mutate caller's
    trade["_original_sl"] = original_sl

    fifty_pct_bar, fifty_pct_level = (None, None)
    if tp:
        fifty_pct_bar, fifty_pct_level = find_first_bar_crossing(bars_window, side, entry_price, tp)

    bars_after_exit = filter_bars_in_window(bars_all, exit_t, exit_t + timedelta(minutes=30), pad_min=0) if exit_t else []
    tp_after_exit = find_tp_hit_bar(bars_after_exit, side, tp) if tp else None

    peers = fetch_recent_peers(trade_ref, n=10)

    md = render_markdown(trade, journal, bars_window, peers, excursions,
                         tp_after_exit, fifty_pct_bar, fifty_pct_level,
                         system_label, instrument)

    out_dir = REPO / "docs" / "trades"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{trade_ref}.md"
    out_path.write_text(md)
    return str(out_path)


def main():
    p = argparse.ArgumentParser(
        description="Build deterministic trade postmortems (LOCAL — uses VPS API + local MT5)"
    )
    p.add_argument("trade_ref", nargs="?", help="trade_ref like GD-MI-cce2a254")
    p.add_argument("--latest", action="store_true",
                   help="postmortem the most recently closed trade across all 4 systems")
    p.add_argument("--since", help="postmortem all trades closed in this window (e.g. 1h, 30m, 2d)")
    args = p.parse_args()

    refs: list = []
    if args.latest:
        ref = latest_closed_trade()
        if not ref:
            raise SystemExit("no closed trades found via VPS API")
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
