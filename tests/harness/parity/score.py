"""ParityScore — aggregate diffs into a per-system, per-window score.

The parity_pct formula is intentionally simple and explicit so future
tuning is visible (not buried in heuristic glue):

    parity_pct = 0.50 * coverage_ratio
               + 0.30 * direction_agreement_ratio
               + 0.20 * (1 - clamped(avg_entry_delta_normalized, 0, 1))

where:
    coverage_ratio              = signals_in_both / max(BT_count, Live_count, 1)
    direction_agreement_ratio   = direction_agreements / max(signals_in_both, 1)
    avg_entry_delta_normalized  = avg(|entry_delta|) / sweep_threshold
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone
from typing import Iterable

from .diff import SignalDiff


REPORTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "parity_reports"))


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _git_short_sha() -> str:
    """Best-effort git SHA. Returns 'nogit' if anything goes wrong (CI without
    .git, harness running on a tarball, etc.). Never raises."""
    try:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
        result = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "nogit"


@dataclass
class ParityScore:
    system: str
    date_range: tuple[date, date]
    total_signals_backtest: int
    total_signals_live: int
    signals_in_both: int
    signals_only_in_backtest: int
    signals_only_in_live: int
    direction_agreements: int
    direction_disagreements: int
    avg_entry_price_delta: float
    max_entry_price_delta: float
    avg_timestamp_delta_secs: float
    skip_reason_histogram_backtest: dict[str, int]
    skip_reason_histogram_live: dict[str, int]
    parity_pct: float
    formula_version: str = "v1.0"
    weights: dict[str, float] = field(default_factory=lambda: {
        "coverage": 0.50,
        "direction_agreement": 0.30,
        "entry_price_drift": 0.20,
    })
    sweep_threshold_used: float = 0.0
    diffs: list[SignalDiff] = field(default_factory=list)
    data_files: tuple[str, ...] = ()

    def summary_line(self) -> str:
        return (
            f"{self.system}: parity={self.parity_pct:.1%} "
            f"(BT={self.total_signals_backtest}, "
            f"Live={self.total_signals_live}, "
            f"in_both={self.signals_in_both}, "
            f"agree={self.direction_agreements}, "
            f"disagree={self.direction_disagreements})"
        )

    def write_json(self, base_dir: str | None = None) -> str:
        """Write the parity report JSON to <base_dir>/parity_<utc_date>_<sha>_<system>.json.

        Returns the absolute file path.
        """
        if base_dir is None:
            base_dir = REPORTS_DIR
        os.makedirs(base_dir, exist_ok=True)
        sha = _git_short_sha()
        utc_date = datetime.now(timezone.utc).date().isoformat()
        fname = f"parity_{utc_date}_{sha}_{self.system}.json"
        path = os.path.join(base_dir, fname)

        payload = {
            "system": self.system,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": sha,
            "date_range": [self.date_range[0].isoformat(), self.date_range[1].isoformat()],
            "data_files": list(self.data_files),
            "formula_version": self.formula_version,
            "weights": self.weights,
            "sweep_threshold_used": self.sweep_threshold_used,
            "parity_score": {
                "parity_pct": self.parity_pct,
                "total_signals_backtest": self.total_signals_backtest,
                "total_signals_live": self.total_signals_live,
                "signals_in_both": self.signals_in_both,
                "signals_only_in_backtest": self.signals_only_in_backtest,
                "signals_only_in_live": self.signals_only_in_live,
                "direction_agreements": self.direction_agreements,
                "direction_disagreements": self.direction_disagreements,
                "avg_entry_price_delta": self.avg_entry_price_delta,
                "max_entry_price_delta": self.max_entry_price_delta,
                "avg_timestamp_delta_secs": self.avg_timestamp_delta_secs,
                "skip_reason_histogram_backtest": self.skip_reason_histogram_backtest,
                "skip_reason_histogram_live": self.skip_reason_histogram_live,
            },
            "diffs": [d.to_dict() for d in self.diffs],
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        return path


def score_parity(
    system: str,
    date_range: tuple[date, date],
    diffs: list[SignalDiff],
    sweep_threshold: float,
    data_files: tuple[str, ...] = (),
) -> ParityScore:
    """Aggregate diffs → ParityScore. Pure function, no I/O."""

    bt_count = sum(1 for d in diffs if d.in_backtest)
    live_count = sum(1 for d in diffs if d.in_live)
    in_both = sum(1 for d in diffs if d.in_backtest and d.in_live)
    only_bt = sum(1 for d in diffs if d.in_backtest and not d.in_live)
    only_live = sum(1 for d in diffs if d.in_live and not d.in_backtest)
    dir_agree = sum(1 for d in diffs if d.in_backtest and d.in_live and d.direction_match)
    dir_disagree = sum(1 for d in diffs if d.in_backtest and d.in_live and not d.direction_match)

    entry_deltas = [abs(d.entry_price_delta) for d in diffs
                    if d.entry_price_delta is not None]
    avg_entry_delta = sum(entry_deltas) / len(entry_deltas) if entry_deltas else 0.0
    max_entry_delta = max(entry_deltas) if entry_deltas else 0.0

    ts_deltas = [abs(d.timestamp_delta_secs) for d in diffs
                 if d.timestamp_delta_secs is not None]
    avg_ts_delta = sum(ts_deltas) / len(ts_deltas) if ts_deltas else 0.0

    bt_skip_hist: Counter[str] = Counter()
    live_skip_hist: Counter[str] = Counter()
    for d in diffs:
        if d.backtest_record and d.backtest_record.skip_reason:
            bt_skip_hist[d.backtest_record.skip_reason] += 1
        if d.live_record and d.live_record.skip_reason:
            live_skip_hist[d.live_record.skip_reason] += 1

    coverage_ratio = in_both / max(bt_count, live_count, 1)
    direction_ratio = dir_agree / max(in_both, 1)
    if sweep_threshold <= 0:
        # Avoid div-by-zero; treat any drift as full miss.
        normalized_drift = 1.0 if avg_entry_delta > 0 else 0.0
    else:
        normalized_drift = _clamp(avg_entry_delta / sweep_threshold, 0.0, 1.0)
    drift_factor = 1.0 - normalized_drift

    weights = {"coverage": 0.50, "direction_agreement": 0.30, "entry_price_drift": 0.20}
    parity_pct = (
        weights["coverage"] * coverage_ratio
        + weights["direction_agreement"] * direction_ratio
        + weights["entry_price_drift"] * drift_factor
    )

    return ParityScore(
        system=system,
        date_range=date_range,
        total_signals_backtest=bt_count,
        total_signals_live=live_count,
        signals_in_both=in_both,
        signals_only_in_backtest=only_bt,
        signals_only_in_live=only_live,
        direction_agreements=dir_agree,
        direction_disagreements=dir_disagree,
        avg_entry_price_delta=avg_entry_delta,
        max_entry_price_delta=max_entry_delta,
        avg_timestamp_delta_secs=avg_ts_delta,
        skip_reason_histogram_backtest=dict(bt_skip_hist),
        skip_reason_histogram_live=dict(live_skip_hist),
        parity_pct=parity_pct,
        weights=weights,
        sweep_threshold_used=sweep_threshold,
        diffs=diffs,
        data_files=data_files,
    )
