"""COBRAX — OTE sweep→BOS→FVG scalp, 3rd live leg (M5 XAU).

Streaming causal port of research/cobrax/cobrax.py. Build order (see
docs/COBRAX_3RD_LEG_PLAN.md): config → htf_bias → detectors → state → strategy.

Phase 1 (built): config, htf_bias, detectors.
Phase 1 (pending): state, strategy.
Phase 2 (pending): streaming↔research parity + BT=live 0-delta + known_at audit.
Phase 3 (pending): shared-account ownership (live.py) — NOT started (A+D regression surface).
"""
from __future__ import annotations

from .config import (
    COBRAX_LONG_LEG,
    COBRAX_SHORT_LEG,
    CobraxConfig,
    CobraxLegSpec,
    make_cobrax_config,
)
from .detectors import ConfirmedPivots, confirmed_pivots, detect_fvg, ote_ratio
from .htf_bias import HtfBiasTracker

__all__ = [
    "CobraxConfig",
    "CobraxLegSpec",
    "COBRAX_LONG_LEG",
    "COBRAX_SHORT_LEG",
    "make_cobrax_config",
    "HtfBiasTracker",
    "ConfirmedPivots",
    "confirmed_pivots",
    "detect_fvg",
    "ote_ratio",
]
