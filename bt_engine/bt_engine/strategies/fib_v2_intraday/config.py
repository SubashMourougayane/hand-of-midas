"""FibV2IntradayConfig — frozen production config for intraday A+D port.

100TH-TIME AUDIT CHECKLIST (verified per file):
  1. NO center-rolling pivots — uses PivotTracker idx+lb confirmation (inherited).
  2. D1 features shift(1)-lagged — RegimeTracker handles (inherited, but regime='any' so gate is OFF).
  3. Phantom-fill prevention — _finalize_entry uses next bar.open as entry price (inherited).
  4. Bar-close timing — on_bar receives just-closed bar; pivot fed directly, no re-derive.
  5. Multi-pivot stacking — DEDUP via consumed_entry_keys on (entry_ts, side, leg_name).
  6. Min risk floor — min_risk_units rejects tiny stops before order construction.
  7. Session in NY hour only from bar.timestamp (inherited via _ny_hour).
  8. Cost double-count — cost_r computed ONCE in _finalize_entry, engine reads from extra (inherited).
  9. Same-direction concurrent same-bar — blocked by dedup. Opposite-dir A+D allowed.
 10. Risk-pct cap — max_risk_pct kept at 0.02 (inherited).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..fib_v2.config import FibV2Config, LegSpec


@dataclass(frozen=True)
class FibV2IntradayConfig:
    """Wraps FibV2Config + adds intraday-specific knobs.

    NOTE: composition (not inheritance). FibV2Config is frozen and
    field-default-ordering with subclassing is fragile. Compose to keep
    the audit surface explicit.
    """

    base: FibV2Config = field(default_factory=FibV2Config)
    base_tf: str = "M15"
    pivot_tf: str = "M15"
    min_risk_units: float = 0.50  # $0.50 stop floor on XAU (broker un-tradeable below)
    strict_after: bool = True
    """Research-parity gate (searchsorted side='right'): block entry ON the setup-confirm
    bar (bar K); only allow from K+1. True = certified baseline behavior. False = 'no-strict'
    (bar K is a valid entry-scan bar too; fill still K+1 open, causally clean). NOT a
    causality requirement — it is a research bit-for-bit choice. See docs/NOSTRICT_A_D_*.md."""

    def __post_init__(self) -> None:
        if self.base_tf != self.pivot_tf:
            raise ValueError(
                f"FibV2IntradayConfig requires base_tf == pivot_tf, got "
                f"base={self.base_tf} pivot={self.pivot_tf}. "
                "Mixed-TF requires aggregation path not implemented in this port."
            )
        if self.min_risk_units < 0:
            raise ValueError(f"min_risk_units must be >= 0, got {self.min_risk_units}")


# -----------------------------------------------------------------------------
# Leg specs — regime='any' for both legs (production validated)
# -----------------------------------------------------------------------------

INTRADAY_A_LEG = LegSpec(
    direction="long",
    regime="any",
    leg_name="intraday_a_long",
)

INTRADAY_D_LEG = LegSpec(
    direction="short",
    regime="any",
    leg_name="intraday_d_short",
)


# -----------------------------------------------------------------------------
# Factory builders — production-locked params
# -----------------------------------------------------------------------------

# EDGE variant (audited 2026-07-12): drop the partial-TP (it capped the fat tail
# AND was the over-count bug) + cost-robustness filter (skip trades where the $0.65
# cost is > 12% of the stop). See docs/EDGE_AUDIT_IRONCLAD.md +
# [[real-edge-nopartial-costfilter]]. PF 1.20 physical, OOS>IS, bootstrap p=0.0000.
_EDGE_PARTIAL = None      # no partial (baseline was 1.0)
_EDGE_MAX_COST_R = 0.12   # skip if cost_usd/risk_units > this


def make_intraday_a_config(*, strict_after: bool = True, edge: bool = False,
                           ote: float | None = None) -> FibV2IntradayConfig:
    """A leg: LONG  · lb=3 · hold=12h · session=london_ny · ext=2.618 · cost=$0.65.
    edge=True → no partial + cost_r<=0.12 filter (audited).
    ote=0.62 → ICT-OTE deep-zone entry gate (research variant)."""
    base = FibV2Config(
        pivot_lb=3,
        max_hold_h=12,
        session="london_ny",
        ext_target_pct=2.618,
        sl_buffer_pct=0.02,
        partial_tp_at_r=_EDGE_PARTIAL if edge else 1.0,
        partial_tp_pct=0.5,
        cost_usd=0.65,  # JustMarkets Raw Spread realistic
        max_cost_r=_EDGE_MAX_COST_R if edge else None,
        ote_shallow_pct=ote,
    )
    return FibV2IntradayConfig(
        strict_after=strict_after,
        base=base, base_tf="M15", pivot_tf="M15", min_risk_units=0.50,
    )


def make_intraday_d_config(*, strict_after: bool = True, edge: bool = False,
                           ote: float | None = None) -> FibV2IntradayConfig:
    """D leg: SHORT · lb=3 · hold=24h · session=all       · ext=2.618 · cost=$0.65.
    edge=True → no partial + cost_r<=0.12 filter (audited).
    ote=0.62 → ICT-OTE deep-zone entry gate (research variant)."""
    base = FibV2Config(
        pivot_lb=3,
        max_hold_h=24,
        session="all",
        ext_target_pct=2.618,
        sl_buffer_pct=0.02,
        partial_tp_at_r=_EDGE_PARTIAL if edge else 1.0,
        partial_tp_pct=0.5,
        cost_usd=0.65,
        max_cost_r=_EDGE_MAX_COST_R if edge else None,
        ote_shallow_pct=ote,
    )
    return FibV2IntradayConfig(
        strict_after=strict_after,
        base=base, base_tf="M15", pivot_tf="M15", min_risk_units=0.50,
    )
