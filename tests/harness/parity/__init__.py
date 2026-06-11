"""Parity verification harness.

Compares LIVE signal-generation against BACKTEST signal-generation for the
same input bars. Surfaces drift bugs (5 confirmed in 3 weeks before this
harness existed). Per-system, per-day measurement, with a hybrid soft gate:

- Catastrophic drift   → pytest fails (CI blocks)
- Warning-level drift  → pytest passes with warning + JSON artifact
- Clean parity         → pytest passes silently

Public API:
    from tests.harness.parity import run_parity_check, SYSTEMS

See docs/PARITY_HARNESS_PLAN.md for the full design.
"""

from .config import SYSTEMS
from .extractor import SignalRecord
from .diff import SignalDiff, diff_signals
from .score import ParityScore
from .runner import run_parity_check

__all__ = [
    "SYSTEMS",
    "SignalRecord",
    "SignalDiff",
    "ParityScore",
    "diff_signals",
    "run_parity_check",
]
