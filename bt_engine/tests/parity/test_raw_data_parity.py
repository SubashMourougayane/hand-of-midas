"""Real raw-data parity gate: SDR-001 generator from M1 bars must match the
frozen ledger row-for-row on every headline metric.

Distinct from `test_summary_parity.py` (which reads the ledger directly).
This test runs the strategy logic on raw bars and verifies the OUTPUT.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bt_engine.strategies.sdr001.generator import generate_events_from_raw


REPO_ROOT = Path(__file__).resolve().parents[3]
RAW = REPO_ROOT / "research-baseline" / "data" / "raw" / "XAUUSD.ecn_M1_201601040000_202606181903.csv"
SLEEVE = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


pytestmark = pytest.mark.skipif(
    not (RAW.is_file() and SLEEVE.is_file()),
    reason="baseline data missing",
)


def _load_raw() -> pd.DataFrame:
    raw = pd.read_csv(RAW, sep="\t")
    raw["timestamp"] = pd.to_datetime(
        raw["<DATE>"].astype(str) + " " + raw["<TIME>"].astype(str),
        format="%Y.%m.%d %H:%M:%S",
        utc=True,
    )
    raw = raw.rename(
        columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
                 "<CLOSE>": "close", "<TICKVOL>": "volume"}
    )
    raw = raw[["timestamp", "open", "high", "low", "close", "volume"]]
    for c in ["open", "high", "low", "close", "volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    return raw


def _headline(filtered: pd.DataFrame) -> dict:
    r = filtered["net_1r_after_cost"].astype(float)
    wr = float((r > 0).mean())
    gross_w = float(r[r > 0].sum())
    gross_l = float(-r[r < 0].sum())
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    eq = r.cumsum().values
    peak = np.maximum.accumulate(eq)
    maxdd = float((eq - peak).min())
    years = pd.to_datetime(filtered["entry_timestamp"], utc=True).dt.year
    yearly = filtered.assign(_y=years).groupby("_y")["net_1r_after_cost"].sum()
    pos = int((yearly > 0).sum())
    total = len(yearly)
    return {
        "trades": int(len(filtered)),
        "net_r": float(r.sum()),
        "win_rate": wr,
        "profit_factor": pf,
        "max_drawdown_r": maxdd,
        "pos_years": f"{pos}/{total}",
    }


def test_raw_data_parity_full_sample() -> None:
    raw = _load_raw()
    events = generate_events_from_raw(
        raw,
        start=pd.Timestamp("2019-01-01", tz="UTC"),
        end=pd.Timestamp("2026-06-19", tz="UTC"),
    )
    # full m15_2c_1atr universe before sleeve1 filter
    assert len(events) == 13720, f"event count mismatch: {len(events)} != 13720"

    sleeve = pd.read_csv(SLEEVE)
    sleeve_zones = set(sleeve["zone_id"])
    filtered = (
        events[events["zone_id"].isin(sleeve_zones)]
        .sort_values("entry_timestamp")
        .reset_index(drop=True)
    )
    assert len(filtered) == 1032, f"sleeve1 filter mismatch: {len(filtered)} != 1032"

    h = _headline(filtered)
    assert h["trades"] == 1032
    assert h["net_r"] == pytest.approx(256.106675, abs=1e-4)
    assert h["win_rate"] == pytest.approx(0.638566, abs=1e-6)
    assert h["profit_factor"] == pytest.approx(1.683757, abs=1e-6)
    assert h["max_drawdown_r"] == pytest.approx(-12.694926, abs=1e-4)
    assert h["pos_years"] == "8/8"
