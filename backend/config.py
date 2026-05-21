import os

OANDA_TOKEN = os.getenv("OANDA_TOKEN", "bc0ccfb02462f673c14378350f0367c8-9f4a07ef3b2f62f480465643ee8d3ca4")
OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT", "101-004-39331014-001")
OANDA_URL = os.getenv("OANDA_URL", "https://api-fxpractice.oanda.com/v3")
INSTRUMENT = "XAU_USD"

DB_URL = os.getenv("DATABASE_URL", "postgresql://subash@localhost:5432/golddigger")

SESSIONS_UTC = {
    "asia": {"start": 0, "end": 8},
    "london": {"start": 8, "end": 16},
    "new_york": {"start": 13, "end": 21},
}

# Alpha-Sweep (V4)
ALPHA_SWEEP = {
    "asia_min_range": 5.0,
    "sweep_threshold": 2.0,
    "sl_buffer": 0.30,
    "min_sl": 5.0,
    "tp_multiplier": 2.0,
    "be_trigger_pct": 0.50,
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 2,
}

# Mean-Rev (V7)
MEAN_REV = {
    "condition1_threshold": -0.4,
    "condition2_threshold": -0.8,
    "sl_range_multiplier": 1.0,
    "max_hold_days": 5,
    "ma_period": 10,
}

# Cross-Market (V8)
CROSS_MARKET = {
    "instruments": ["EUR_USD", "USB10Y_USD", "SPX500_USD", "XAG_USD", "BCO_USD", "USB02Y_USD"],
    "weights": {"eur": 2, "us10y": 3, "spx": 1, "silver": 2, "oil": 1, "us2y": 2},
    "threshold": 0.005,
    "consensus_min": 0.3,
    "sl_atr_mult": 2.0,
    "tp_atr_mult": 4.0,
    "max_hold_days": 20,
    "min_bar_gap": 2,
    "atr_period": 14,
}

# DD Protection
DD_PROTECTION = {
    "ma_filter_period": 50,
    "consecutive_loss_halve": 3,
    "consecutive_loss_pause": 5,
    "pause_signals": 2,
    "equity_ma_period": 20,
}

# Position Sizing
RISK_PCT = 3.0
MAX_UNITS = 100
YEARLY_CAPITAL = 5000.0

# Slippage Model
def slippage(bar_range: float) -> float:
    import numpy as np
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
