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

# Filter #28 — bias mode for live scanner.
#   "production" (default): use the V1+V2 daily candle bias (current behavior)
#   "neutral":              force every day to "neutral" (bias filter goes silent)
# Override via env var GOLD_MACRO_BIAS_MODE for production-without-redeploy flips.
# See docs/FILTER_28_BIAS_DISABLE_RESEARCH.md.
# Multi-seed 21yr BT: Gold Macro Δ = +$233.2k mean (range $233.0k-$233.3k, std $117).
# F28-H1: parse_bias_mode_env normalizes whitespace + case + warns on typos
# (vs raw os.getenv which silently flips "neutral " → production).
from backend.backtest.neutral_bias import parse_bias_mode_env
BIAS_MODE = parse_bias_mode_env("GOLD_MACRO_BIAS_MODE", default="production")

# Alpha-Sweep (V4)
ALPHA_SWEEP = {
    "asia_min_range": 5.0,
    "sweep_threshold": 2.0,
    "sl_buffer": 2.0,
    "min_sl": 5.0,
    "tp_multiplier": 2.0,
    "tp_structure_buffer": 2.0,
    "be_trigger_pct": 0.50,
    "partial_tp_at_pct": 0.5,    # Filter #7 shipped 2026-06-13 (Variant A): PF 2.56→3.53, +$81k 21yr (+23.5%)
    "partial_tp_size": 0.5,      # bank 50% of position at halfway, runner takes full TP/SL
    "partial_arms_be": False,    # Variant A — BE on original schedule, not on partial fire
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

# Slippage Model — Deterministic (Filter #11, 2026-06-12).
# Was: 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)
# The unseeded uniform(0, 0.02) made backtest run-to-run non-deterministic
# (~0.07pp parity_pct noise; meaningful when comparing PF deltas across
# filter ships). Replace random term with its expected value (0.01) so the
# mean slippage distribution is preserved and runs are reproducible.
def slippage(bar_range: float) -> float:
    return 0.04 + bar_range * 0.003

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
