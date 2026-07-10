"""CobraxConfig — frozen params for the COBRAX 3rd leg (OTE sweep→BOS→FVG scalp).

Every value is the validated research headline (see research/cobrax/cobrax.py::HEADLINE
+ SWEEP_REVIEW_2026-07-10.md). The streaming port MUST reproduce these bit-for-bit
against the research engine (Phase 2 parity gate) before any live deploy.

Causal contract (enforced by the strategy + detectors, mirrored from research):
  - swing pivots confirmed at pivot_idx + mss_lb (never center-rolling look-ahead).
  - sweep / BOS / FVG / OTE read CLOSED bars only, all strictly before the fill bar.
  - HTF bias indexed by M15 CLOSE time (no interior peek) — see htf_bias.py.
  - fill is a resting LIMIT at the FVG edge, touched on a bar AFTER the FVG bar.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CobraxConfig:
    """Frozen COBRAX config. Defaults = validated XAU M5 headline (rr3)."""

    # ── timeframes ──────────────────────────────────────────────
    base_tf: str = "M5"
    """Execution timeframe. Live leg drives M5 bars (needs EA M5 export — Phase 0)."""
    htf_tf_min: int = 15
    """HTF-bias timeframe in minutes (M15). Derived from the M5 stream internally."""

    # ── structure detection ─────────────────────────────────────
    mss_lb: int = 3
    """Swing pivot left=right lookback. Pivot confirmed at pivot_idx + mss_lb."""
    sweep_lb: int = 60
    """How many bars back the sweep scan looks for a swept swing extreme."""
    sweep_reject: bool = True
    """Require the sweep bar to CLOSE back across the level (rejection wick)."""

    # ── FVG + entry zone ────────────────────────────────────────
    fvg_min: float = 0.3
    """Minimum FVG size ($ for XAU). Below this the gap is noise."""
    fvg_wait: int = 40
    """Bars after MSS to scan for the FVG to form."""
    retrace_wait: int = 40
    """Bars after the FVG to wait for price to retrace into the entry level."""
    entry: str = "edge"
    """FVG entry level: 'edge' = proximal edge (research headline), 'ce' = mid."""
    ote_lo: float = 0.62
    ote_hi: float = 0.79
    """OTE band the entry level must sit inside (classic ICT OTE == Fib V2 zone)."""

    # ── stop / target ───────────────────────────────────────────
    sl: str = "sweep"
    """SL anchor: 'sweep' = past the swept extreme (research headline), 'fvg' = far edge."""
    tp_mode: str = "rr"
    """'rr' = fixed R multiple (headline rr3), 'nl' = next-liquidity swing extreme."""
    tp_r: float = 3.0
    """Target R for tp_mode='rr'. Sweep review: rr3 = +36% netR vs nl baseline."""

    # ── bias / direction / session ──────────────────────────────
    bias_align: bool = True
    """Only take trades whose direction agrees with the HTF bias."""
    direction: str = "both"
    """'both' | 'long' | 'short'."""
    session: str = "all"
    """Session filter. Headline = 'all' (24h)."""

    # ── holding / risk / cost ───────────────────────────────────
    max_hold_bars: int = 120
    """Timeout in M5 bars (120 = 10h). Mark-to-close if neither SL nor TP hit."""
    min_risk_units: float = 0.50
    """Reject broker-untradeable tiny stops (mirrors fib_v2_intraday floor)."""
    max_risk_pct: float = 0.02
    """Reject trades where risk_units > max_risk_pct * entry_price."""
    cost_usd: float = 0.2
    """Cost in $/risk_units used for net_r. 0.2 = research 'realistic ECN' (XAU).
    NOTE: live JustMarkets XAU is ~$0.65 — recalibrate before live (Phase 0/4).
    Parity (Phase 2) runs at THIS value so streaming↔research match exactly."""


@dataclass(frozen=True)
class CobraxLegSpec:
    """One COBRAX leg: direction + unique comment tag for shared-account ownership."""

    direction: str  # "long" | "short"
    leg_name: str  # unique, contains 'cobrax' so _leg_owns_position can claim it

    def __post_init__(self) -> None:
        if self.direction not in ("long", "short"):
            raise ValueError(f"direction must be 'long' or 'short', got {self.direction}")
        if "cobrax" not in self.leg_name:
            raise ValueError(
                f"leg_name must contain 'cobrax' for live ownership tagging, got {self.leg_name}"
            )


COBRAX_LONG_LEG = CobraxLegSpec(direction="long", leg_name="cobrax_long")
COBRAX_SHORT_LEG = CobraxLegSpec(direction="short", leg_name="cobrax_short")


def make_cobrax_config(**overrides) -> CobraxConfig:
    """Factory — headline defaults with optional overrides (tests / sweeps)."""
    return CobraxConfig(**overrides)
