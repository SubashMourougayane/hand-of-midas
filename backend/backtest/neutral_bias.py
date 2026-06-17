"""Filter #28 — NeutralBiasDict.

A dict-like that returns "neutral" for every key lookup. Used by
run_backtest(bias_mode="neutral") to disable the bias filter without
touching strategy code.

Extracted to its own module so all 4 engines (and the research script)
share one definition — no copy-paste drift.

Path A research result (2026-06-18, single-seed 21yr):
    Cumulative ΔP&L (NEUTRAL minus WITH-BIAS): +$3.58M
    Yearly W/L per system: 21W/0L for ALL 4 systems (84/84)
See `scripts/output/filter_28_path_a_21yr_console.txt` for the full table.

Path B status: this module is the production path for Path B — wired
into each engine's run_backtest as `bias_mode` kwarg, default None
(no behavior change for existing callers).
"""

from __future__ import annotations


class NeutralBiasDict(dict):
    """Returns "neutral" for any key lookup. Mutations are silently ignored
    (the engine's bias-computation loop does `daily_bias[d] = "..."` — we
    must NOT let those writes succeed, otherwise neutrality breaks).

    Usage:
        from backend.backtest.neutral_bias import NeutralBiasDict
        daily_bias = NeutralBiasDict()  # every .get() returns "neutral"
    """

    def get(self, key, default=None):
        return "neutral"

    def __getitem__(self, key):
        return "neutral"

    def __setitem__(self, key, value):
        # Silently ignore writes — preserves neutrality even if engine
        # code attempts to populate the dict.
        pass

    def update(self, *args, **kwargs):
        # Same — preserve neutrality regardless of what callers try to write.
        pass

    def __contains__(self, key):
        # All dates are "in" the neutral dict.
        return True


def resolve_bias_mode(bias_mode: str | None) -> str:
    """Normalize the bias_mode kwarg. Returns 'neutral' or 'production'.

    Accepted inputs:
      None        → 'production' (default — compute daily_bias normally)
      'production' → 'production' (explicit)
      'neutral'    → 'neutral' (use NeutralBiasDict)

    Raises ValueError for any other string so a typo doesn't silently
    fall through to production behavior.

    NOTE: this is the BT-kwarg path. RAISES on typos because BT call sites
    are explicit code, not env vars. For env-var resolution see
    `parse_bias_mode_env()` below — that path warns + falls back instead
    of raising, since service startup must not crash on a misspelled .env.
    """
    if bias_mode is None or bias_mode == "production":
        return "production"
    if bias_mode == "neutral":
        return "neutral"
    raise ValueError(
        f"Unknown bias_mode={bias_mode!r}. Valid: None, 'production', 'neutral'."
    )


# F28-H1 (2026-06-18): env-var parsing path.
#
# Background: F28 Phase 3 wired BIAS_MODE = os.getenv("X_BIAS_MODE", "production")
# in 4 configs. Audit found this is whitespace/case-fragile — `"neutral "`
# (trailing space, copy-paste hazard) silently falls through to "production"
# because string equality is exact. Same regression as LIMIT_DRY_RUN H1
# from F27 audit. This helper fixes it.
#
# Why fail-open (warn + default) instead of fail-closed (raise)?
# Service startup must not crash on a misspelled .env line. The default is
# "production" which is the safe state — if user types `GOLD_MACRO_BIAS_MODE=NEUTRAL`
# (uppercase) and we normalized it, that's fine; if they type `neutrol` (typo),
# we warn loudly to logs but keep the safe default.

_VALID_BIAS_MODE_VALUES = frozenset({"production", "neutral"})


def parse_bias_mode_env(env_var_name: str, default: str = "production") -> str:
    """Read an env var holding a bias-mode string and normalize it.

    Whitespace is stripped, case is lowered, then matched against the
    accepted set. Unrecognized values (typos) trigger a warning and fall
    back to `default`. Empty string is treated as "use default" too.

    Returns either "production" or "neutral" — guaranteed by the
    accepted-values gate. Never raises.

    Args:
      env_var_name: e.g., "GOLD_MACRO_BIAS_MODE"
      default:     fallback when env unset/blank/unrecognized — must be
                   one of the valid values; otherwise function-author bug.

    Logging:
      Uses module-level `import logging` so the warning lands wherever the
      service's logging is configured. (This module is imported at config
      time, before `_log` from scanner is available, so we avoid that.)
    """
    import os
    import logging

    if default not in _VALID_BIAS_MODE_VALUES:
        # Guard against caller bug — refuse to load with invalid default
        raise ValueError(
            f"parse_bias_mode_env(default={default!r}) — caller bug: "
            f"default must be one of {sorted(_VALID_BIAS_MODE_VALUES)}"
        )

    raw = os.getenv(env_var_name)
    if raw is None or raw.strip() == "":
        return default

    cleaned = raw.strip().lower()
    if cleaned in _VALID_BIAS_MODE_VALUES:
        return cleaned

    # Typo — log loudly + fall back. Operator might miss this in a busy
    # log, but at least it's there. Better than a silent flip.
    logging.warning(
        "F28-H1 parse_bias_mode_env: %s=%r is not one of %s. "
        "Falling back to %r. Check your .env for typos / extra whitespace.",
        env_var_name, raw, sorted(_VALID_BIAS_MODE_VALUES), default,
    )
    return default
