"""DWX file-bridge wrapper.

Wraps the MT5 DWX_Server EA file-based protocol:
    Common/Files/DWX/
        account_info.json       — periodic account snapshot
        market_data.json        — tick-level bid/ask per symbol
        bars_<SYMBOL>_<TF>.json — periodic OHLC dumps (M3/H1/D1 by default)
        commands/<id>.txt       — pipe-separated command (OPEN|MODIFY|CLOSE|CLOSE_ALL)
        last_response.json      — last command result

Atomic-read pattern: read full file, retry once on JSONDecodeError (file may be
mid-write). Mtime poll for change detection.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DWX_DIR = Path(
    "/Users/subash/Library/Application Support/net.metaquotes.wine.metatrader5"
    "/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
)


@dataclass
class DwxBridge:
    """Wraps the DWX Common/Files/DWX dir as a simple JSON IPC."""

    dwx_dir: Path = DEFAULT_DWX_DIR

    def __post_init__(self) -> None:
        self.dwx_dir = Path(self.dwx_dir)

    @property
    def commands_dir(self) -> Path:
        return self.dwx_dir / "commands"

    def is_alive(self) -> bool:
        """EA writes account_info.json every 2s. mtime within 10s == alive."""
        p = self.dwx_dir / "account_info.json"
        if not p.is_file():
            return False
        return (time.time() - p.stat().st_mtime) < 10

    def read_json(self, name: str, *, retries: int = 5, backoff_s: float = 0.05) -> Any:
        path = self.dwx_dir / name
        last_err: Exception | None = None
        for _ in range(retries):
            try:
                text = path.read_text()
                if not text.strip():
                    raise ValueError(f"{name} is empty")
                return json.loads(text)
            except (json.JSONDecodeError, FileNotFoundError, ValueError) as e:
                last_err = e
                time.sleep(backoff_s)
        raise RuntimeError(f"Failed to read {name} after {retries} retries: {last_err}")

    def mtime(self, name: str) -> float:
        path = self.dwx_dir / name
        if not path.is_file():
            return 0.0
        return path.stat().st_mtime

    def account_info(self) -> dict[str, Any]:
        return self.read_json("account_info.json")

    def market_data(self) -> dict[str, Any]:
        return self.read_json("market_data.json")

    def open_orders(self) -> dict[str, Any]:
        return self.read_json("open_orders.json")

    def closed_orders(self) -> list[dict[str, Any]]:
        """Recent closed positions written by EA on DEAL_ENTRY_OUT.

        Shape: list of dicts with ticket, symbol, type, volume, open_price,
        open_time, close_price, close_time, profit, swap, commission,
        magic, comment, deal_reason.
        """
        data = self.read_json("closed_orders.json")
        if isinstance(data, list):
            return data
        return []

    def bars(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        """Read bars JSON for a symbol+timeframe. Symbol dots replaced with _.

        EA writes M3/H1/D1 by default at 3-second cadence with fixed counts:
        M3=500 bars, H1=30 bars, D1=5 bars.
        """
        safe = symbol.replace(".", "_")
        return self.read_json(f"bars_{safe}_{timeframe}.json")

    def last_response(self) -> dict[str, Any]:
        return self.read_json("last_response.json")

    def send_command(self, command: str, *, wait_response: bool = True, timeout_s: float = 5.0) -> dict[str, Any] | None:
        """Write a pipe-separated command to commands/<id>.txt.

        Format examples:
            "OPEN|XAUUSD.ecn|BUY|0.01|0.0|1980.0|2020.0|tag"
            "MODIFY|123456|1985.0|2025.0"
            "CLOSE|123456"
            "CLOSE_ALL|"

        If wait_response, polls last_response.json mtime until it changes.
        """
        self.commands_dir.mkdir(parents=True, exist_ok=True)
        cmd_id = uuid.uuid4().hex[:12]
        cmd_path = self.commands_dir / f"cmd_{cmd_id}.txt"

        before_mtime = self.mtime("last_response.json")
        cmd_path.write_text(command)
        if not wait_response:
            return None

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            now_mtime = self.mtime("last_response.json")
            if now_mtime > before_mtime:
                try:
                    return self.last_response()
                except RuntimeError:
                    pass
            # also bail if EA processed (deleted) the command
            if not cmd_path.exists() and self.mtime("last_response.json") > before_mtime:
                return self.last_response()
            time.sleep(0.05)
        raise TimeoutError(f"No response within {timeout_s}s for command: {command}")
