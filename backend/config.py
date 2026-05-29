import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Executor selection: "oanda" or "mt5"
EXECUTOR = os.getenv("EXECUTOR", "oanda")

OANDA_TOKEN = os.getenv("OANDA_TOKEN", "")
OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT", "")
OANDA_URL = os.getenv("OANDA_URL", "https://api-fxpractice.oanda.com/v3")
INSTRUMENT = "XAU_USD"

DB_URL = os.getenv("DATABASE_URL", "postgresql://subash@localhost:5432/golddigger")

SESSIONS_UTC = {
    "asia": {"start": 0, "end": 8},
    "london": {"start": 8, "end": 16},
    "new_york": {"start": 13, "end": 21},
}

# Engulfing tolerance — relaxes strict body-wrap by this amount (sub-spread noise)
ENGULFING_TOLERANCE = 0.10  # $0.10 for Gold (0.002% of price)

# Alpha-Sweep (V4)
ALPHA_SWEEP = {
    "asia_min_range": 5.0,
    "sweep_threshold": 2.0,
    "sl_buffer": 2.0,
    "min_sl": 5.0,
    "tp_multiplier": 2.0,
    "be_trigger_pct": 0.50,
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 0.75,  # 45 min (optimal: PF 3.34 vs 3.07 at 2hr)
    "scan_start": 8,
    "scan_end": 20,
    "max_trades_per_day": 3,
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

# Position Sizing — Tiered by strategy (reward strength, dampen weakness)
STRATEGY_RISK = {
    "alpha_sweep": 4.0,   # Best edge (PF 6.09, 73% WR) — reward it
    "mean_rev": 3.0,      # Solid — keep as-is
    "cross_market": 2.0,  # Most frequent, weakest per-trade, biggest DD contributor
}
RISK_PCT = 3.0  # fallback if strategy not in map
MAX_UNITS = 100
YEARLY_CAPITAL = 5000.0

# Slippage Model
def slippage(bar_range: float) -> float:
    import numpy as np
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
