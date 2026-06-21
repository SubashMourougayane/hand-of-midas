"""Labs data gateway.

Thin wrapper around R&D/data_split.py. Labs strategies call get_brent()
and get nothing but the development window (or whatever the gateway has
unlocked). No raw CSV access. No live API. No imports from production.

Why thin wrap instead of direct import:
- Labs and R&D have different cadence. R&D is paranoid (Phase 0 → Phase 1
  → ... with discipline gates). Labs is research-grade — strategies come
  and go quickly.
- A separate wrapper means Labs can add caching / batch helpers without
  polluting R&D's gateway.
- Both still funnel through the same hash-locked split file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# R&D gateway is the single source of truth for which dates are visible.
_RND_PATH = Path(__file__).resolve().parent.parent.parent / "R&D"
sys.path.insert(0, str(_RND_PATH))

from data_split import Phase, get_data  # noqa: E402


def get_brent(phase: Phase = Phase.DEVELOPMENT) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (D1, H1, M3) DataFrames for BCO_USD in the given phase.

    Default is DEVELOPMENT. VALIDATION and HOLDOUT remain locked unless
    the R&D gate file unlocks them.
    """
    return get_data(phase, "BCO_USD")


def get_xauusd(phase: Phase = Phase.DEVELOPMENT) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Same gateway, different instrument. For when a Labs strategy needs
    a control or cross-asset reference. Use sparingly."""
    return get_data(phase, "XAU_USD")
