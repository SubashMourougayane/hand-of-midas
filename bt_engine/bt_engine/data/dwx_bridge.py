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


# Mac/Wine MT5 default. On native Windows the DWX dir lives under the real
# MetaQuotes terminal path, e.g.
#   C:\Users\<user>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\DWX
# Set the DWX_DIR env var to override (per-machine, no hardcoded path in code).
_MAC_WINE_DWX_DIR = Path(
    "/Users/subash/Library/Application Support/net.metaquotes.wine.metatrader5"
    "/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"
)


def _default_dwx_dir() -> Path:
    """Resolve the DWX bridge dir: DWX_DIR env override, else Mac/Wine default."""
    env = os.environ.get("DWX_DIR")
    return Path(env) if env else _MAC_WINE_DWX_DIR


# Backwards-compatible module constant (resolved at import time).
DEFAULT_DWX_DIR = _default_dwx_dir()


@dataclass
class DwxBridge:
    """Wraps the DWX Common/Files/DWX dir as a simple JSON IPC."""

    dwx_dir: Path = None  # type: ignore[assignment]  # resolved in __post_init__

    def __post_init__(self) -> None:
        # Resolve at construction (not class-def) so a DWX_DIR set after import
        # — e.g. by the live runner's env — is still honored.
        if self.dwx_dir is None:
            self.dwx_dir = _default_dwx_dir()
        self.dwx_dir = Path(self.dwx_dir)

    @property
    def commands_dir(self) -> Path:
        return self.dwx_dir / "commands"

    def is_alive(self, max_age_s: float = 10.0) -> bool:
        """EA rewrites account_info.json + market_data.json every ~2s while it's
        running. account_info refreshes ON-TICK, so on a CLOSED market (weekend /
        holiday) it goes stale even though the EA loop is perfectly alive and still
        rewriting market_data.json each cycle (with a frozen quote).

        Proof-of-life = EITHER file fresh within max_age_s. This lets a leg BOOT +
        adopt/manage existing positions over a closed market instead of crash-
        looping on the account_info freshness check. New entries can't fire on a
        closed market anyway (no new bar closes → no signals), and the equity
        sizer tracks its own equity (not account_info), so accepting a fresh
        market_data.json here does NOT relax any new-entry sizing safety.
        """
        now = time.time()
        for name in ("account_info.json", "market_data.json"):
            p = self.dwx_dir / name
            if p.is_file() and (now - p.stat().st_mtime) < max_age_s:
                return True
        return False

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
