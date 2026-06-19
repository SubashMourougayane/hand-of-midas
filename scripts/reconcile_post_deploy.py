"""Phase 7 — Post-deploy reconciler.

Pulls last N closed live trades for both Micros from the VPS API, replays
each through bt_replay.replay(), and computes the live↔BT capture metrics:

    - fire_match_rate: % of live trades that BT also fired (within ±12min)
    - direction_match_rate: % of fired trades where direction agrees
    - exit_reason_match_rate: % where exit_reason categories agree
    - capture_pct: live_pnl / bt_pnl per trade (normalized for unit-size)
    - net_capture: aggregate ($ live captured / $ BT projection)

Output:
    1. Console table (per-trade)
    2. docs/reconcile_<YYYY-MM-DD>.md report

Usage:
    python scripts/reconcile_post_deploy.py            # last 30 trades each system
    python scripts/reconcile_post_deploy.py --limit 50 # last 50 each
    python scripts/reconcile_post_deploy.py --since 7d # last 7 days

Caveats:
    - Trades whose entry exceeds JM CSV end show "data_too_old" — skipped.
    - LIMIT_TTL_EXPIRED trades have no exit and skip P&L comparison.
    - Pre-Phase-6 (Jun 19 deploy) trades expected to show high drift —
      that's the baseline. Post-deploy capture should improve.
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make sibling scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_replay import replay as bt_replay  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
API_BASE = "https://midas.subashtrades.in"

# trade-ref prefix → API endpoint suffix
SYSTEMS = [
    ("GD-MI-",  "Gold Micro",  "micro",     "XAU_USD"),
    ("OIL-MI-", "Oil Micro",   "oil-micro", "BCO_USD"),
]


def fetch_trades(api_suffix: str, limit: int) -> list:
    url = f"{API_BASE}/api/{api_suffix}/trades?limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "midas-reconcile/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    return data if isinstance(data, list) else data.get("trades", [])


def normalize_exit_reason(reason: str) -> str:
    """Bucket live and BT exit reasons into shared categories.

    Live values:    SL, TP, MAX_HOLD, EXPERT, MANUAL_CLOSE_DETECTED,
                    LIMIT_TTL_EXPIRED, BE_SL, PARTIAL_TP+TP, etc.
    BT values:      sl, tp, tp_partial+sl, tp_partial+tp, tp_partial+expired,
                    max_hold, expired (= MAX_HOLD), missed_unfilled (= LIMIT_TTL).
    """
    if not reason:
        return "unknown"
    r = reason.upper()
    if "MISSED_UNFILLED" in r or "LIMIT_TTL" in r:
        return "limit_unfilled"
    if "MAX_HOLD" in r or "EXPIRED" in r:
        return "max_hold"
    if "PARTIAL" in r and "TP" in r and "SL" not in r:
        return "tp_partial"  # banked + runner closed in profit
    if "PARTIAL" in r and "SL" in r:
        return "tp_partial_then_sl"  # banked + runner stopped out
    if "TP" in r and "PARTIAL" not in r:
        return "tp"
    if "SL" in r or "BE_SL" in r:
        return "sl"
    if "EXPERT" in r or "MANUAL" in r:
        return "expert_close"
    return r.lower()


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def reconcile_trade(trade: dict, system_label: str) -> dict:
    """Reconcile one live trade against BT replay. Returns flat row dict."""
    tr = trade["trade_ref"]
    live_entry_iso = trade.get("entry_time")
    live_dir = (trade.get("side") or "LONG").upper()
    live_pnl = float(trade.get("pnl_usd") or 0)
    live_exit_reason = normalize_exit_reason(trade.get("exit_reason") or "")
    live_units = float(trade.get("units") or 0)
    live_entry_price = float(trade.get("entry_price") or 0)
    live_exit_price = float(trade.get("exit_price") or 0)

    # Skip unfilled limit orders — they have no entry to compare.
    if live_exit_reason == "limit_unfilled":
        return {
            "trade_ref": tr,
            "system": system_label,
            "side": live_dir,
            "live_entry": live_entry_price,
            "live_exit": live_exit_price,
            "live_pnl": live_pnl,
            "live_exit_reason": live_exit_reason,
            "verdict": "limit_unfilled",
            "skip_reason": "live entry never filled (LIMIT_TTL_EXPIRED)",
        }

    # Run BT replay
    rr = bt_replay(tr, live_entry_iso, live_dir, verbose=False)

    if rr.get("data_too_old"):
        return {
            "trade_ref": tr,
            "system": system_label,
            "side": live_dir,
            "live_entry": live_entry_price,
            "live_exit": live_exit_price,
            "live_pnl": live_pnl,
            "live_exit_reason": live_exit_reason,
            "verdict": "data_too_old",
            "skip_reason": rr.get("drift_reason", "BT data not yet caught up"),
        }

    if not rr.get("fired_in_bt"):
        return {
            "trade_ref": tr,
            "system": system_label,
            "side": live_dir,
            "live_entry": live_entry_price,
            "live_exit": live_exit_price,
            "live_pnl": live_pnl,
            "live_exit_reason": live_exit_reason,
            "verdict": "drift_no_match",
            "skip_reason": rr.get("drift_reason"),
            "nearest_bt": (rr.get("candidates_nearby") or [None])[0],
        }

    m = rr["match"]
    bt_exit_reason = normalize_exit_reason(m["status"])

    # Capture: per-unit P&L ratio (normalizes unit-size differences).
    # BT yearly-reset capital ≠ live continuous NAV → sized P&L not directly
    # comparable. Per-unit is the apples-to-apples metric.
    bt_pnl_unit = m["pnl_unit"]
    live_pnl_unit = (live_pnl / live_units) if live_units > 0 else 0

    capture_pct = None
    if abs(bt_pnl_unit) > 0.01:
        capture_pct = (live_pnl_unit / bt_pnl_unit) * 100

    return {
        "trade_ref": tr,
        "system": system_label,
        "side": live_dir,
        "live_entry": live_entry_price,
        "live_exit": live_exit_price,
        "live_pnl": live_pnl,
        "live_pnl_unit": live_pnl_unit,
        "live_exit_reason": live_exit_reason,
        "bt_entry": m["entry"],
        "bt_exit": m["exit_price"],
        "bt_pnl_unit": bt_pnl_unit,
        "bt_pnl_sized": m["pnl_sized"],
        "bt_exit_reason": bt_exit_reason,
        "delta_minutes": m.get("delta_minutes", 0),
        "exit_match": bt_exit_reason == live_exit_reason,
        "direction_match": m["direction"] == live_dir,
        "capture_pct": capture_pct,
        "verdict": "matched",
    }


def render_console(rows: list[dict]) -> None:
    """Print per-trade table + aggregate stats."""
    print()
    print("=" * 110)
    print(f"{'trade_ref':22s} {'sys':12s} {'side':5s} {'verdict':16s} "
          f"{'exit_match':10s} {'live_pnl':>9s} {'bt_pnl':>9s} {'cap%':>6s} {'Δmin':>6s}")
    print("-" * 110)
    for r in rows:
        ref = r["trade_ref"][:22]
        sys_ = r["system"][:12]
        side = r["side"]
        v = r["verdict"]
        em = "—" if v != "matched" else ("✅" if r["exit_match"] else "❌")
        live_pnl = f"${r['live_pnl']:+.0f}"
        bt_pnl = (f"${r.get('bt_pnl_sized', 0):+.0f}"
                  if v == "matched" else "—")
        cap = (f"{r['capture_pct']:.0f}%"
               if v == "matched" and r.get("capture_pct") is not None else "—")
        dm = f"{r.get('delta_minutes', 0):+d}" if v == "matched" else "—"
        print(f"{ref:22s} {sys_:12s} {side:5s} {v:16s} {em:10s} "
              f"{live_pnl:>9s} {bt_pnl:>9s} {cap:>6s} {dm:>6s}")
    print("-" * 110)

    # Aggregate
    total = len(rows)
    if not total:
        print("No trades to reconcile.")
        return

    matched = [r for r in rows if r["verdict"] == "matched"]
    drift = [r for r in rows if r["verdict"] == "drift_no_match"]
    too_old = [r for r in rows if r["verdict"] == "data_too_old"]
    unfilled = [r for r in rows if r["verdict"] == "limit_unfilled"]

    print(f"\nTotal trades: {total}")
    print(f"  ✅ Matched:        {len(matched):3d} ({100*len(matched)/total:.0f}%)")
    print(f"  ❌ Drift no match: {len(drift):3d} ({100*len(drift)/total:.0f}%)")
    print(f"  ⏳ Data too old:    {len(too_old):3d} ({100*len(too_old)/total:.0f}%)")
    print(f"  ⊘  Limit unfilled: {len(unfilled):3d} ({100*len(unfilled)/total:.0f}%)")

    if matched:
        em_count = sum(1 for r in matched if r["exit_match"])
        dm_count = sum(1 for r in matched if r["direction_match"])
        print(f"\nOf matched ({len(matched)} trades):")
        print(f"  Direction match: {dm_count}/{len(matched)} "
              f"({100*dm_count/len(matched):.0f}%)")
        print(f"  Exit match:      {em_count}/{len(matched)} "
              f"({100*em_count/len(matched):.0f}%)")
        captures = [r["capture_pct"] for r in matched
                    if r.get("capture_pct") is not None]
        if captures:
            mean_cap = sum(captures) / len(captures)
            print(f"  Mean capture %:  {mean_cap:.0f}% "
                  f"(n={len(captures)}, range "
                  f"{min(captures):.0f}-{max(captures):.0f}%)")
        live_total = sum(r["live_pnl"] for r in matched)
        bt_total = sum(r.get("bt_pnl_sized", 0) for r in matched)
        if bt_total != 0:
            net_cap = live_total / bt_total * 100
            print(f"  Aggregate $:     live=${live_total:+,.0f} vs "
                  f"bt=${bt_total:+,.0f} → net capture {net_cap:.0f}%")
    print()


def render_markdown_report(rows: list[dict], out_path: Path) -> None:
    """Write a docs/reconcile_<date>.md report."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = []
    lines.append(f"# Phase 7 Reconciliation Report — {today}")
    lines.append("")
    lines.append(f"_Generated by `scripts/reconcile_post_deploy.py`. "
                 f"BT data end timestamp determines replay eligibility. "
                 f"For each replayable trade, BT signal-gen + execution "
                 f"is run on a ±15-day slice and matched to live entry "
                 f"within ±12 min._")
    lines.append("")

    # Summary
    matched = [r for r in rows if r["verdict"] == "matched"]
    drift = [r for r in rows if r["verdict"] == "drift_no_match"]
    too_old = [r for r in rows if r["verdict"] == "data_too_old"]
    unfilled = [r for r in rows if r["verdict"] == "limit_unfilled"]
    lines.append(f"## Summary")
    lines.append("")
    lines.append(f"| Verdict | Count |")
    lines.append(f"|---|---:|")
    lines.append(f"| Total trades | {len(rows)} |")
    lines.append(f"| ✅ Matched | {len(matched)} |")
    lines.append(f"| ❌ Drift no match | {len(drift)} |")
    lines.append(f"| ⏳ Data too old | {len(too_old)} |")
    lines.append(f"| ⊘ Limit unfilled | {len(unfilled)} |")
    lines.append("")

    if matched:
        em = sum(1 for r in matched if r["exit_match"])
        dm = sum(1 for r in matched if r["direction_match"])
        captures = [r["capture_pct"] for r in matched
                    if r.get("capture_pct") is not None]
        live_total = sum(r["live_pnl"] for r in matched)
        bt_total = sum(r.get("bt_pnl_sized", 0) for r in matched)
        lines.append(f"## Capture metrics (matched trades, n={len(matched)})")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---:|")
        lines.append(f"| Direction match rate | {100*dm/len(matched):.0f}% "
                     f"({dm}/{len(matched)}) |")
        lines.append(f"| Exit-reason match rate | {100*em/len(matched):.0f}% "
                     f"({em}/{len(matched)}) |")
        if captures:
            mean = sum(captures) / len(captures)
            lines.append(f"| Mean per-trade capture % | {mean:.0f}% "
                         f"(range {min(captures):.0f}-{max(captures):.0f}%, "
                         f"n={len(captures)}) |")
        if bt_total != 0:
            lines.append(f"| Aggregate $ capture | "
                         f"live=${live_total:+,.0f} / bt=${bt_total:+,.0f} = "
                         f"**{100*live_total/bt_total:.0f}%** |")
        lines.append("")

    # Per-trade
    lines.append(f"## Per-trade detail")
    lines.append("")
    lines.append("| trade_ref | system | side | verdict | live_pnl | bt_pnl | "
                 "capture% | exit_match | Δmin |")
    lines.append("|---|---|---|---|---:|---:|---:|---|---:|")
    for r in rows:
        v = r["verdict"]
        bt = (f"${r.get('bt_pnl_sized', 0):+.0f}"
              if v == "matched" else "—")
        cap = (f"{r['capture_pct']:.0f}%"
               if v == "matched" and r.get("capture_pct") is not None
               else "—")
        em = "—" if v != "matched" else ("✅" if r["exit_match"] else "❌")
        dm = (f"{r.get('delta_minutes', 0):+d}"
              if v == "matched" else "—")
        lines.append(f"| `{r['trade_ref']}` | {r['system']} | {r['side']} | "
                     f"{v} | ${r['live_pnl']:+.0f} | {bt} | {cap} | {em} | {dm} |")
    lines.append("")

    # Drift detail
    if drift:
        lines.append(f"## Drift cases (no BT match within ±12 min)")
        lines.append("")
        for r in drift:
            lines.append(f"### `{r['trade_ref']}` — {r['system']} {r['side']}")
            lines.append("")
            lines.append(f"- **Live:** entry ${r['live_entry']:.2f} → "
                         f"exit ${r['live_exit']:.2f}, "
                         f"P&L ${r['live_pnl']:+.0f} ({r['live_exit_reason']})")
            lines.append(f"- **Drift reason:** {r.get('skip_reason', '?')}")
            nearest = r.get("nearest_bt")
            if nearest:
                lines.append(
                    f"- **Nearest BT trade:** {nearest.get('direction','?')} "
                    f"at {nearest.get('date','?')} "
                    f"(Δ {nearest.get('delta_minutes','?'):+d}min) — "
                    f"`{nearest.get('status','?')}`, "
                    f"P&L ${nearest.get('pnl_sized', 0):+.0f}"
                )
            lines.append("")

    out_path.write_text("\n".join(lines))


def main():
    p = argparse.ArgumentParser(
        description="Phase 7 post-deploy reconciler — measure live↔BT capture"
    )
    p.add_argument("--limit", type=int, default=30,
                   help="Trades to fetch per system (default 30)")
    p.add_argument("--out",
                   help="Output markdown path (default docs/reconcile_<date>.md)")
    args = p.parse_args()

    print(f"[reconcile] fetching last {args.limit} trades per Micro system...")
    rows = []
    for prefix, label, suffix, instrument in SYSTEMS:
        try:
            trades = fetch_trades(suffix, args.limit)
        except Exception as e:
            print(f"  ⚠️  {label}: fetch failed ({type(e).__name__}: {e})")
            continue
        # Only closed trades
        closed = [t for t in trades if t.get("exit_time")]
        print(f"  {label}: {len(closed)} closed trades fetched")
        for i, t in enumerate(closed, 1):
            print(f"  ... [{i}/{len(closed)}] {t['trade_ref']}", end="\r")
            try:
                row = reconcile_trade(t, label)
                rows.append(row)
            except Exception as e:
                print(f"\n    ✗ {t['trade_ref']}: {type(e).__name__}: {e}")
        print(" " * 80, end="\r")  # clear progress line

    # Render
    render_console(rows)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = Path(args.out) if args.out else REPO / "docs" / f"reconcile_{today}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render_markdown_report(rows, out_path)
    print(f"\n✓ wrote {out_path}")


if __name__ == "__main__":
    main()
