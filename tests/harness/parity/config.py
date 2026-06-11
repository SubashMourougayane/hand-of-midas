"""Per-system configuration for the parity harness.

Each entry describes how to invoke the live signal-gen path and the
backtest signal-gen path for one of the four trading systems. The harness
uses this dict to drive parametrized pytest cases.

Phase 1 ships gold_micro only. Other systems are stubbed out and will be
filled in as later phases land.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemConfig:
    """Static description of one trading system, for harness use."""
    key: str                       # short id, e.g. "gold_micro"
    label: str                     # human label, e.g. "Gold Micro"
    instrument: str                # e.g. "XAU_USD" (live's instrument arg)
    h1_csv: str                    # backend/data/cache.py file name
    m3_csv: str
    daily_csv: str
    sweep_threshold: float         # used by parity score normalization
    # The four hooks below are referenced by name and resolved lazily so
    # importing config.py does NOT pull in the four scheduler modules
    # at once (avoids the sys.modules['config'] pollution that breaks
    # test_14_oil_micro). The runner imports them on demand.
    live_module_path: str          # Python import path
    live_core_fn_name: str
    backtest_module_path: str
    backtest_fn_name: str
    config_module_path: str        # for live config (MICRO_ALPHA_SWEEP, etc.)
    strategy_config_key: str       # the dict to pull (e.g. "MICRO_ALPHA_SWEEP")


# Phase 1: gold_micro only is filled. Other systems are stubs (will skip
# with pytest.skip until their phase lands).
SYSTEMS: dict[str, SystemConfig] = {
    "gold_micro": SystemConfig(
        key="gold_micro",
        label="Gold Micro",
        instrument="XAU_USD",
        h1_csv="XAU_USD_H1.csv",
        m3_csv="XAU_USD_M3.csv",
        daily_csv="XAU_USD_D.csv",
        sweep_threshold=2.0,        # MICRO_ALPHA_SWEEP["sweep_threshold"] for gold
        live_module_path="scanner.scheduler",   # resolved with backend-micro on sys.path
        live_core_fn_name="_run_micro_sweep_core",
        backtest_module_path="backend.strategies.micro_alpha_sweep",
        backtest_fn_name="generate_signals",
        config_module_path="config",
        strategy_config_key="MICRO_ALPHA_SWEEP",
    ),
    # Phase 3 — oil_micro
    # Phase 4 — gold_macro, oil_macro
}


# Default replay window. Overridable via run_parity_check(days=...).
DEFAULT_DAYS = 7
