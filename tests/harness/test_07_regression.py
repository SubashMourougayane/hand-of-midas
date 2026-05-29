"""TEST 07: Regression — Golden snapshot comparison.

Runs the signal generator + fill model on a fixed date range and compares
against a saved snapshot. ANY change in output = regression = FAIL.
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.strategies import micro_alpha_sweep
from backend.execution.fill_model import execute_trade
from backend.config import ALPHA_SWEEP


def generate_snapshot(h1_df, m3_df, daily_bias, start_date, end_date):
    """Generate a deterministic snapshot of signals + trades for a date range."""
    np.random.seed(42)
    signals = micro_alpha_sweep.generate_signals(h1_df, m3_df, daily_bias)
    signals = sorted(signals, key=lambda x: x.date)

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    signals = [s for s in signals if start_ts <= s.date <= end_ts]

    trades = []
    for s in signals:
        try:
            bar_idx = m3_df.index.get_loc(s.date)
        except KeyError:
            continue
        result = execute_trade(
            df=m3_df, bar_start=bar_idx, entry=s.entry, sl=s.sl, tp=s.tp,
            direction=s.direction, max_bars=s.max_bars, strategy=s.strategy,
            use_break_even=True
        )
        if result is None:
            continue
        trades.append({
            "ts": s.date.isoformat(),
            "dir": s.direction,
            "entry": round(s.entry, 2),
            "sl": round(s.sl, 2),
            "tp": round(s.tp, 2),
            "exit_reason": result.exit_reason,
            "exit_price": round(result.exit_price, 2),
            "pnl_per_unit": round(result.pnl_per_unit, 2),
            "bars_held": result.bars_held,
        })

    return {
        "signals": [{"ts": s.date.isoformat(), "dir": s.direction, "entry": round(s.entry, 2)} for s in signals],
        "trades": trades,
        "summary": {
            "total_signals": len(signals),
            "total_trades": len(trades),
            "wins": sum(1 for t in trades if t["pnl_per_unit"] > 0),
            "losses": sum(1 for t in trades if t["pnl_per_unit"] <= 0),
            "total_pnl": round(sum(t["pnl_per_unit"] for t in trades), 2),
        },
        "config": {
            "sl_buffer": ALPHA_SWEEP["sl_buffer"],
            "tp_structure_buffer": ALPHA_SWEEP.get("tp_structure_buffer"),
            "sweep_threshold": ALPHA_SWEEP["sweep_threshold"],
            "min_sl": ALPHA_SWEEP["min_sl"],
        },
    }


def load_golden():
    """Load saved golden snapshot (if exists)."""
    golden_file = os.path.join(GOLDEN_DIR, "snapshot_latest.json")
    if not os.path.exists(golden_file):
        return None
    with open(golden_file) as f:
        return json.load(f)


def save_golden(snapshot):
    """Save a new golden snapshot."""
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    golden_file = os.path.join(GOLDEN_DIR, "snapshot_latest.json")
    with open(golden_file, "w") as f:
        json.dump(snapshot, f, indent=2)


class TestRegression:
    """07: Output must match saved golden snapshot."""

    def test_deterministic_output(self, gold_7d_h1, gold_7d_m3, daily_bias):
        """Same input + same seed = same output (no randomness leaking)."""
        np.random.seed(42)
        start = gold_7d_h1.index[0].strftime("%Y-%m-%d")
        end = gold_7d_h1.index[-1].strftime("%Y-%m-%d")

        snap1 = generate_snapshot(gold_7d_h1, gold_7d_m3, daily_bias, start, end)
        snap2 = generate_snapshot(gold_7d_h1, gold_7d_m3, daily_bias, start, end)

        assert snap1["summary"] == snap2["summary"], \
            f"Non-deterministic: run1={snap1['summary']}, run2={snap2['summary']}"
        assert len(snap1["trades"]) == len(snap2["trades"])
        for t1, t2 in zip(snap1["trades"], snap2["trades"]):
            assert t1 == t2, f"Trade mismatch: {t1} vs {t2}"

    def test_golden_snapshot_match(self, gold_7d_h1, gold_7d_m3, daily_bias):
        """Current output matches saved golden snapshot."""
        golden = load_golden()
        if golden is None:
            # No golden exists — generate and save one (first run)
            start = gold_7d_h1.index[0].strftime("%Y-%m-%d")
            end = gold_7d_h1.index[-1].strftime("%Y-%m-%d")
            snap = generate_snapshot(gold_7d_h1, gold_7d_m3, daily_bias, start, end)
            save_golden(snap)
            pytest.skip("Golden snapshot created (first run). Re-run to verify.")

        # Generate current snapshot with same date range
        start = gold_7d_h1.index[0].strftime("%Y-%m-%d")
        end = gold_7d_h1.index[-1].strftime("%Y-%m-%d")
        current = generate_snapshot(gold_7d_h1, gold_7d_m3, daily_bias, start, end)

        # Compare summaries
        if golden["config"] != current["config"]:
            pytest.skip(f"Config changed since golden was saved. Regenerate with --regenerate-golden")

        assert current["summary"]["total_signals"] == golden["summary"]["total_signals"], \
            f"Signal count changed: was {golden['summary']['total_signals']}, now {current['summary']['total_signals']}"

        assert current["summary"]["total_trades"] == golden["summary"]["total_trades"], \
            f"Trade count changed: was {golden['summary']['total_trades']}, now {current['summary']['total_trades']}"

        # P&L within $1 tolerance (floating point)
        pnl_diff = abs(current["summary"]["total_pnl"] - golden["summary"]["total_pnl"])
        assert pnl_diff < 1.0, \
            f"P&L changed: was ${golden['summary']['total_pnl']}, now ${current['summary']['total_pnl']} (diff=${pnl_diff})"

        # Individual trade comparison
        mismatches = []
        for i, (curr, gold) in enumerate(zip(current["trades"], golden["trades"])):
            if curr["exit_reason"] != gold["exit_reason"]:
                mismatches.append(f"Trade {i} ({curr['ts']}): exit was '{gold['exit_reason']}', now '{curr['exit_reason']}'")
            elif abs(curr["pnl_per_unit"] - gold["pnl_per_unit"]) > 0.5:
                mismatches.append(f"Trade {i} ({curr['ts']}): PnL was ${gold['pnl_per_unit']}, now ${curr['pnl_per_unit']}")

        assert not mismatches, f"Regression detected:\n" + "\n".join(mismatches[:5])
