"""Unit tests for JournalEvent enum."""
from __future__ import annotations

from bt_engine.journal.events import JournalEvent


def test_journal_event_values_are_strings() -> None:
    for member in JournalEvent:
        assert isinstance(member.value, str)
        assert member.value == member.name


def test_journal_event_has_expected_members() -> None:
    required = {
        "ZONE_CREATED", "RETEST_TOUCH", "RETEST_FAIL",
        "CONFIRM_ATTEMPT", "CONFIRM_PASS", "CONFIRM_FAIL",
        "CLEAN_TOP3_REJECT",
        "ENTRY_SUBMIT", "ENTRY_FILL",
        "BE_TRIGGER", "BAR_OBSERVED_INTRADE",
        "EXIT_TP", "EXIT_SL", "EXIT_TIMEOUT", "EXIT_MANUAL",
    }
    have = set(JournalEvent.all())
    assert required.issubset(have)


def test_journal_event_str_inherited() -> None:
    assert JournalEvent.ENTRY_FILL == "ENTRY_FILL"
    assert JournalEvent.EXIT_TP.value == "EXIT_TP"
