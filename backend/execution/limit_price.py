"""Filter #27 — single source of truth for limit-order entry price computation.

Used by:
- BT engines (`backend/backtest/engine.py`, `backend-{micro,oil,oil-micro}/backtest/engine.py`)
  via `from backend.execution.limit_price import compute_limit_price`
- Live scheduler / engine (`backend/scanner/live_engine.py`, `backend-{micro,oil,oil-micro}/...`)
  via the same import

The two callers must produce identical limit_price for identical inputs, otherwise
the live↔BT parity drift class returns. See [[project-live-backtest-parity-gap]] for
the full list of past parity bugs and `tests/test_limit_price.py` for the
unit-test guarantee.

Variant rules (locked-in 2026-06-16 from Filter #27 sweep):
- A (offset = 0.0)       : limit at signal.entry verbatim. signal.entry already
                            includes the BT's baseline slippage estimate, so this
                            is the "what we thought we'd get" price.
- B ("engulf_close")     : limit at the engulfing M3 bar's ask_close (LONG) or
                            bid_close (SHORT). No slippage offset baked in — the
                            purer level. Best variant for Oil Macro.
- C (offset < 0)         : pullback into structure by offset × risk. -0.10 / -0.20
                            / -0.30 sweeps a 10/20/30% pullback. C10_loose is the
                            best variant for Gold Macro / Gold Micro / Oil Micro.
                            Sign convention: offset is negative for LONG ("below
                            entry"), inverted for SHORT.
"""
from __future__ import annotations
from typing import Union


def compute_limit_price(
    direction: str,
    signal_entry: float,
    signal_risk: float,
    engulf_close_ask: float,
    engulf_close_bid: float,
    limit_offset_pct: Union[float, str],
) -> float:
    """Return the limit-order entry price for a Filter #27 signal.

    Args:
        direction: "long" or "short". Anything else raises ValueError.
        signal_entry: strategy's calc-entry (engulfing close + slippage estimate
            on the bid/ask side that matches direction). Used by variant A and
            as the anchor for variant C.
        signal_risk: strategy's risk distance in instrument price units. Used
            by variant C as the pullback scale.
        engulf_close_ask: bid-close of the engulfing M3 bar — wait, ask_close
            for LONG variant B. Read directly from df at bar_idx in BT, or
            from get_current_price() in live.
        engulf_close_bid: bid_close of the engulfing M3 bar. Used by variant B
            for SHORT.
        limit_offset_pct: 0.0 (A), "engulf_close" (B), or a negative float
            (C; -0.10 / -0.20 / -0.30 are the swept variants).

    Returns:
        The limit price as a float in instrument units.

    Raises:
        ValueError: on unknown direction or unknown limit_offset_pct.

    See backend/backtest/engine.py:272-292 (and siblings) for the historical
    inline implementation that this helper replaces. Behaviour is byte-identical
    to that inline code.
    """
    if direction not in ("long", "short"):
        raise ValueError(f"unknown direction: {direction!r}")

    # Variant B — engulfing close, no slippage offset
    if limit_offset_pct == "engulf_close":
        return engulf_close_ask if direction == "long" else engulf_close_bid

    # Variant A — calc entry verbatim
    if limit_offset_pct == 0.0:
        return signal_entry

    # Variant C — pullback into structure by offset × risk.
    # offset_pct is negative for the swept variants (-0.10/-0.20/-0.30).
    # LONG: limit BELOW entry by offset×risk, so add a negative.
    # SHORT: limit ABOVE entry by |offset|×risk, so subtract a negative.
    # The sign-flip on SHORT is intentional and matches the BT engine inline code.
    if isinstance(limit_offset_pct, (int, float)):
        if direction == "long":
            return signal_entry + limit_offset_pct * signal_risk
        else:
            return signal_entry - limit_offset_pct * signal_risk

    raise ValueError(
        f"unknown limit_offset_pct: {limit_offset_pct!r} "
        f"(expected 0.0, 'engulf_close', or a negative float)"
    )
