"""Unit tests for DwxBridge — uses tmp_path to simulate the DWX dir layout."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from bt_engine.data.dwx_bridge import DEFAULT_DWX_DIR, DwxBridge


def _write(p: Path, content) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(content, str):
        content = json.dumps(content)
    p.write_text(content)


def test_read_json_happy_path(tmp_path: Path) -> None:
    bridge = DwxBridge(dwx_dir=tmp_path)
    _write(tmp_path / "account_info.json", {"balance": 1000.0})
    assert bridge.account_info() == {"balance": 1000.0}


def test_read_json_retries_on_partial_write(tmp_path: Path) -> None:
    bridge = DwxBridge(dwx_dir=tmp_path)
    _write(tmp_path / "market_data.json", '{"XAU":{"bid":100,')  # truncated
    # bumping a valid file mid-loop is hard to simulate, so test the error path
    with pytest.raises(RuntimeError):
        bridge.read_json("market_data.json", retries=2, backoff_s=0.001)


def test_is_alive_true_when_account_fresh(tmp_path: Path) -> None:
    _write(tmp_path / "account_info.json", {"balance": 1.0})
    bridge = DwxBridge(dwx_dir=tmp_path)
    assert bridge.is_alive() is True


def test_is_alive_false_when_no_file(tmp_path: Path) -> None:
    bridge = DwxBridge(dwx_dir=tmp_path)
    assert bridge.is_alive() is False


def test_is_alive_false_when_stale(tmp_path: Path) -> None:
    p = tmp_path / "account_info.json"
    _write(p, {"balance": 1.0})
    # backdate
    old = time.time() - 30
    import os

    os.utime(p, (old, old))
    bridge = DwxBridge(dwx_dir=tmp_path)
    # No fresh market_data.json either → genuinely dead.
    assert bridge.is_alive() is False


def test_is_alive_true_on_closed_market_via_market_data(tmp_path: Path) -> None:
    """Closed market (weekend/holiday): account_info goes stale because the EA
    only refreshes it on-tick, but the EA loop still rewrites market_data.json
    each cycle (frozen quote). That fresh market_data is valid proof-of-life so
    a leg can BOOT + adopt/manage existing positions. Regression 2026-07-03."""
    import os

    acct = tmp_path / "account_info.json"
    _write(acct, {"balance": 1.0, "server": "JustMarkets-Demo2"})
    old = time.time() - 3600  # 1h stale (market closed 1h ago)
    os.utime(acct, (old, old))
    # market_data rewritten just now (EA loop alive, frozen quote inside)
    _write(tmp_path / "market_data.json", {"XAUUSD.ecn": {"bid": 4175.6, "ask": 4175.7}})
    bridge = DwxBridge(dwx_dir=tmp_path)
    assert bridge.is_alive() is True


def test_is_alive_false_when_both_stale(tmp_path: Path) -> None:
    """Both files stale → EA genuinely down → refuse to boot."""
    import os

    for name in ("account_info.json", "market_data.json"):
        p = tmp_path / name
        _write(p, {"x": 1})
        old = time.time() - 60
        os.utime(p, (old, old))
    bridge = DwxBridge(dwx_dir=tmp_path)
    assert bridge.is_alive() is False


def test_bars_reads_symbol_filename(tmp_path: Path) -> None:
    bridge = DwxBridge(dwx_dir=tmp_path)
    _write(tmp_path / "bars_XAUUSD_ecn_H1.json", [{"time": "2026.06.29 00:00:00", "open": 100}])
    bars = bridge.bars("XAUUSD.ecn", "H1")
    assert isinstance(bars, list)
    assert bars[0]["open"] == 100


def test_default_dwx_dir_constant_set() -> None:
    assert "Common/Files/DWX" in str(DEFAULT_DWX_DIR)


def test_send_command_writes_file_no_wait(tmp_path: Path) -> None:
    bridge = DwxBridge(dwx_dir=tmp_path)
    # touch last_response to set baseline mtime
    _write(tmp_path / "last_response.json", {"success": False})
    bridge.send_command("CLOSE_ALL|", wait_response=False)
    cmds = list((tmp_path / "commands").glob("*.txt"))
    assert len(cmds) == 1
    assert cmds[0].read_text() == "CLOSE_ALL|"
