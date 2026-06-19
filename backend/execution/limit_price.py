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
import logging
import os
from typing import Optional, Union

_log = logging.getLogger(__name__)


# H1 (2026-06-17) — robust LIMIT_DRY_RUN parsing.
# Old code: `os.environ.get("LIMIT_DRY_RUN", "true").lower() == "true"`. That
# silently flipped `LIMIT_DRY_RUN=true ` (trailing space) to dry_run=False
# (REAL LIMIT, opposite of intent), and silently treated unknown values like
# `'fasle'` (typo) or `'0'`/`'no'`/`'off'` as REAL LIMIT.
# New behavior:
# - .strip() before .lower() → whitespace tolerant
# - Recognised TRUE set: {"1","true","yes","on"}
# - Recognised FALSE set: {"0","false","no","off"}
# - Unknown values default to TRUE (safe — keeps dry-run on) AND log a warning
#   so ops can spot the typo.

_DRY_RUN_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DRY_RUN_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def parse_dry_run_env(
    env_var: str = "LIMIT_DRY_RUN",
    *,
    default: bool = True,
    system_prefix: Optional[str] = None,
) -> bool:
    """Parse a boolean env var with whitespace tolerance + warn-on-unknown.

    Args:
        env_var: env var name. Defaults to "LIMIT_DRY_RUN".
        default: returned when the env var is unset OR has an unrecognised value.
            Defaults to True (safe — keeps dry-run on).
        system_prefix: optional per-system override prefix, e.g. "OIL". When
            set, the function first checks `{system_prefix}_LIMIT_DRY_RUN`
            and falls back to the global `LIMIT_DRY_RUN` if that's unset.
            (M7 — per-system rollback support.)

    Returns:
        Resolved boolean. Unrecognised values default to `default` AND log a
        WARNING via `logging` so ops can spot typos without ambiguity.

    Examples (with default=True):
        parse_dry_run_env()                       # env unset → True
        os.environ["LIMIT_DRY_RUN"] = "false"     # → False
        os.environ["LIMIT_DRY_RUN"] = "false "    # trailing space → False (FIXED)
        os.environ["LIMIT_DRY_RUN"] = "true "     # trailing space → True (FIXED)
        os.environ["LIMIT_DRY_RUN"] = "fasle"     # typo → True + WARN
        os.environ["LIMIT_DRY_RUN"] = "FALSE"     # case-insensitive → False
        os.environ["LIMIT_DRY_RUN"] = "0"         # → False
        os.environ["LIMIT_DRY_RUN"] = "yes"       # → True
    """
    # M7 hook: per-system override wins, else fall back to global.
    raw = None
    source = env_var
    if system_prefix:
        per_sys_var = f"{system_prefix}_{env_var}"
        raw = os.environ.get(per_sys_var)
        if raw is not None:
            source = per_sys_var
    if raw is None:
        raw = os.environ.get(env_var)
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if cleaned in _DRY_RUN_TRUE_VALUES:
        return True
    if cleaned in _DRY_RUN_FALSE_VALUES:
        return False
    # Unknown value: warn loudly, return safe default.
    _log.warning(
        "limit_dry_run_unrecognised_value: %s=%r (cleaned=%r) "
        "not in TRUE=%s or FALSE=%s — defaulting to %s",
        source, raw, cleaned,
        sorted(_DRY_RUN_TRUE_VALUES),
        sorted(_DRY_RUN_FALSE_VALUES),
        default,
    )
    return default


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

    # Compute the candidate price per variant, then sanity-check before return.
    if limit_offset_pct == "engulf_close":
        # Variant B — engulfing close, no slippage offset
        candidate = engulf_close_ask if direction == "long" else engulf_close_bid
    elif limit_offset_pct == 0.0:
        # Variant A — calc entry verbatim
        candidate = signal_entry
    elif isinstance(limit_offset_pct, (int, float)):
        # Variant C — pullback into structure by offset × risk.
        # offset_pct is negative for the swept variants (-0.10/-0.20/-0.30).
        # LONG: limit BELOW entry by offset×risk, so add a negative.
        # SHORT: limit ABOVE entry by |offset|×risk, so subtract a negative.
        # The sign-flip on SHORT is intentional and matches the BT engine inline code.
        if direction == "long":
            candidate = signal_entry + limit_offset_pct * signal_risk
        else:
            candidate = signal_entry - limit_offset_pct * signal_risk
    else:
        raise ValueError(
            f"unknown limit_offset_pct: {limit_offset_pct!r} "
            f"(expected 0.0, 'engulf_close', or a negative float)"
        )

    # M1 (2026-06-17): refuse to return non-positive prices. Math guarantees
    # this for current shipped variants (offset in [-0.30, 0]) on real-world
    # entries (XAU $4000+, BCO $80+, FX 1.X+). But a future variant sweep
    # with offset=-1.5 OR an FX pair with very small entry × large risk could
    # produce <=0. Broker would reject; raise here so caller catches at the
    # source (live_engine catches via existing compute_limit_price_failed
    # log path) instead of a confusing 10015 broker reject downstream.
    # See docs/FILTER_27_AUDIT_BACKLOG.md M1.
    if candidate <= 0:
        raise ValueError(
            f"compute_limit_price returned non-positive {candidate} "
            f"(direction={direction}, signal_entry={signal_entry}, "
            f"signal_risk={signal_risk}, offset_pct={limit_offset_pct!r}). "
            f"Broker would reject. Refusing to return junk price."
        )
    # Coerce to native float — numpy 2.x's np.float64 repr is "np.float64(X)"
    # which broke a live LIMIT INSERT on 2026-06-19 when psycopg2 fell back
    # to str() (no adapter). DB now has a global adapter (backend/db.py)
    # but defending here too: callers downstream may format/serialize/log,
    # and native float keeps everything portable.
    return float(candidate)
