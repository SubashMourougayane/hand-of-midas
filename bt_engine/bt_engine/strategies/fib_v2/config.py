"""FibV2Config — frozen params for the production Fib V2 ENSEMBLE.

Winning numbers locked from research session 2026-06-30. See plan/tracker.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FibV2Config:
    """Frozen Fib V2 ENSEMBLE config. Default values = production winner."""

    pivot_lb: int = 5
    """H1 pivot left=right=lb. Confirmation lands at bar pivot_idx + lb."""

    max_hold_h: int = 72
    """Setup-scan horizon in hours. max_hold_bars = max_hold_h * 12 (M5 bars/h)."""

    session: str = "all"
    """Session filter: 'all' | 'london' | 'ny' | 'overlap' | 'london_ny'."""

    ext_target_pct: float = 1.618
    """TP = H + ext * diff (long) / L - ext * diff (short). diff = H - L."""

    sl_buffer_pct: float = 0.02
    """SL = L - sl_buf * diff (long) / H + sl_buf * diff (short)."""

    swing_lb: int = 20
    """M5 swing low/high lookback (raw_features only; not in entry rule)."""

    d1_ema_fast: int = 50
    d1_ema_slow: int = 200
    atr_period: int = 14
    """D1 EMA periods + ATR period for regime tracker."""

    max_risk_pct: float = 0.02
    """Reject trades where risk > max_risk_pct * entry_price."""

    cost_usd: float = 0.30
    """Cost in $/risk_units. XAU=$0.30; EUR=$0.00003; BRENT=$0.05."""

    qty: float = 1.0
    """Default order qty (lots). Overridden by live position sizing."""

    sideways_band_pct: float = 0.03
    """For 'sideways' regime variant — |d1_close - ema200|/ema200 < this."""

    partial_tp_at_r: float | None = None
    """If set, close partial_tp_pct of position once MFE reaches +N R, then move SL to BE.
    Research winners: 1.0 (PTP+1R) or 2.0 (PTP+2R). None = baseline (no partial)."""

    partial_tp_pct: float = 0.5
    """Fraction of position to close at partial-TP trigger. Default 0.5 (research baseline)."""


@dataclass(frozen=True)
class LegSpec:
    """One leg of the ensemble: direction + regime gate + label."""

    direction: str  # "long" | "short"
    regime: str  # "bull_strong" | "bear_strong" | "bull" | "bear" | "sideways" | "any"
    leg_name: str  # e.g. "long_bull_strong"

    def __post_init__(self) -> None:
        if self.direction not in ("long", "short"):
            raise ValueError(f"direction must be 'long' or 'short', got {self.direction}")
        valid_regimes = {"bull_strong", "bear_strong", "bull", "bear", "sideways", "any"}
        if self.regime not in valid_regimes:
            raise ValueError(f"regime must be one of {valid_regimes}, got {self.regime}")


LONG_BULL_STRONG = LegSpec(direction="long", regime="bull_strong", leg_name="long_bull_strong")
SHORT_BEAR_STRONG = LegSpec(direction="short", regime="bear_strong", leg_name="short_bear_strong")


# Cost defaults per asset family — used to override config.cost_usd from CLI.
COST_USD_DEFAULTS: dict[str, float] = {
    "XAUUSD": 0.30,
    "XAUUSD.ecn": 0.30,
    "EURUSD": 0.00003,
    "EURUSD.ecn": 0.00003,
    "EUR_USD": 0.00003,
    "BCO_USD": 0.05,
    "BRENT.ecn": 0.05,
    "GBP_USD": 0.00005,
}
