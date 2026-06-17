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

# Filter #28 — bias mode (per-system env override). Default = production (V1+V2).
# Set OIL_MACRO_BIAS_MODE=neutral on VPS .env to disable bias filter.
# Multi-seed 21yr BT: Oil Macro Δ = +$1.01M mean (range $996.5k-$1.02M, std $9.0k).
# See docs/FILTER_28_BIAS_DISABLE_RESEARCH.md.
# F28-H1: parse_bias_mode_env normalizes whitespace + case + warns on typos.
from backend.backtest.neutral_bias import parse_bias_mode_env
BIAS_MODE = parse_bias_mode_env("OIL_MACRO_BIAS_MODE", default="production")

# Alpha-Sweep for Oil (same logic, different thresholds)
ALPHA_SWEEP = {
    "asia_min_range": 0.50,       # $0.50 min range (vs $5 for gold)
    "sweep_threshold": 0.20,      # $0.20 extension (vs $2 for gold)
    "sl_buffer": 0.03,            # $0.03 buffer (vs $0.30 for gold)
    "min_sl": 0.10,               # $0.10 min SL (vs $5 for gold)
    "tp_multiplier": 2.0,
    "tp_structure_buffer": 0.13,  # Oil-scaled ($2 / 15.2x ratio)
    "be_trigger_pct": 0.35,       # Filter #5 shipped 2026-06-13: PF 2.66→2.94, +$52k 21yr, +6.2pp WR
    "trail_after_be_pct": 0.50,   # Filter #6 shipped 2026-06-13 (Oil Macro only): +$80k 21yr, +11.5% P&L
    "partial_tp_at_pct": 0.5,     # Filter #7 shipped 2026-06-13 (Variant A): PF 2.96→4.70, +$45k 21yr (+5.8%)
    "partial_tp_size": 0.5,
    "partial_arms_be": False,     # Variant A — BE on original schedule
    "max_bars": 80,               # Same (~4 hours)
    "skip_first_bar": True,       # Same
    "engulfing_window_hours": 2,  # Same
    "scan_start": 8,
    "scan_end": 20,
    "max_trades_per_day": 3,
    # Filter #27 shipped 2026-06-16 (Oil Macro variant ttl15_B_loose):
    # PF 4.70→5.43, +$180,178 21yr (+21.8%). Yearly slice 18/21 up, 2.2% loss/gain.
    # Place limit at engulfing-close (no slippage offset baked in), 15min TTL,
    # fill on any wick touch. See docs/FILTER_27_LIMIT_ORDER_RESEARCH.md.
    "entry_mode": "limit",
    "limit_offset_pct": "engulf_close",
    "limit_ttl_bars": 5,            # 15 min on M3
    "limit_fill_strict": False,
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
