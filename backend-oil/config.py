import os
import sys
from dotenv import load_dotenv

# Share common modules from the gold backend
GOLD_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

OANDA_TOKEN = os.getenv("OANDA_TOKEN", "")
OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT", "")
OANDA_URL = os.getenv("OANDA_URL", "https://api-fxpractice.oanda.com/v3")
INSTRUMENT = "BCO_USD"

DB_URL = os.getenv("DATABASE_URL", "postgresql://subash@localhost:5432/golddigger")

SESSIONS_UTC = {
    "asia": {"start": 0, "end": 8},
    "london": {"start": 8, "end": 16},
}

# Engulfing tolerance — relaxes strict body-wrap (sub-spread noise for Oil)
ENGULFING_TOLERANCE = 0.01  # $0.01 for Oil (0.01% of price)

# Alpha-Sweep for Oil (same logic, different thresholds)
ALPHA_SWEEP = {
    "asia_min_range": 0.50,       # $0.50 min range (vs $5 for gold)
    "sweep_threshold": 0.20,      # $0.20 extension (vs $2 for gold)
    "sl_buffer": 0.03,            # $0.03 buffer (vs $0.30 for gold)
    "min_sl": 0.10,               # $0.10 min SL (vs $5 for gold)
    "tp_multiplier": 2.0,
    "tp_structure_buffer": 0.13,  # Oil-scaled ($2 / 15.2x ratio)
    "be_trigger_pct": 0.50,       # Same
    "max_bars": 80,               # Same (~4 hours)
    "skip_first_bar": True,       # Same
    "engulfing_window_hours": 2,  # Same
    "scan_start": 8,
    "scan_end": 20,
    "max_trades_per_day": 3,
}

# Position Sizing
STRATEGY_RISK = {"alpha_sweep": 4.0}
RISK_PCT = 4.0
MAX_UNITS = 5000  # 5,000 barrels (5 lots)
YEARLY_CAPITAL = 5000.0

# Slippage Model — Deterministic (Filter #11, 2026-06-12). See backend/config.py.
def slippage(bar_range: float) -> float:
    return 0.04 + bar_range * 0.003

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
