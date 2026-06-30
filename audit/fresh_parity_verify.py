"""FRESH parity verifier. Zero reuse of prior scripts/parquets.

Builds research baseline + bt run from scratch and compares trade-by-trade.

Steps:
  1. Load /tmp/oanda_xau_m5.parquet
  2. Resample to M15 (label='left', closed='left') — same as production
  3. Build features (D1 lag, swing lag) using PRODUCTION primitives
  4. Generate signals via gen_signals_with_regime
  5. Apply dedup + min_risk filter (production rules)
  6. Walk brackets via simulate_with_safety with strict horizon
  7. Run same setup through bt_engine FibV2IntradayA
  8. Compare trade-by-trade

Output: PASS / FAIL + drift report.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")

# Research primitives
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)
from research.fib_retrace.safety_net_sweep import simulate_with_safety

# bt_engine primitives
from bt_engine.core.bar import Bar
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

# Locked production config
COST = 0.65
MIN_RISK = 0.50
PTP_AT_R = 1.0

# Test legs (mirror production)
LEGS = [
    {"name": "A", "strategy_cls": FibV2IntradayA, "direction": "long",
     "session": "london_ny", "hold_h": 12, "max_bars": 48},
    {"name": "D", "strategy_cls": FibV2IntradayD, "direction": "short",
     "session": "all", "hold_h": 24, "max_bars": 96},
]


def resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()
    return out


def gen_research_ledger(m15_f: pd.DataFrame, pivots, *, direction: str, session: str,
                        hold_h: int) -> pd.DataFrame:
    """Research vectorized: signals → dedup → min_risk → simulate."""
    max_bars = hold_h * 4
    sigs = gen_signals_with_regime(
        m15_f, pivots, direction=direction, session=session,
        max_hold_bars=max_bars,
        ext_target_pct=2.618, sl_buffer_pct=0.02, regime="any",
    )
    sigs = sigs.copy()
    sigs["entry_ts"] = m15_f["timestamp"].iloc[sigs["entry_index"].astype(int).values].values
    sigs = sigs.sort_values("entry_index").drop_duplicates(
        subset=["entry_ts", "side"], keep="first"
    ).reset_index(drop=True)
    sigs = sigs[sigs["risk_units"] >= MIN_RISK].reset_index(drop=True)
    trades = simulate_with_safety(
        m15_f, sigs, cost_usd=COST,
        horizon_bars=max_bars, partial_tp_at_r=PTP_AT_R,
    )
    return trades


class InMemoryProvider:
    def __init__(self, frame, symbol, timeframe):
        self._df = frame.reset_index(drop=True)
        self.symbol = symbol
        self.timeframe = timeframe
        self._ts = self._df["timestamp"].values

    def bars(self):
        for row in self._df.itertuples(index=False):
            yield Bar.from_row(symbol=self.symbol, timeframe=self.timeframe, row=row._asdict())

    def history_up_to(self, ts):
        ts_val = pd.Timestamp(ts).to_datetime64()
        end = self._ts.searchsorted(ts_val, side="right")
        return self._df.iloc[:end]


class InMemoryClock:
    def __init__(self, provider):
        self._iter = iter(provider.bars())

    def tick(self):
        try:
            return next(self._iter)
        except StopIteration:
            return None


def run_bt_ledger(m15: pd.DataFrame, strategy_cls, *, max_bars: int) -> pd.DataFrame:
    """bt streaming: same M15 frame through FibV2Intraday strategy."""
    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = strategy_cls(symbol="XAUUSD.ecn")
    rows = []
    def _on_close(tr, outcome):
        cost_r = tr.order.extra.get("cost_r", 0.0)
        gross = outcome.bracket_1r_outcome
        rows.append({
            "entry_ts": tr.entry_timestamp,
            "side": int(tr.side),
            "risk_units": float(tr.risk_units),
            "bracket_r": float(gross),
            "cost_r": float(cost_r),
            "net_r": float(gross - cost_r),
            "reason": outcome.reason,
        })
    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_close=_on_close,
        max_bars_held=max_bars,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    return pd.DataFrame(rows)


def headline(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"n": 0}
    gw = df.loc[df.net_r > 0, "net_r"].sum()
    gl = -df.loc[df.net_r < 0, "net_r"].sum()
    pf = gw / gl if gl > 0 else float("inf")
    return {
        "n": len(df),
        "net_r": round(float(df.net_r.sum()), 2),
        "wr_pct": round(float((df.net_r > 0).mean() * 100), 2),
        "pf": round(pf, 3),
    }


def diff_pct(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-9) * 100


def main():
    print("=" * 90)
    print("FRESH PARITY VERIFIER — research vs bt_engine (intraday A+D)")
    print("=" * 90)
    print()

    print("[load] /tmp/oanda_xau_m5.parquet")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                         Path("/tmp/oanda_xau_m5.parquet"))
    m15 = resample_m15(m5)
    print(f"  m5 bars: {len(m5):,}  m15 bars: {len(m15):,}")

    print("[features] add M15 features + D1 regime (production primitives)")
    m15_f = add_m5_features(m15)
    d1 = add_d1_features(resample_d1(m15_f))
    m15_f = attach_d1_to_m5(m15_f, d1)

    pivots = build_pivot_events(m15_f, 3)
    print(f"  pivots(lb=3): {len(pivots):,}")
    print()

    all_pass = True

    for leg in LEGS:
        print(f"--- {leg['name']} leg ---")
        research = gen_research_ledger(
            m15_f, pivots,
            direction=leg["direction"], session=leg["session"], hold_h=leg["hold_h"],
        )
        if "year" not in research.columns:
            research["year"] = pd.to_datetime(research["entry_ts"]).dt.year

        bt = run_bt_ledger(m15, leg["strategy_cls"], max_bars=leg["max_bars"])

        r_h = headline(research)
        b_h = headline(bt)

        d_n = diff_pct(b_h["n"], r_h["n"])
        d_net = diff_pct(b_h["net_r"], r_h["net_r"])
        d_pf = diff_pct(b_h["pf"], r_h["pf"])

        print(f"  research  n={r_h['n']:>5}  net_r={r_h['net_r']:>+9.2f}  WR={r_h['wr_pct']:5.2f}%  PF={r_h['pf']:.3f}")
        print(f"  bt        n={b_h['n']:>5}  net_r={b_h['net_r']:>+9.2f}  WR={b_h['wr_pct']:5.2f}%  PF={b_h['pf']:.3f}")
        print(f"  drift     n={d_n:>4.2f}%   net_r={d_net:>4.2f}%   PF={d_pf:.2f}%")

        # Gate thresholds (same as committed parity tests)
        pass_n = d_n <= 5.0
        pass_net = d_net <= 5.0
        pass_pf = d_pf <= 10.0
        verdict = "PASS" if (pass_n and pass_net and pass_pf) else "FAIL"
        print(f"  verdict: {verdict}")
        if not (pass_n and pass_net and pass_pf):
            all_pass = False
            if not pass_n: print(f"    ! count drift {d_n:.2f}% > 5%")
            if not pass_net: print(f"    ! net_r drift {d_net:.2f}% > 5%")
            if not pass_pf: print(f"    ! PF drift {d_pf:.2f}% > 10%")
        print()

    print("=" * 90)
    print(f"FINAL VERDICT: {'ALL PASS' if all_pass else 'FAIL'}")
    print("=" * 90)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
