"""BT Parity Replay — given a live trade ref, run the matching system's
backtest and find the BT trade that should correspond to the same signal.

Used by scripts/postmortem.py to add a "BT Parity Replay" deterministic
section to every trade postmortem.

Outputs (per replay):
    {
        "fired_in_bt": bool,
        "match": {
            "date":         str (ISO),
            "direction":    "LONG"/"SHORT",
            "entry":        float,
            "sl":           float,
            "tp":           float,
            "exit_price":   float,
            "exit_reason":  str (status),
            "bars_held":    int,
            "pnl_unit":     float,
            "pnl_sized":    float,
            "units":        float,
            "delta_minutes": int,  # signed minutes between live entry and BT entry
        } | None,
        "candidates_nearby": list,   # other BT trades within ±24hr (for context)
        "drift_reason": str | None,  # populated only when fired_in_bt=False
    }

The actual fan-out across SYSTEMS lives in postmortem.py; this module owns
ONLY the per-system "run BT, find matching trade, return verdict" flow.

NOTE: Each call runs a 30-day BT slice (signal date ± 15 days). We use a
SHORT slice rather than full 21-year BT because:
  1. Speed — ~5-15s per replay vs ~150s for full BT.
  2. Yearly capital reset doesn't matter for matching a single trade.
  3. Gates that depend on running equity (consecutive_losses, equity-MA)
     warm-start during the slice — the first ~20 trades in slice are
     under-constrained vs production, but the SIGNAL itself does not
     depend on those gates. We surface the BT trade list as-is and flag
     when slice trade count is too low for gate context to matter.
"""
from __future__ import annotations

import os
import sys
import importlib
from datetime import datetime, timedelta, timezone
from typing import Optional


REPO_ROOT = "/Users/subash/SUBASH/GoldDigger"


# trade-ref prefix → (pkg_dir, env_var, instrument, lot_div, bt_strategies)
SYSTEM_BT_MAP = {
    "GD-MI-": {
        "pkg_dir": "backend-micro",
        "env_var": "GOLD_MICRO_BIAS_MODE",
        "instrument": "XAU_USD",
        "lot_div": 100,
        "strategies": ["micro_alpha_sweep"],  # live runs single strategy
    },
    "OIL-MI-": {
        "pkg_dir": "backend-oil-micro",
        "env_var": "OIL_MICRO_BIAS_MODE",
        "instrument": "BCO_USD",
        "lot_div": 1000,
        "strategies": ["micro_alpha_sweep"],
    },
    # Macro systems — BT path retained but live disabled per Phase 6 e38b288.
    # Replay still works for historical postmortems on Macro trades.
    "GD-AL-": {
        "pkg_dir": "backend",
        "env_var": "GOLD_BIAS_MODE",
        "instrument": "XAU_USD",
        "lot_div": 100,
        "strategies": None,  # use BT default
    },
    "OIL-AS-": {
        "pkg_dir": "backend-oil",
        "env_var": "OIL_BIAS_MODE",
        "instrument": "BCO_USD",
        "lot_div": 1000,
        "strategies": None,
    },
}

# Match window: BT signal-date must be within this many seconds of live
# entry-time to count as the "same signal". Live entry can drift from the
# strategy's bar-close timestamp by several minutes due to:
#   - Cron tick lag (scheduler runs every 3 min, may pick up signal up to
#     +90s after bar close).
#   - F27 limit fill latency (added bars between signal and broker fill).
# 12 minutes covers the Filter #27 worst case (15min TTL fill).
SIGNAL_MATCH_WINDOW_SECS = 720  # ±12 min

# Slice radius around the live trade entry (in days) — controls BT speed.
SLICE_DAYS_BEFORE = 15
SLICE_DAYS_AFTER = 5  # exit must land in window so ample post-entry data


def _system_for_trade_ref(trade_ref: str) -> Optional[dict]:
    for prefix, conf in SYSTEM_BT_MAP.items():
        if trade_ref.startswith(prefix):
            return {"prefix": prefix, **conf}
    return None


def _setup_modules(pkg_dir: str, env_var: str, bias_mode: str = "neutral"):
    """Mirror phase6_smoke_test.setup_modules — env BEFORE config import,
    clear sys.modules so each system gets a fresh import."""
    os.environ[env_var] = bias_mode

    for k in list(sys.modules.keys()):
        if k.startswith((
            "scanner", "config", "backtest", "strategies",
            "backend.execution", "backend.strategies",
            "backend.backtest", "backend.data",
        )):
            del sys.modules[k]

    pkg_path = os.path.join(REPO_ROOT, pkg_dir)
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()


def _run_bt_slice(pkg_dir: str, env_var: str, start_iso: str, end_iso: str,
                  strategies: Optional[list]) -> list:
    """Run BT on a date slice, return trade list (raw BacktestTrade dicts)."""
    _setup_modules(pkg_dir, env_var)
    engine = importlib.import_module("backtest.engine")

    kwargs = {
        "bias_mode": "neutral",
        "start_date": start_iso,
        "end_date": end_iso,
    }
    if strategies:
        kwargs["strategies"] = strategies

    result = engine.run_backtest(**kwargs)

    # Convert to plain dicts so caller doesn't depend on the dataclass
    return [
        {
            "date": str(t.date),
            "direction": t.direction.upper(),
            "entry": float(t.entry),
            "sl": float(t.sl),
            "tp": float(t.tp),
            "exit_price": float(t.exit_price),
            "status": t.status,
            "bars_held": int(t.bars_held),
            "pnl_unit": float(t.pnl_unit),
            "pnl_sized": float(t.pnl_sized),
            "units": float(t.units),
            "strategy": t.strategy,
            "risk": float(t.risk),
            "r_mult": float(t.r_mult),
            "hold_human": t.hold_human,
        }
        for t in result.trades
    ]


def _parse_iso(s: str) -> Optional[datetime]:
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


def replay(trade_ref: str, live_entry_iso: str, live_direction: str,
           verbose: bool = False) -> dict:
    """Run BT replay for a closed live trade, return match verdict.

    Args:
        trade_ref: e.g. "GD-MI-a94ebe4a"
        live_entry_iso: ENTRY_FILLED timestamp ISO (UTC). For F27 trades,
            use the broker fill time (LIMIT_FILLED), since BT's signal date
            is the strategy's bar-close, which is closer to LIMIT_PLACED
            than LIMIT_FILLED — we widen the match window to absorb this.
        live_direction: "LONG" or "SHORT"
        verbose: print diagnostics during run.

    Returns: dict (see module docstring).
    """
    sysconf = _system_for_trade_ref(trade_ref)
    if not sysconf:
        return {
            "fired_in_bt": False,
            "match": None,
            "candidates_nearby": [],
            "drift_reason": f"trade_ref prefix not recognized: {trade_ref}",
        }

    live_entry_dt = _parse_iso(live_entry_iso)
    if not live_entry_dt:
        return {
            "fired_in_bt": False,
            "match": None,
            "candidates_nearby": [],
            "drift_reason": f"could not parse live_entry_iso={live_entry_iso!r}",
        }

    # BT slice: ±15 days centered on entry, but expand the END so the BT
    # trade has full exit-walk data even for max-hold trades.
    slice_start = (live_entry_dt - timedelta(days=SLICE_DAYS_BEFORE)).strftime("%Y-%m-%d")
    slice_end = (live_entry_dt + timedelta(days=SLICE_DAYS_AFTER)).strftime("%Y-%m-%d")

    if verbose:
        print(f"[bt_replay] {trade_ref}: BT slice {slice_start} → {slice_end}")

    # Pre-flight: check whether the system's M3 CSV covers the trade date.
    # If the CSV ends BEFORE live entry, BT cannot replay this trade —
    # report cleanly rather than producing a misleading "drift" verdict.
    csv_path = os.path.join(
        REPO_ROOT, "data", "raw",
        f"{sysconf['instrument']}_M3.csv",
    )
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, "rb") as f:
                f.seek(-200, os.SEEK_END)
                last_line = f.read().decode("utf-8").strip().split("\n")[-1]
            last_ts_str = last_line.split(",")[0].replace("+00:00", "Z")
            last_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
            if last_ts < live_entry_dt:
                return {
                    "fired_in_bt": False,
                    "match": None,
                    "candidates_nearby": [],
                    "drift_reason": (
                        f"BT data ends {last_ts.isoformat()} but live trade "
                        f"entered {live_entry_dt.isoformat()} — BT data has not "
                        f"caught up to live trade window. Run after JM data refresh."
                    ),
                    "data_too_old": True,
                    "data_last_ts": last_ts.isoformat(),
                }
        except (OSError, ValueError, IndexError):
            pass  # fall through to BT call; engine will tell us if it can't

    try:
        bt_trades = _run_bt_slice(
            sysconf["pkg_dir"], sysconf["env_var"],
            slice_start, slice_end,
            sysconf["strategies"],
        )
    except Exception as e:
        return {
            "fired_in_bt": False,
            "match": None,
            "candidates_nearby": [],
            "drift_reason": f"BT slice raised: {type(e).__name__}: {e}",
        }

    if verbose:
        print(f"[bt_replay] {trade_ref}: BT produced {len(bt_trades)} trades in slice")

    # Find best match: same direction + closest signal-date to live entry.
    target_dir = live_direction.upper()
    nearby = []
    best_match = None
    best_delta_secs = None

    for t in bt_trades:
        bt_dt = _parse_iso(t["date"])
        if not bt_dt:
            continue
        delta_secs = (live_entry_dt - bt_dt).total_seconds()
        if abs(delta_secs) <= 86400:  # within ±1 day
            nearby.append({**t, "delta_minutes": int(delta_secs / 60)})
        if t["direction"] != target_dir:
            continue
        if abs(delta_secs) <= SIGNAL_MATCH_WINDOW_SECS:
            if best_delta_secs is None or abs(delta_secs) < abs(best_delta_secs):
                best_match = {**t, "delta_minutes": int(delta_secs / 60)}
                best_delta_secs = delta_secs

    nearby.sort(key=lambda t: abs(t.get("delta_minutes", 9999)))

    if best_match:
        return {
            "fired_in_bt": True,
            "match": best_match,
            "candidates_nearby": nearby[:5],
            "drift_reason": None,
        }

    # Drift cause heuristic
    same_dir_in_window = [
        t for t in nearby
        if t["direction"] == target_dir
        and abs(t.get("delta_minutes", 9999)) <= 60
    ]
    if same_dir_in_window:
        drift = (
            f"Same-direction BT signal within ±60 min, but offset "
            f"{same_dir_in_window[0]['delta_minutes']:+d}min exceeds "
            f"±{SIGNAL_MATCH_WINDOW_SECS // 60}min match window — possible bar/cron drift"
        )
    elif nearby:
        nearest = nearby[0]
        drift = (
            f"No same-direction BT signal in window. Nearest BT trade: "
            f"{nearest['direction']} at {nearest['date']} "
            f"({nearest.get('delta_minutes', '?'):+d}min from live entry)"
        )
    else:
        drift = (
            "No BT trades in ±1 day of live entry — strategy didn't fire at all "
            "in BT for this date. Possible causes: (a) bias filter blocked in BT "
            "but lifted in live, (b) BT data has gap, (c) signal-gen drift."
        )

    return {
        "fired_in_bt": False,
        "match": None,
        "candidates_nearby": nearby[:5],
        "drift_reason": drift,
    }


def render_replay_section(replay_result: dict, instrument: str) -> list:
    """Render the BT Parity Replay markdown section for postmortem.py.
    Returns list of lines (no trailing newline)."""
    is_xau = "XAU" in instrument
    fmt_p = lambda p: f"${p:.2f}" if is_xau else f"${p:.4f}"

    lines = []
    lines.append("## BT Parity Replay")
    lines.append("")

    if replay_result["fired_in_bt"]:
        m = replay_result["match"]
        lines.append(
            f"- **Fired in BT?** ✅ YES "
            f"(BT signal at `{m['date']}`, {m['delta_minutes']:+d} min vs live entry)"
        )
        lines.append("")
        lines.append("### BT trade outcome")
        lines.append("")
        lines.append("| Field | BT |")
        lines.append("|---|---:|")
        lines.append(f"| Strategy | {m.get('strategy', '?')} |")
        lines.append(f"| Direction | {m['direction']} |")
        lines.append(f"| Entry | {fmt_p(m['entry'])} |")
        lines.append(f"| SL (original) | {fmt_p(m['sl'])} |")
        lines.append(f"| TP | {fmt_p(m['tp'])} |")
        lines.append(f"| Exit | {fmt_p(m['exit_price'])} |")
        lines.append(f"| Exit reason | `{m['status']}` |")
        lines.append(f"| Bars held | {m['bars_held']} ({m.get('hold_human', '?')}) |")
        lines.append(f"| P&L per unit | {fmt_p(m['pnl_unit'])} |")
        lines.append(f"| Units | {m['units']:.2f} |")
        lines.append(f"| **P&L sized** | **${m['pnl_sized']:+.2f}** |")
        lines.append(f"| R-multiple | {m['r_mult']:+.2f}R |")
        lines.append("")
        lines.append(
            "_BT P&L is per BT capital schedule (yearly reset to $5k, "
            "configured risk%). Compare DIRECTION + EXIT_REASON to live; "
            "P&L magnitudes differ when live NAV ≠ BT capital schedule._"
        )
    elif replay_result.get("data_too_old"):
        lines.append(f"- **Fired in BT?** ⏳ DATA NOT YET AVAILABLE")
        lines.append(
            f"- **BT data last timestamp:** "
            f"`{replay_result.get('data_last_ts', '?')}`"
        )
        lines.append(
            f"- {replay_result['drift_reason']}"
        )
        lines.append("")
    else:
        lines.append(f"- **Fired in BT?** ❌ NO")
        if replay_result.get("drift_reason"):
            lines.append(f"- **Drift reason:** {replay_result['drift_reason']}")
        lines.append("")
        if replay_result["candidates_nearby"]:
            lines.append("### Nearest BT signals in ±1 day")
            lines.append("")
            lines.append("| BT date | dir | entry | exit | reason | P&L | Δmin |")
            lines.append("|---|---|---:|---:|---|---:|---:|")
            for c in replay_result["candidates_nearby"]:
                lines.append(
                    f"| {c['date']} | {c['direction']} | "
                    f"{fmt_p(c['entry'])} | {fmt_p(c['exit_price'])} | "
                    f"`{c['status']}` | ${c['pnl_sized']:+.2f} | "
                    f"{c.get('delta_minutes', '?'):+d} |"
                )
            lines.append("")
        else:
            lines.append("- No BT trades in ±1 day window.")

    lines.append("")
    return lines


# CLI for ad-hoc replay (does not write files; pure stdout)
def _cli():
    import argparse
    import json
    p = argparse.ArgumentParser(
        description="BT parity replay for a single live trade"
    )
    p.add_argument("trade_ref", help="trade_ref like GD-MI-a94ebe4a")
    p.add_argument("entry_iso",
                   help="live ENTRY_FILLED timestamp (ISO 8601, UTC)")
    p.add_argument("direction", help="LONG or SHORT")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    res = replay(args.trade_ref, args.entry_iso, args.direction,
                 verbose=args.verbose)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    _cli()
