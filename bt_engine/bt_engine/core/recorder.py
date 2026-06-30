"""TradeRecorder — finalises CSV + DB rows. Streaming during run; finalise writes summary."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_TRADE_COLUMNS = (
    "trade_ref", "run_id", "symbol", "timeframe",
    "zone_id", "zone_tf", "spec_name", "direction", "side",
    "upper", "lower",
    "created_timestamp", "base_timestamp", "impulse_start_ts", "impulse_end_ts",
    "touch_timestamp", "confirm_timestamp",
    "entry_timestamp", "entry_price", "stop_price", "take_profit_price", "risk_units",
    "exit_timestamp", "exit_price", "exit_reason", "bars_held",
    "bracket_1r_outcome", "cost_r", "gross_r", "net_r",
    "confluence_score", "clean_top3_rank",
)


@dataclass
class TradeRecorder:
    """Collects closed-trade rows in memory; writes CSV at finalize().

    DB writes are handled directly by TradeRepo at trade close time (streaming).
    This recorder is for CSV parity diffs and offline reporting.
    """

    out_dir: Path
    filename: str = "sdr001_trades.csv"
    rows: list[dict[str, Any]] = field(default_factory=list)

    def record(self, row: dict[str, Any]) -> None:
        self.rows.append(row)

    def finalize(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / self.filename
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_TRADE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for r in self.rows:
                writer.writerow(r)
        return path
