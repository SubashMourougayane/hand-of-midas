"""Sealed data access for the R&D lab.

This is the ONLY way R&D code reads the JustMarkets price data. Direct
`pd.read_csv("data/raw/...")` from anywhere in `R&D/` is a contract
violation.

The lab's data split is hash-locked in this file. Any change to the
split boundaries changes the hash, which is logged and visible to the
user.

Usage:
    from R&D.data_split import get_data, Phase

    h1, m3 = get_data(Phase.DEVELOPMENT, instrument="BCO_USD")
    # h1 and m3 are pandas DataFrames with UTC timestamps as index, both
    # already filtered to dates in the development window.

If you call get_data(Phase.VALIDATION) before Phase 1 is signed off,
the call raises PhaseLockedError. Same for HOLDOUT before Phase 2.

Every call appends a JSON line to data_access_log.jsonl with timestamp,
phase, caller, and result row count. Audit trail for the user.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import pandas as pd


# ── Locked split boundaries (DO NOT EDIT WITHOUT EXPLICIT USER SIGN-OFF) ──

DEV_START = "2019-09-26"   # First clean M3 cadence row in JM data
DEV_END   = "2023-12-31"
VAL_START = "2024-01-01"
VAL_END   = "2024-12-31"
HOLD_START = "2025-01-01"
HOLD_END   = "2026-06-19"   # Last data day in current snapshot

# Hash of these boundaries. If anyone edits the dates above, this hash
# will no longer match what get_data() recomputes, and the user can spot
# the tampering.
SPLIT_BOUNDARIES_HASH = hashlib.sha256(
    f"{DEV_START}|{DEV_END}|{VAL_START}|{VAL_END}|{HOLD_START}|{HOLD_END}".encode()
).hexdigest()

# As of 2026-06-20 lab construction, the expected hash. If get_data() ever
# computes a different hash, that's evidence of tampering.
EXPECTED_HASH = "ecee833f4f3ac9f6f078927c28640617acbdccf8276b37bf900429ef0a55ac08"


# ── Phase gate state ──────────────────────────────────────────────────────

# These are toggled to True only after the user signs off the previous phase.
# Default: only DEVELOPMENT is unlocked. The user must explicitly unlock the
# next phase by editing the gate file (R&D/.phase_gate) to add the phase name.
# Editing this Python file to bypass the gate is a contract violation.

GATE_FILE = Path(__file__).parent / ".phase_gate"


class Phase(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class PhaseLockedError(PermissionError):
    """Raised when code tries to access a phase that hasn't been unlocked yet."""


class TamperedSplitError(RuntimeError):
    """Raised if the split boundaries hash doesn't match the locked-in expected hash."""


def _verify_split_integrity() -> None:
    """Confirms the split boundaries haven't been edited since lock-in."""
    if SPLIT_BOUNDARIES_HASH != EXPECTED_HASH:
        raise TamperedSplitError(
            f"Split boundaries hash mismatch.\n"
            f"  Computed:  {SPLIT_BOUNDARIES_HASH}\n"
            f"  Expected:  {EXPECTED_HASH}\n"
            f"This means the DEV_START/DEV_END/etc. values have been edited "
            f"since the lab was locked. Either:\n"
            f"  1. Revert the edit, OR\n"
            f"  2. Update EXPECTED_HASH in this file AND record the change in DECISIONS.md "
            f"with explicit user sign-off."
        )


def _phase_unlocked(phase: Phase) -> bool:
    """True iff `phase` has been unlocked by the gate file."""
    if phase == Phase.DEVELOPMENT:
        return True  # Always unlocked — the only data dev can see.
    if not GATE_FILE.exists():
        return False
    unlocked = {line.strip() for line in GATE_FILE.read_text().splitlines() if line.strip()}
    return phase.value in unlocked


def _log_request(phase: Phase, instrument: str, caller: str, n_rows_h1: int, n_rows_m3: int) -> None:
    """Append a JSON line to the access log. Tamper-evident audit trail."""
    log_path = Path(__file__).parent / "data_access_log.jsonl"
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": phase.value,
        "instrument": instrument,
        "caller": caller,
        "n_rows_h1": n_rows_h1,
        "n_rows_m3": n_rows_m3,
        "split_hash": SPLIT_BOUNDARIES_HASH,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _caller_info() -> str:
    """Best-effort identification of the caller for the audit log."""
    frame = inspect.currentframe()
    # Walk back up to find the first frame that's not in this file.
    while frame:
        f = frame.f_code
        if Path(f.co_filename).resolve() != Path(__file__).resolve():
            return f"{f.co_filename}:{frame.f_lineno}"
        frame = frame.f_back
    return "<unknown>"


@dataclass(frozen=True)
class _PhaseRange:
    start: str
    end: str


_PHASE_RANGES = {
    Phase.DEVELOPMENT: _PhaseRange(DEV_START, DEV_END),
    Phase.VALIDATION: _PhaseRange(VAL_START, VAL_END),
    Phase.HOLDOUT: _PhaseRange(HOLD_START, HOLD_END),
}


def _load_csv(instrument: str, granularity: str) -> pd.DataFrame:
    """Load a single CSV file. Internal — callers go through get_data()."""
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "data" / "raw" / f"{instrument}_{granularity}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    # Add mid columns so callers don't have to.
    for side in ("open", "high", "low", "close"):
        df[f"mid_{side}"] = (df[f"bid_{side}"] + df[f"ask_{side}"]) / 2.0
    return df


def get_data(phase: Phase, instrument: str = "BCO_USD") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (daily, h1, m3) DataFrames sliced to the requested phase.

    Args:
        phase: which data slice to return
        instrument: 'BCO_USD' or 'XAU_USD'

    Returns:
        (d1, h1, m3) — three pandas DataFrames, all UTC-indexed, all sliced
        to the phase's date range.

    Raises:
        PhaseLockedError if the phase hasn't been unlocked via the gate file
        TamperedSplitError if the split boundaries have been edited
    """
    _verify_split_integrity()
    if not _phase_unlocked(phase):
        raise PhaseLockedError(
            f"Phase {phase.value} is locked.\n"
            f"To unlock, the user must add '{phase.value}' to a new line in "
            f"{GATE_FILE}.\n"
            f"This is a one-way door — once unlocked, the seen data cannot be "
            f"unseen. Only unlock when the previous phase has been signed off."
        )

    rng = _PHASE_RANGES[phase]
    d1 = _load_csv(instrument, "D")
    h1 = _load_csv(instrument, "H1")
    m3 = _load_csv(instrument, "M3")

    start_ts = pd.Timestamp(rng.start, tz="UTC")
    end_ts = pd.Timestamp(rng.end, tz="UTC") + pd.Timedelta(days=1)  # Inclusive end-of-day

    d1_slice = d1[(d1.index >= start_ts) & (d1.index < end_ts)]
    h1_slice = h1[(h1.index >= start_ts) & (h1.index < end_ts)]
    m3_slice = m3[(m3.index >= start_ts) & (m3.index < end_ts)]

    _log_request(phase, instrument, _caller_info(), len(h1_slice), len(m3_slice))

    return d1_slice, h1_slice, m3_slice


def split_summary() -> str:
    """Print a summary of the locked split. Safe to call from anywhere."""
    return (
        f"R&D Data Split (LOCKED)\n"
        f"  Hash: {SPLIT_BOUNDARIES_HASH}\n"
        f"  DEVELOPMENT: {DEV_START} → {DEV_END}\n"
        f"  VALIDATION:  {VAL_START} → {VAL_END}\n"
        f"  HOLDOUT:     {HOLD_START} → {HOLD_END}\n"
        f"  Gate file:   {GATE_FILE}\n"
    )


if __name__ == "__main__":
    print(split_summary())
    _verify_split_integrity()
    print("Split integrity: OK")
    print(f"DEVELOPMENT unlocked: {_phase_unlocked(Phase.DEVELOPMENT)}")
    print(f"VALIDATION unlocked: {_phase_unlocked(Phase.VALIDATION)}")
    print(f"HOLDOUT unlocked: {_phase_unlocked(Phase.HOLDOUT)}")
