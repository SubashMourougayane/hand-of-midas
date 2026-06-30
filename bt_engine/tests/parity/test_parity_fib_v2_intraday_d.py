"""BLOCKING parity gate: FibV2IntradayD bt_engine vs research dedup parquet."""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayD

from ._fib_v2_helper import InMemoryClock, InMemoryProvider


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
RESEARCH_PARQUET = Path(
    "/Users/subash/SUBASH/GoldDigger/research/fib_retrace/intraday_dedup/"
    "intraday_d_trades.parquet"
)
MAX_BARS_HELD_D = 96  # 24h * 4 bars/h — STRICT cap to match research (no doubling)


def _resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()


def _pf(df: pd.DataFrame, col: str = "net_r") -> float:
    gw = df.loc[df[col] > 0, col].sum()
    gl = -df.loc[df[col] < 0, col].sum()
    return gw / gl if gl > 0 else float("inf")


@pytest.mark.skipif(
    not (XAU_M5.exists() and RESEARCH_PARQUET.exists()),
    reason="OANDA M5 or research dedup parquet missing",
)
def test_parity_intraday_d_count_and_pnl():
    research = pd.read_parquet(RESEARCH_PARQUET)
    research["entry_ts"] = pd.to_datetime(research["entry_ts"], utc=True)

    raw = pd.read_parquet(XAU_M5)
    if raw["timestamp"].dt.tz is None:
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
    raw = raw.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    m15 = _resample_m15(raw)

    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = FibV2IntradayD(symbol="XAUUSD.ecn")

    bt_rows = []
    def _on_close(tr, outcome):
        cost_r = tr.order.extra.get("cost_r", 0.0)
        gross = outcome.bracket_1r_outcome
        bt_rows.append({
            "entry_ts": tr.entry_timestamp,
            "side": int(tr.side),
            "risk_units": float(tr.risk_units),
            "bracket_r": float(gross),
            "cost_r": float(cost_r),
            "net_r": float(gross - cost_r),
        })

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_close=_on_close,
        max_bars_held=MAX_BARS_HELD_D,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    bt = pd.DataFrame(bt_rows)
    assert len(bt) > 0, "bt produced 0 trades"

    n_research = len(research)
    n_bt = len(bt)
    count_diff_pct = abs(n_bt - n_research) / max(n_research, 1) * 100

    r_net = float(research["net_r"].sum())
    b_net = float(bt["net_r"].sum())
    net_diff_pct = abs(b_net - r_net) / max(abs(r_net), 1e-9) * 100

    r_pf = _pf(research)
    b_pf = _pf(bt)
    pf_diff_pct = abs(b_pf - r_pf) / max(abs(r_pf), 1e-9) * 100

    print(f"\n[parity D] bt n={n_bt}  research n={n_research}  diff={count_diff_pct:.2f}%")
    print(f"[parity D] bt net_r={b_net:+.1f}  research net_r={r_net:+.1f}  diff={net_diff_pct:.2f}%")
    print(f"[parity D] bt PF={b_pf:.3f}  research PF={r_pf:.3f}  diff={pf_diff_pct:.2f}%")

    assert count_diff_pct <= 5.0, f"trade count drift {count_diff_pct:.2f}% > 5%"
    assert net_diff_pct <= 5.0, f"net_r drift {net_diff_pct:.2f}% > 5%"
    assert pf_diff_pct <= 10.0, f"PF drift {pf_diff_pct:.2f}% > 10%"
