"""Replay today's BT signals + cross-reference against gd_traded_sweeps.

Goal: for the 9 marked-no-trade rows post-Phase-6 (deploy 09:28 UTC),
determine what BT would have done for each. This tells us how much of
today's 0-trades-vs-BT gap is due to A1 (persistent state) vs A9 (live-only
gates BT doesn't simulate).

Run: python scripts/replay_today_missed_signals.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, date, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import importlib

# Same setup pattern as bt_replay.py
PHASE6_DEPLOY_UTC = datetime(2026, 6, 19, 9, 28, tzinfo=timezone.utc)


SYSTEMS = [
    {
        "name": "gold-micro",
        "pkg_dir": "backend-micro",
        "env_var": "GOLD_MICRO_BIAS_MODE",
        "instrument": "XAU_USD",
    },
    {
        "name": "oil-micro",
        "pkg_dir": "backend-oil-micro",
        "env_var": "OIL_MICRO_BIAS_MODE",
        "instrument": "BCO_USD",
    },
]


def setup_modules(pkg_dir: str, env_var: str, bias_mode: str = "neutral"):
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


def run_bt_for_today(sys_conf: dict) -> list:
    """Run BT for date range covering today, return all trade dicts."""
    setup_modules(sys_conf["pkg_dir"], sys_conf["env_var"])
    engine = importlib.import_module("backtest.engine")

    # Slice ±15 days around today for warm-state context
    start_iso = "2026-06-04"
    end_iso = "2026-06-20"

    result = engine.run_backtest(
        bias_mode="neutral",
        start_date=start_iso,
        end_date=end_iso,
        strategies=["micro_alpha_sweep"],
    )

    today_trades = []
    for t in result.trades:
        # t.date is "2026-06-19T13:48:00+00:00" string
        if "2026-06-19" in t.date:
            today_trades.append({
                "date": t.date,
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
                "risk": float(t.risk),
                "r_mult": float(t.r_mult),
                "hold_human": t.hold_human,
            })
    return today_trades


def main():
    print("=" * 70)
    print("BT Replay — today (2026-06-19) post-Phase-6 marked-no-trade analysis")
    print("=" * 70)
    print(f"Phase 6 deploy: {PHASE6_DEPLOY_UTC} UTC")
    print()

    for sys_conf in SYSTEMS:
        print(f"--- {sys_conf['name']} ({sys_conf['instrument']}) ---")
        try:
            trades = run_bt_for_today(sys_conf)
        except Exception as e:
            print(f"  BT run FAILED: {type(e).__name__}: {e}")
            continue

        print(f"  Total BT trades on 2026-06-19: {len(trades)}")
        if not trades:
            print()
            continue

        pre_count, pre_pnl = 0, 0.0
        post_count, post_pnl = 0, 0.0

        for t in trades:
            try:
                trade_dt = datetime.fromisoformat(t["date"].replace("Z", "+00:00"))
                if trade_dt.tzinfo is None:
                    trade_dt = trade_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                trade_dt = None

            is_post = trade_dt and trade_dt >= PHASE6_DEPLOY_UTC
            tag = "POST" if is_post else "PRE "
            print(f"    [{tag}] {t['date']} {t['direction']:5s} "
                  f"entry={t['entry']:.4f} sl={t['sl']:.4f} tp={t['tp']:.4f} "
                  f"status={t['status']} bars={t['bars_held']:3d} "
                  f"pnl_unit={t['pnl_unit']:+.4f} pnl_sized=${t['pnl_sized']:+.2f}")
            if is_post:
                post_count += 1
                post_pnl += t["pnl_sized"]
            else:
                pre_count += 1
                pre_pnl += t["pnl_sized"]

        print(f"  PRE-deploy:  {pre_count} trades, ${pre_pnl:+.2f}")
        print(f"  POST-deploy: {post_count} trades, ${post_pnl:+.2f}")
        print()

    print("=" * 70)
    print("Now compare against gd_traded_sweeps marked-no-trade rows post-09:28 UTC")
    print("(use https://midas.subashtrades.in/api/<sys>/debug/sql to verify)")
    print("=" * 70)


if __name__ == "__main__":
    main()
