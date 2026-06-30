"""Unit tests for CLI parser."""
from __future__ import annotations

import pytest

from bt_engine.runner.cli import build_parser


def test_parser_bt_command() -> None:
    p = build_parser()
    ns = p.parse_args(["bt", "--strategy", "sdr001", "--out", "/tmp/x"])
    assert ns.cmd == "bt"
    assert ns.strategy == "sdr001"


def test_parser_journal_command() -> None:
    p = build_parser()
    ns = p.parse_args(["journal", "--trade-ref", "SDR001-2019-06-12-S-0001-39"])
    assert ns.cmd == "journal"
    assert ns.trade_ref == "SDR001-2019-06-12-S-0001-39"


def test_parser_requires_subcommand() -> None:
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args([])
