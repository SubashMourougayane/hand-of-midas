"""Fib V2 INTRADAY — A+D production port for live trading.

A leg: LONG  · lb=3 · hold=12h · session=london_ny · regime=any · PTP+1R · ext=2.618 · sl_buf=0.02
D leg: SHORT · lb=3 · hold=24h · session=all       · regime=any · PTP+1R · ext=2.618 · sl_buf=0.02

Base TF = Pivot TF = M15. Engine drives M15 bars. Every base bar IS a pivot bar.

Validated by:
  - research/fib_retrace/intraday_phase1_sweep.py (10,800 configs, A+D top survivors)
  - research/fib_retrace/intraday_adversarial_battery.py (15/15 audit pass)
  - research/fib_retrace/gen_intraday_dedup_parquets.py (per-leg dedup parity baseline)

Parity baseline: research/fib_retrace/intraday_dedup/{intraday_a,intraday_d}_trades.parquet
"""
from .config import (
    FibV2IntradayConfig,
    INTRADAY_A_LEG,
    INTRADAY_D_LEG,
    make_intraday_a_config,
    make_intraday_d_config,
)
from .strategy import FibV2IntradayBase, FibV2IntradayA, FibV2IntradayD

__all__ = [
    "FibV2IntradayConfig",
    "INTRADAY_A_LEG",
    "INTRADAY_D_LEG",
    "make_intraday_a_config",
    "make_intraday_d_config",
    "FibV2IntradayBase",
    "FibV2IntradayA",
    "FibV2IntradayD",
]
