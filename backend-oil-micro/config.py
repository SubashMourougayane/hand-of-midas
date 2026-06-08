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
INSTRUMENT = "BCO_USD"

DB_URL = os.getenv("DATABASE_URL", "postgresql://subash@localhost:5432/golddigger")

ENGULFING_TOLERANCE = 0.01  # $0.01 for Oil (sub-spread noise)

# Oil Micro Alpha-Sweep: rolling 4hr consolidation windows every 2 hours
# Same architecture as Gold Micro but with Oil-scaled thresholds
# Research: PF 6.98, WR 85.9%, $1.21M (20yr, $5k capital, 4% risk)
MICRO_ALPHA_SWEEP = {
    "consol_hours": 4,
    "scan_gap_hours": 2,
    "scan_after_hours": 6,
    "min_range": 0.33,              # $0.33 min range (vs $5 for gold)
    "sweep_threshold": 0.13,        # $0.13 extension (vs $2 for gold)
    "sl_buffer": 0.20,              # $0.20 buffer (wider — research optimal)
    "min_sl": 0.10,                 # $0.10 min SL
    "tp_multiplier": 2.0,
    "tp_structure_buffer": 0.13,    # $0.13 TP buffer (vs $2 for gold)
    "be_trigger_pct": 0.50,
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 0.75,  # 45 min (same as Gold Micro)
    "max_trades_per_day": 3,
    "market_close_start": 21,
    "market_close_end": 22,
}

STRATEGY_RISK = {"micro_alpha_sweep_oil": 4.0}
RISK_PCT = 4.0
MAX_UNITS = 5000  # 5,000 barrels (5 lots)
YEARLY_CAPITAL = 5000.0

DD_STATE_ID = 4  # Separate DD state for Oil Micro (Gold=1, Oil Macro=2, Gold Micro=3, Oil Micro=4)
TRADE_REF_PREFIX = "OIL-MI-"

DD_PROTECTION = {
    "daily_max_loss": 400,
    "half_after_consecutive": 3,
    "consecutive_loss_pause": 5,
    "pause_signals": 2,
}


def slippage(bar_range: float) -> float:
    import numpy as np
    return 0.03 + bar_range * 0.01 + np.random.uniform(0, 0.005)


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
