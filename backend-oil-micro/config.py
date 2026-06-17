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

# Filter #28 — bias mode (per-system env override). Default = production (V1+V2).
# Set OIL_MICRO_BIAS_MODE=neutral on VPS .env to disable bias filter.
# Multi-seed 21yr BT: Oil Micro Δ = +$2.18M mean (range $2.15M-$2.21M, std $28.7k).
# See docs/FILTER_28_BIAS_DISABLE_RESEARCH.md.
# F28-H1: parse_bias_mode_env normalizes whitespace + case + warns on typos.
from backend.backtest.neutral_bias import parse_bias_mode_env
BIAS_MODE = parse_bias_mode_env("OIL_MICRO_BIAS_MODE", default="production")

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
    "be_trigger_pct": 0.35,         # Filter #5 shipped 2026-06-13: PF 2.69→3.10, +$115k 21yr, +7.2pp WR
    "partial_tp_at_pct": 0.5,       # Filter #7 shipped 2026-06-13 (Variant A): PF 3.10→5.76, +$1.05M 21yr (+49.5%)
    "partial_tp_size": 0.5,
    "partial_arms_be": False,       # Variant A — BE on original schedule
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 0.75,  # 45 min (same as Gold Micro)
    "max_trades_per_day": 3,
    "market_close_start": 21,
    "market_close_end": 22,
    # Filter #27 shipped 2026-06-16 (Oil Micro variant ttl15_C10_loose):
    # PF 5.76→7.56, +$534,162 21yr (+16.8%). Yearly slice 18/21 up, 6.8% loss/gain.
    # Place limit at signal.entry − 10% × risk (LONG; +10% × risk for SHORT),
    # 15min TTL, fill on any wick touch. See docs/FILTER_27_LIMIT_ORDER_RESEARCH.md.
    "entry_mode": "limit",
    "limit_offset_pct": -0.10,
    "limit_ttl_bars": 5,
    "limit_fill_strict": False,
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


# Slippage Model — Deterministic (Filter #11, 2026-06-12). See backend/config.py.
# Oil Micro uses different multipliers; preserves expected slippage = 0.03 + br*0.01 + 0.0025.
def slippage(bar_range: float) -> float:
    return 0.0325 + bar_range * 0.01


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
