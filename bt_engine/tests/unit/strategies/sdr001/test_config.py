"""Unit tests for SDR001Config loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from bt_engine.strategies.sdr001.config import SDR001Config


REPO_ROOT = Path(__file__).resolve().parents[5]
CFG = REPO_ROOT / "research-baseline" / "config" / "xau_sdr_001_config.json"


pytestmark = pytest.mark.skipif(not CFG.is_file(), reason="baseline config missing")


def test_load_config_exposes_headline_numbers() -> None:
    c = SDR001Config.from_json(CFG)
    assert c.strategy_id == "XAU-SDR-001"
    assert c.instrument == "XAUUSD"
    assert c.expected_trades == 1032
    assert c.expected_net_r == pytest.approx(256.106675)
    assert c.expected_win_rate == pytest.approx(0.638566)
    assert c.expected_profit_factor == pytest.approx(1.683757)
    assert c.expected_max_dd_r == pytest.approx(-12.694926)
