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
MICRO_ALPHA_SWEEP = {
    "consol_hours": 4,
    "scan_gap_hours": 2,
    "scan_after_hours": 6,
    "min_range": 5.0,
    "sweep_threshold": 2.0,
    "sl_buffer": 0.30,
    "min_sl": 5.0,
    "tp_multiplier": 2.0,
    "be_trigger_pct": 0.50,
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 2,
    "max_trades_per_day": 3,
    "scan_start_hour": 0,
    "scan_end_hour": 20,
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


def slippage(bar_range: float) -> float:
    import numpy as np
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
