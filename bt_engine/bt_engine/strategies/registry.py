"""Strategy registry — name → factory."""
from __future__ import annotations

from typing import Callable

from .base import Strategy


_REGISTRY: dict[str, Callable[..., Strategy]] = {}


def register(name: str, factory: Callable[..., Strategy]) -> None:
    if name in _REGISTRY:
        raise ValueError(f"Strategy already registered: {name}")
    _REGISTRY[name] = factory


def get(name: str, **kwargs) -> Strategy:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy: {name}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def list_strategies() -> list[str]:
    return sorted(_REGISTRY)


def _register_builtins() -> None:
    from .ema_cross.strategy import EmaCrossStrategy

    def _ema_factory(**kwargs) -> Strategy:
        return EmaCrossStrategy(**kwargs)

    register("ema_cross", _ema_factory)

    from .sdr001.strategy import SDR001Strategy, SDR002CleanStrategy

    def _sdr001_factory(**kwargs) -> Strategy:
        return SDR001Strategy(**kwargs)

    register("sdr001", _sdr001_factory)

    def _sdr002_clean_factory(**kwargs) -> Strategy:
        return SDR002CleanStrategy(**kwargs)

    register("sdr002_clean", _sdr002_clean_factory)

    # ----- Fib V2 ENSEMBLE (production XAU + EUR) -----
    from .fib_v2.config import FibV2Config
    from .fib_v2.strategy import (
        FibV2EnsembleStrategy,
        FibV2LongStrategy,
        FibV2ShortStrategy,
    )

    def _fib_v2_ensemble_factory(**kwargs) -> Strategy:
        return FibV2EnsembleStrategy(**kwargs)

    def _fib_v2_long_factory(**kwargs) -> Strategy:
        return FibV2LongStrategy(**kwargs)

    def _fib_v2_short_factory(**kwargs) -> Strategy:
        return FibV2ShortStrategy(**kwargs)

    register("fib_v2_xau_ensemble", _fib_v2_ensemble_factory)
    register("fib_v2_xau_long", _fib_v2_long_factory)
    register("fib_v2_xau_short", _fib_v2_short_factory)

    # ----- Partial-TP safety-net variants (Phase 7) -----
    def _make_ptp_factory(at_r: float):
        def _factory(**kwargs) -> Strategy:
            cfg = kwargs.pop("config", None) or FibV2Config()
            # Override partial-TP params on the config.
            from dataclasses import replace
            cfg = replace(cfg, partial_tp_at_r=at_r, partial_tp_pct=0.5)
            return FibV2EnsembleStrategy(config=cfg, **kwargs)
        return _factory

    register("fib_v2_xau_ensemble_ptp1r", _make_ptp_factory(1.0))
    register("fib_v2_xau_ensemble_ptp2r", _make_ptp_factory(2.0))

    # ----- Fib V2 INTRADAY A+D (production port — M15 base + pivots) -----
    from .fib_v2_intraday import FibV2IntradayA, FibV2IntradayD, FibV2IntradayAPlusD

    def _fib_v2_intraday_a_factory(**kwargs) -> Strategy:
        return FibV2IntradayA(**kwargs)

    def _fib_v2_intraday_d_factory(**kwargs) -> Strategy:
        return FibV2IntradayD(**kwargs)

    def _fib_v2_intraday_a_plus_d_factory(**kwargs) -> Strategy:
        return FibV2IntradayAPlusD(**kwargs)

    register("fib_v2_intraday_a", _fib_v2_intraday_a_factory)
    register("fib_v2_intraday_d", _fib_v2_intraday_d_factory)
    register("fib_v2_intraday_a_plus_d", _fib_v2_intraday_a_plus_d_factory)

    # ----- NO-STRICT variants (strict_after=False): bar-K entry eligible, fill still K+1.
    # Causally clean (see docs/NOSTRICT_A_D). Deploy target: run at <=2.5% risk only. -----
    def _fib_v2_intraday_a_nostrict_factory(**kwargs) -> Strategy:
        return FibV2IntradayA(strict_after=False, **kwargs)

    def _fib_v2_intraday_d_nostrict_factory(**kwargs) -> Strategy:
        return FibV2IntradayD(strict_after=False, **kwargs)

    def _fib_v2_intraday_a_plus_d_nostrict_factory(**kwargs) -> Strategy:
        return FibV2IntradayAPlusD(strict_after=False, **kwargs)

    register("fib_v2_intraday_a_nostrict", _fib_v2_intraday_a_nostrict_factory)
    register("fib_v2_intraday_d_nostrict", _fib_v2_intraday_d_nostrict_factory)
    register("fib_v2_intraday_a_plus_d_nostrict", _fib_v2_intraday_a_plus_d_nostrict_factory)

    # ----- EDGE variant (audited 2026-07-12): no partial-TP + cost_r<=0.12 filter.
    # The FIRST config to survive the full iron-clad audit (PF 1.20 physical, OOS>IS,
    # bootstrap p=0.0000, delay-robust, $5k->$56k 21yr no-wipe). See
    # docs/EDGE_AUDIT_IRONCLAD.md + [[real-edge-nopartial-costfilter]]. -----
    def _fib_v2_intraday_a_plus_d_edge_factory(**kwargs) -> Strategy:
        return FibV2IntradayAPlusD(edge=True, **kwargs)

    register("fib_v2_intraday_a_plus_d_edge", _fib_v2_intraday_a_plus_d_edge_factory)


_register_builtins()
