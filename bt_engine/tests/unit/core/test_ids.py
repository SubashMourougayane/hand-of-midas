"""Unit tests for id generators."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd

from bt_engine.core.ids import make_run_ref, make_trade_ref, new_run_id, new_trade_id


def test_new_trade_id_returns_uuid() -> None:
    tid = new_trade_id()
    assert isinstance(tid, uuid.UUID)


def test_new_run_id_returns_uuid() -> None:
    rid = new_run_id()
    assert isinstance(rid, uuid.UUID)


def test_run_ref_bt_format() -> None:
    when = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    ref = make_run_ref("sdr001", "bt", when=when, seq=7)
    assert ref == "BT-20260629-SDR001-0007"


def test_run_ref_live_format() -> None:
    when = datetime(2026, 6, 29, tzinfo=timezone.utc)
    ref = make_run_ref("sdr001", "live", when=when, seq=1)
    assert ref == "LIVE-20260629-SDR001-0001"


def test_trade_ref_format_supply() -> None:
    ts = pd.Timestamp("2019-06-12T20:00:00Z")
    assert make_trade_ref("sdr001", ts, "supply", 1) == "SDR001-2019-06-12-S-0001"


def test_trade_ref_format_demand() -> None:
    ts = pd.Timestamp("2019-06-12T20:00:00Z")
    assert make_trade_ref("sdr001", ts, "demand", 42) == "SDR001-2019-06-12-D-0042"
