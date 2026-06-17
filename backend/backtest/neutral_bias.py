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
    """
    if bias_mode is None or bias_mode == "production":
        return "production"
    if bias_mode == "neutral":
        return "neutral"
    raise ValueError(
        f"Unknown bias_mode={bias_mode!r}. Valid: None, 'production', 'neutral'."
    )
