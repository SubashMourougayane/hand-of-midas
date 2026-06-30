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

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(m.value for m in cls)
