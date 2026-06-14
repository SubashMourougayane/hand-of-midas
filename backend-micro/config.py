import os
import sys
from dotenv import load_dotenv

GOLD_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

EXECUTOR = os.getenv("EXECUTOR", "mt5")
OANDA_TOKEN = os.getenv("OANDA_TOKEN", "")
OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT", "")
OANDA_URL = os.getenv("OANDA_URL", "https://api-fxpractice.oanda.com/v3")
INSTRUMENT = "XAU_USD"

DB_URL = os.getenv("DATABASE_URL", "postgresql://subash@localhost:5432/golddigger")

ENGULFING_TOLERANCE = 0.10

# Micro Alpha-Sweep: rolling 4hr consolidation windows every 2 hours
# Full market coverage: 22:00 - 21:00 UTC (skip 21:00-22:00 = market close)
MICRO_ALPHA_SWEEP = {
    "consol_hours": 4,
    "scan_gap_hours": 2,
    "scan_after_hours": 6,
    "min_range": 5.0,
    "sweep_threshold": 2.0,
    "sl_buffer": 2.0,
    "min_sl": 5.0,
    "tp_multiplier": 2.0,
    "tp_structure_buffer": 2.0,
    "be_trigger_pct": 0.35,  # Filter #5 shipped 2026-06-13: PF 2.42→2.77, +$12k 21yr, +5.9pp WR
    "partial_tp_at_pct": 0.5,    # Filter #7 shipped 2026-06-13 (Variant A): PF 2.77→4.40, +$82k 21yr (+32.7%)
    "partial_tp_size": 0.5,
    "partial_arms_be": False,    # Variant A — BE on original schedule
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 0.75,  # 45 min (was 2hr — stale signals after 45min dilute PF)
    "max_trades_per_day": 3,
    "market_close_start": 21,
    "market_close_end": 22,
    # Filter shipped 2026-06-15: drop the 21-22 UTC block. The gate was
    # inherited from Oil Micro config but Gold Micro doesn't actually close
    # at that hour. BT 21-yr: PF 4.40→4.52, P&L +$26.8k (+8.0%), N +42.
    # Oil Micro keeps the block (regresses without it per prior audit).
    "disable_market_close": True,
}

STRATEGY_RISK = {"micro_alpha_sweep": 4.0, "mean_rev": 3.0, "cross_market": 2.0}
RISK_PCT = 4.0
MAX_UNITS = 100
YEARLY_CAPITAL = 5000.0

DD_STATE_ID = 3
TRADE_REF_PREFIX = "GD-MI-"

DD_PROTECTION = {
    "daily_max_loss": 400,
    "half_after_consecutive": 3,
    "consecutive_loss_pause": 5,
    "pause_signals": 2,
}


# Slippage Model — Deterministic (Filter #11, 2026-06-12). See backend/config.py.
def slippage(bar_range: float) -> float:
    return 0.04 + bar_range * 0.003


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
