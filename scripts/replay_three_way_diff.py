"""TR-4 Three-way diff: LIVE ↔ BT ↔ REPLAY.

Compares trade lists from three sources for the same date range:
  L = production live trades (queried from VPS via debug API /sql)
  B = corrected BT (run_backtest with post-lookahead-fix engine)
  R = tape replay (golddigger_replay.gd_trades after a replay run)

Buckets every signal-time observation into:
  - L∩B∩R   — three-way agreement (the goal)
  - B∩R\L   — BT and replay agree, live missed (live-only gate)
  - L∩R\B   — replay and live agree, BT missed (BT bug or strategy diff)
  - L∩B\R   — live and BT agree, replay missed (replay broker bug)
  - B only  — BT-only fill (lookahead suspect, OR BT-correct but live+replay
              both blocked by a gate)
  - R only  — replay-only fill (rare; usually broker-physics asymmetry)
  - L only  — live-only fill (timing edge)

Match logic:
  Signals are "the same" if direction matches AND signal-time delta < 12 min.
  Fill comparison uses entry_price + exit_reason + bars_held + pnl_sized.

Usage:
  python scripts/replay_three_way_diff.py --start 2026-06-19 --end 2026-06-19
                                          --system gold-micro
"""
from __future__ import annotations

import argparse
import os
import sys
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
import urllib.parse
import urllib.request

REPO_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, REPO_ROOT)


SIGNAL_MATCH_WINDOW_SECS = 3600  # ±60 min — covers BT engulfing-time anchor vs replay/live cron-tick placement-time anchor difference


# ────────────────────────────────────────────────────────────────────
# Trade record (canonical shape; all 3 sources normalize to this)
# ────────────────────────────────────────────────────────────────────

@dataclass
class TradeRow:
    source: str  # "L" / "B" / "R"
    signal_time: datetime
    direction: str  # "LONG" / "SHORT"
    entry: float
    sl: float
    tp: float
    exit_price: Optional[float]
    exit_reason: Optional[str]
    bars_held: Optional[int]
    pnl_sized: Optional[float]   # P&L in account currency, sized
    raw: dict = field(default_factory=dict)


# ────────────────────────────────────────────────────────────────────
# Source 1 — production LIVE trades via VPS debug API
# ────────────────────────────────────────────────────────────────────

def fetch_live_trades(system: str, start: datetime, end: datetime) -> list[TradeRow]:
    """Pull from production VPS via /api/<sys>/debug/sql GET."""
    base = "https://midas.subashtrades.in"
    api_sys = "micro" if system == "gold-micro" else "oil-micro"
    prefix = "GD-MI-" if system == "gold-micro" else "OIL-MI-"
    sql = (
        f"SELECT trade_ref, side, entry_time, entry_price, sl_price, tp_price, "
        f"exit_time, exit_reason, exit_price, pnl_usd FROM gd_trades "
        f"WHERE trade_ref LIKE '{prefix}%' "
        f"AND entry_time >= '{start.isoformat()}'::timestamptz "
        f"AND entry_time < '{end.isoformat()}'::timestamptz "
        f"ORDER BY entry_time"
    )
    url = f"{base}/api/{api_sys}/debug/sql?q=" + urllib.parse.quote(sql)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [LIVE FETCH] FAILED: {type(e).__name__}: {e}")
        return []
    rows = data.get("rows", [])
    out = []
    for r in rows:
        sig_t = r.get("entry_time")
        if not sig_t:
            continue
        sig_dt = _parse_iso(sig_t)
        if not sig_dt:
            continue
        out.append(TradeRow(
            source="L",
            signal_time=sig_dt,
            direction=str(r.get("side", "")).upper(),
            entry=_to_float(r.get("entry_price")),
            sl=_to_float(r.get("sl_price")),
            tp=_to_float(r.get("tp_price")),
            exit_price=_to_float(r.get("exit_price")) if r.get("exit_price") else None,
            exit_reason=r.get("exit_reason"),
            bars_held=None,  # not in schema
            pnl_sized=_to_float(r.get("pnl_usd")) if r.get("pnl_usd") is not None else None,
            raw=r,
        ))
    return out


# ────────────────────────────────────────────────────────────────────
# Source 2 — corrected BT (in-process)
# ────────────────────────────────────────────────────────────────────

def fetch_bt_trades(system: str, start: datetime, end: datetime) -> list[TradeRow]:
    """Run BT for the date range and return trade rows."""
    import importlib

    pkg_dir = "backend-micro" if system == "gold-micro" else "backend-oil-micro"
    bias_env = "GOLD_MICRO_BIAS_MODE" if system == "gold-micro" else "OIL_MICRO_BIAS_MODE"

    # Clear modules + set env, just like bt_replay.py pattern
    for k in list(sys.modules.keys()):
        if k.startswith((
            "scanner", "config", "backtest", "strategies",
            "backend.execution", "backend.strategies",
            "backend.backtest", "backend.data",
        )):
            del sys.modules[k]
    os.environ[bias_env] = "neutral"
    pkg_path = os.path.join(REPO_ROOT, pkg_dir)
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()

    engine = importlib.import_module("backtest.engine")

    # Slice ±15 days for warm DD context, then filter post-run
    slice_start = (start - timedelta(days=15)).date().isoformat()
    slice_end = (end + timedelta(days=1)).date().isoformat()
    kwargs = {"bias_mode": "neutral", "start_date": slice_start, "end_date": slice_end}
    if system == "gold-micro":
        kwargs["strategies"] = ["micro_alpha_sweep"]
    result = engine.run_backtest(**kwargs)

    out = []
    for t in result.trades:
        sig_dt = _parse_iso(t.date)
        if not sig_dt or sig_dt < start or sig_dt >= end:
            continue
        out.append(TradeRow(
            source="B",
            signal_time=sig_dt,
            direction=t.direction.upper(),
            entry=float(t.entry),
            sl=float(t.sl),
            tp=float(t.tp),
            exit_price=float(t.exit_price),
            exit_reason=t.status,
            bars_held=int(t.bars_held),
            pnl_sized=float(t.pnl_sized),
            raw={"hold_human": t.hold_human, "r_mult": float(t.r_mult), "filled": True},
        ))
    return out


# ────────────────────────────────────────────────────────────────────
# Source 3 — REPLAY trades (golddigger_replay.gd_trades)
# ────────────────────────────────────────────────────────────────────

def fetch_replay_trades(system: str, start: datetime, end: datetime) -> list[TradeRow]:
    """Pull from local golddigger_replay DB."""
    prefix = "GD-MI-" if system == "gold-micro" else "OIL-MI-"
    conn = psycopg2.connect("postgresql://subash@localhost:5432/golddigger_replay")
    cur = conn.cursor()
    cur.execute(
        "SELECT trade_ref, side, entry_time, entry_price, sl_price, tp_price, "
        "exit_time, exit_reason, exit_price, pnl_usd FROM gd_trades "
        "WHERE trade_ref LIKE %s "
        "AND entry_time >= %s AND entry_time < %s "
        "ORDER BY entry_time",
        (f"{prefix}%", start, end),
    )
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        sig_dt = r[2]
        if not sig_dt:
            continue
        if sig_dt.tzinfo is None:
            sig_dt = sig_dt.replace(tzinfo=timezone.utc)
        else:
            sig_dt = sig_dt.astimezone(timezone.utc)
        out.append(TradeRow(
            source="R",
            signal_time=sig_dt,
            direction=str(r[1]).upper(),
            entry=_to_float(r[3]),
            sl=_to_float(r[4]),
            tp=_to_float(r[5]),
            exit_price=_to_float(r[8]) if r[8] is not None else None,
            exit_reason=r[7],
            bars_held=None,
            pnl_sized=_to_float(r[9]) if r[9] is not None else None,
            raw={"trade_ref": r[0], "exit_time": str(r[6]) if r[6] else None},
        ))
    return out


# ────────────────────────────────────────────────────────────────────
# Match logic
# ────────────────────────────────────────────────────────────────────

def _signals_match(a: TradeRow, b: TradeRow) -> bool:
    """Two trades match if same direction AND |delta_t| < SIGNAL_MATCH_WINDOW_SECS."""
    if a.direction != b.direction:
        return False
    dt = abs((a.signal_time - b.signal_time).total_seconds())
    return dt < SIGNAL_MATCH_WINDOW_SECS


def three_way_match(L: list[TradeRow], B: list[TradeRow], R: list[TradeRow]) -> dict:
    """Bucketize. Each trade can appear in only ONE bucket.

    Greedy match: for each L row, find best B match and best R match. Then
    same for unmatched B's — find best R match. Whatever's left is "only".
    """
    L_used = [False] * len(L)
    B_used = [False] * len(B)
    R_used = [False] * len(R)

    buckets = {
        "LBR": [],   # 3-way agree
        "LB": [],    # L+B match, no R
        "LR": [],    # L+R match, no B
        "BR": [],    # B+R match, no L
        "L_only": [],
        "B_only": [],
        "R_only": [],
    }

    # 3-way match first (most strict)
    for i, l in enumerate(L):
        if L_used[i]:
            continue
        for j, b in enumerate(B):
            if B_used[j] or not _signals_match(l, b):
                continue
            for k, r in enumerate(R):
                if R_used[k] or not _signals_match(l, r):
                    continue
                # 3-way!
                buckets["LBR"].append({"L": l, "B": b, "R": r})
                L_used[i] = B_used[j] = R_used[k] = True
                break
            if L_used[i]:
                break

    # 2-way: L+B (no R)
    for i, l in enumerate(L):
        if L_used[i]:
            continue
        for j, b in enumerate(B):
            if B_used[j] or not _signals_match(l, b):
                continue
            buckets["LB"].append({"L": l, "B": b})
            L_used[i] = B_used[j] = True
            break

    # 2-way: L+R (no B)
    for i, l in enumerate(L):
        if L_used[i]:
            continue
        for k, r in enumerate(R):
            if R_used[k] or not _signals_match(l, r):
                continue
            buckets["LR"].append({"L": l, "R": r})
            L_used[i] = R_used[k] = True
            break

    # 2-way: B+R (no L)
    for j, b in enumerate(B):
        if B_used[j]:
            continue
        for k, r in enumerate(R):
            if R_used[k] or not _signals_match(b, r):
                continue
            buckets["BR"].append({"B": b, "R": r})
            B_used[j] = R_used[k] = True
            break

    # Singletons
    for i, l in enumerate(L):
        if not L_used[i]:
            buckets["L_only"].append({"L": l})
    for j, b in enumerate(B):
        if not B_used[j]:
            buckets["B_only"].append({"B": b})
    for k, r in enumerate(R):
        if not R_used[k]:
            buckets["R_only"].append({"R": r})

    return buckets


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _parse_iso(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc) if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        # Decimal('1234.56') from psycopg2 → str → float
        return float(str(v).replace("Decimal(", "").replace(")", "").strip("'\""))


def _fmt_pnl(v) -> str:
    return f"${v:+.2f}" if v is not None else "—"


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%m-%d %H:%M") + "Z"


def _fmt_row(t: Optional[TradeRow], src_label: str = "") -> str:
    if not t:
        return f"{src_label}: —"
    return (f"{src_label}: {_fmt_dt(t.signal_time)} {t.direction:5s} "
            f"entry={t.entry:.4f} exit={t.exit_reason or '—':18s} "
            f"pnl={_fmt_pnl(t.pnl_sized)}")


def render_diff(buckets: dict, system: str, start: datetime, end: datetime) -> None:
    print("=" * 80)
    print(f"3-WAY DIFF: {system}  |  {start.date()} → {end.date()}")
    print("=" * 80)

    counts = {k: len(v) for k, v in buckets.items()}
    total = sum(counts.values())
    print(f"\nBuckets ({total} total trade-observations):")
    for label, n in counts.items():
        print(f"  {label:8s}: {n}")
    print()

    # Render each bucket — emphasize divergences
    for label in ("LBR", "LB", "LR", "BR", "L_only", "B_only", "R_only"):
        rows = buckets[label]
        if not rows:
            continue
        print(f"\n--- {label} ({len(rows)}) ---")
        for entry in rows:
            l = entry.get("L")
            b = entry.get("B")
            r = entry.get("R")
            # Anchor row time
            anchor = (l or b or r).signal_time
            print(f"  @ {_fmt_dt(anchor)}:")
            if l: print(f"    {_fmt_row(l, 'LIVE  ')}")
            if b: print(f"    {_fmt_row(b, 'BT    ')}")
            if r: print(f"    {_fmt_row(r, 'REPLAY')}")
            # Highlight large pnl divergences in 3-way
            if l and b and r:
                pnls = [x.pnl_sized for x in (l, b, r) if x.pnl_sized is not None]
                if pnls:
                    spread = max(pnls) - min(pnls)
                    if spread > 50:
                        print(f"    ⚠️ pnl spread ${spread:.2f} > $50")

    # P&L summaries
    def _sum_pnl(src):
        s = 0.0
        for label, rows in buckets.items():
            for entry in rows:
                t = entry.get(src)
                if t and t.pnl_sized is not None:
                    s += t.pnl_sized
        return s

    print()
    print("=" * 80)
    print("P&L by source:")
    print(f"  LIVE:   {_fmt_pnl(_sum_pnl('L'))}")
    print(f"  BT:     {_fmt_pnl(_sum_pnl('B'))}")
    print(f"  REPLAY: {_fmt_pnl(_sum_pnl('R'))}")
    print("=" * 80)


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="gold-micro",
                    choices=["gold-micro", "oil-micro"])
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")
    ap.add_argument("--no-live", action="store_true",
                    help="skip live fetch (for offline testing)")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    print(f"Fetching LIVE trades from VPS for {args.system}...")
    L = [] if args.no_live else fetch_live_trades(args.system, start, end)
    print(f"  → {len(L)} live trades")

    print(f"\nRunning BT (corrected, post-lookahead-fix) for {args.system}...")
    B = fetch_bt_trades(args.system, start, end)
    print(f"  → {len(B)} BT trades")

    print(f"\nLoading REPLAY trades from golddigger_replay for {args.system}...")
    R = fetch_replay_trades(args.system, start, end)
    print(f"  → {len(R)} replay trades")

    print("\nMatching...")
    buckets = three_way_match(L, B, R)
    render_diff(buckets, args.system, start, end)


if __name__ == "__main__":
    main()
