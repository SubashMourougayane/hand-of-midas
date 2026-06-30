"""SDR-001 configuration loader."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SDR001Config:
    strategy_id: str
    strategy_name: str
    instrument: str
    base_sleeve: str
    data_start_utc: str
    data_end_utc: str
    primary_trade_file: str
    primary_r_column: str
    base_filters: dict[str, Any]
    execution_assumptions: dict[str, Any]
    headline_full_sample: dict[str, Any]
    headline_oos: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> "SDR001Config":
        p = Path(path)
        data = json.loads(p.read_text())
        return cls(
            strategy_id=data["strategy_id"],
            strategy_name=data["strategy_name"],
            instrument=data["instrument"],
            base_sleeve=data["base_sleeve"],
            data_start_utc=data["data_start_utc"],
            data_end_utc=data["data_end_utc"],
            primary_trade_file=data["primary_trade_file"],
            primary_r_column=data["primary_r_column"],
            base_filters=data["base_filters"],
            execution_assumptions=data["execution_assumptions"],
            headline_full_sample=data["headline_full_sample"],
            headline_oos=data["headline_oos"],
            raw=data,
        )

    @property
    def expected_trades(self) -> int:
        return int(self.headline_full_sample["trades"])

    @property
    def expected_net_r(self) -> float:
        return float(self.headline_full_sample["net_r"])

    @property
    def expected_win_rate(self) -> float:
        return float(self.headline_full_sample["win_rate"])

    @property
    def expected_profit_factor(self) -> float:
        return float(self.headline_full_sample["profit_factor"])

    @property
    def expected_max_dd_r(self) -> float:
        return float(self.headline_full_sample["max_drawdown_r"])
