"""JournalEvent enum — every event type written to bt_journal_events."""
from __future__ import annotations

from enum import Enum


class JournalEvent(str, Enum):
    ZONE_CREATED = "ZONE_CREATED"
    RETEST_TOUCH = "RETEST_TOUCH"
    RETEST_FAIL = "RETEST_FAIL"
    CONFIRM_ATTEMPT = "CONFIRM_ATTEMPT"
    CONFIRM_PASS = "CONFIRM_PASS"
    CONFIRM_FAIL = "CONFIRM_FAIL"
    CLEAN_TOP3_REJECT = "CLEAN_TOP3_REJECT"
    ENTRY_SUBMIT = "ENTRY_SUBMIT"
    ENTRY_FILL = "ENTRY_FILL"
    BE_TRIGGER = "BE_TRIGGER"
    BAR_OBSERVED_INTRADE = "BAR_OBSERVED_INTRADE"
    EXIT_TP = "EXIT_TP"
    EXIT_SL = "EXIT_SL"
    EXIT_TIMEOUT = "EXIT_TIMEOUT"
    EXIT_MANUAL = "EXIT_MANUAL"

    # ── Gate-decision instrumentation (Option D: dashboard visibility) ──
    # These fire on every strategy decision so the dashboard can render
    # the rejection funnel. Persisted to bt_signals (not bt_journal_events)
    # because they precede trade creation and have no trade_id.
    GATE_PIVOT_DETECTED = "GATE_PIVOT_DETECTED"
    GATE_SETUP_BUILT = "GATE_SETUP_BUILT"
    GATE_SETUP_REJECT_PIVOT_ORDER = "GATE_SETUP_REJECT_PIVOT_ORDER"
    GATE_SETUP_REJECT_DIFF = "GATE_SETUP_REJECT_DIFF"
    GATE_SETUP_INVALIDATED = "GATE_SETUP_INVALIDATED"
    GATE_SETUP_EXPIRED = "GATE_SETUP_EXPIRED"
    GATE_SIGNAL_ZONE_MISS = "GATE_SIGNAL_ZONE_MISS"
    GATE_SIGNAL_SESSION_FAIL = "GATE_SIGNAL_SESSION_FAIL"
    GATE_SIGNAL_REGIME_FAIL = "GATE_SIGNAL_REGIME_FAIL"
    GATE_SIGNAL_CONFIRM_FAIL = "GATE_SIGNAL_CONFIRM_FAIL"
    GATE_SIGNAL_STRICT_AFTER_FAIL = "GATE_SIGNAL_STRICT_AFTER_FAIL"
    GATE_FINALIZE_RISK_INVALID = "GATE_FINALIZE_RISK_INVALID"
    GATE_FINALIZE_RISK_PCT_CAP = "GATE_FINALIZE_RISK_PCT_CAP"
    GATE_FINALIZE_MIN_RISK_FLOOR = "GATE_FINALIZE_MIN_RISK_FLOOR"
    GATE_FINALIZE_DEDUP_COLLISION = "GATE_FINALIZE_DEDUP_COLLISION"
    GATE_SIGNAL_PASSED = "GATE_SIGNAL_PASSED"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(m.value for m in cls)

    @classmethod
    def gates(cls) -> tuple[str, ...]:
        return tuple(m.value for m in cls if m.value.startswith("GATE_"))
