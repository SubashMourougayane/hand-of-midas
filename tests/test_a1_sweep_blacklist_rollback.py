"""A1 — Sweep blacklist rollback on clean None return from execute_signal.

What these tests guard against:

The scheduler pre-marks a sweep_key as consumed (in-memory + DB) BEFORE
calling execute_signal. That's intentional for the EXCEPTION path — if
execute_signal raises mid-flight, an order may already be live, so we
do NOT want to retry the same sweep. The blacklist must stay set.

But the prior code applied the same rule when execute_signal returned
None CLEANLY — a soft skip (DD pause, sl_too_close, equity too low,
etc.) where no order was placed. Those skipped sweeps stayed blacklisted
for the rest of the day, silently losing legitimate trade opportunities
when the underlying condition cleared up.

A1 fix:
- Add `unmark_sweep_consumed()` DB helper.
- In the None-return branch only, scheduler now also unmarks the sweep
  (in-memory + DB).
- Exception branch behavior is UNCHANGED — sweep stays blacklisted.

These tests pin BOTH halves of the contract.

Doc: docs/bugs/A1_SWEEP_BLACKLIST_ROLLBACK.md
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Test 1 — DB helper unit test: SQL is idempotent and matches mark_sweep
# ─────────────────────────────────────────────────────────────────────────


def test_unmark_sweep_consumed_executes_delete_with_correct_args():
    """unmark_sweep_consumed() issues a DELETE with system/date/sweep_key bound."""
    from datetime import date as date_cls

    import backend.db as db

    target_date = date_cls(2026, 6, 20)
    captured = {}

    def fake_execute(query, args=None, fetch=False):
        captured["query"] = query
        captured["args"] = args
        captured["fetch"] = fetch
        return None

    with patch.object(db, "execute", side_effect=fake_execute):
        db.unmark_sweep_consumed("oil-micro", target_date, "2026-06-20T08:00:00+00:00_8_bullish")

    assert "DELETE FROM gd_traded_sweeps" in captured["query"]
    assert "system = %s" in captured["query"]
    assert "date = %s" in captured["query"]
    assert "sweep_key = %s" in captured["query"]
    assert captured["args"] == (
        "oil-micro",
        target_date,
        "2026-06-20T08:00:00+00:00_8_bullish",
    )


def test_unmark_sweep_consumed_is_safe_when_row_absent():
    """Calling unmark on a never-marked sweep is a no-op (zero rows deleted, no raise)."""
    from datetime import date as date_cls

    import backend.db as db

    with patch.object(db, "execute", return_value=None) as mocked:
        # Should not raise even though the sweep was never marked.
        db.unmark_sweep_consumed("oil-micro", date_cls(2026, 6, 20), "nonexistent_key")
        mocked.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# Test 2 — Behavioral: scheduler calls unmark when execute_signal returns None
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_modules():
    """Drop scheduler/live_engine modules so reload picks up our patches."""
    for mod in list(sys.modules.keys()):
        if mod.startswith(("scanner", "config", "backtest", "strategies",
                           "backend.execution", "backend.strategies",
                           "backend.backtest", "backend.data")):
            del sys.modules[mod]
    yield
    for mod in list(sys.modules.keys()):
        if mod.startswith(("scanner", "config", "backtest", "strategies",
                           "backend.execution", "backend.strategies",
                           "backend.backtest", "backend.data")):
            del sys.modules[mod]


def test_oil_micro_none_return_unmarks_sweep(fresh_modules, monkeypatch):
    """When execute_signal returns None, scheduler must unmark the sweep
    (both in-memory _traded_sweeps AND DB unmark_sweep_consumed).
    Direct unit on the rollback branch — does not run the full scan loop."""
    monkeypatch.chdir(REPO_ROOT)
    pkg_path = REPO_ROOT / "backend-oil-micro"
    sys.path.insert(0, str(pkg_path))

    import importlib
    importlib.invalidate_caches()

    import backend.db as db
    unmark_calls = []
    monkeypatch.setattr(db, "unmark_sweep_consumed",
                        lambda system, target_date, sweep_key: unmark_calls.append((system, sweep_key)))
    monkeypatch.setattr(db, "mark_sweep_consumed", lambda *a, **kw: None)

    scheduler = importlib.import_module("scanner.scheduler")

    # Verify the scheduler module's None-branch references unmark_sweep_consumed.
    # This is a structural assertion — proves the wire-up exists without booting
    # the full live engine + DB + broker + clock.
    src = Path(scheduler.__file__).read_text()
    none_branch_idx = src.find("skipped_by_engine")
    assert none_branch_idx > 0, "skipped_by_engine log marker not found"
    pre_skip = src[: none_branch_idx]
    # Walk back to the most recent `else:` to capture the None-branch block.
    last_else = pre_skip.rfind("else:")
    assert last_else > 0, "Could not locate None-return branch"
    none_branch = src[last_else:none_branch_idx]
    assert "unmark_sweep_consumed" in none_branch, (
        "Oil Micro scheduler None-branch missing unmark_sweep_consumed call. "
        "A1 regression — see docs/bugs/A1_SWEEP_BLACKLIST_ROLLBACK.md"
    )
    assert "_traded_sweeps[\"keys\"].discard" in none_branch, (
        "Oil Micro scheduler None-branch missing in-memory blacklist discard. "
        "A1 regression — see docs/bugs/A1_SWEEP_BLACKLIST_ROLLBACK.md"
    )


def test_gold_micro_none_return_unmarks_sweep(fresh_modules, monkeypatch):
    """Same A1 wire-up assertion for Gold Micro scheduler."""
    monkeypatch.chdir(REPO_ROOT)
    pkg_path = REPO_ROOT / "backend-micro"
    sys.path.insert(0, str(pkg_path))

    import importlib
    importlib.invalidate_caches()

    scheduler = importlib.import_module("scanner.scheduler")
    src = Path(scheduler.__file__).read_text()

    none_branch_idx = src.find("skipped_by_engine")
    assert none_branch_idx > 0, "skipped_by_engine log marker not found in Gold Micro"
    pre_skip = src[: none_branch_idx]
    last_else = pre_skip.rfind("else:")
    assert last_else > 0
    none_branch = src[last_else:none_branch_idx]
    assert "unmark_sweep_consumed" in none_branch, (
        "Gold Micro scheduler None-branch missing unmark_sweep_consumed call. "
        "A1 regression — see docs/bugs/A1_SWEEP_BLACKLIST_ROLLBACK.md"
    )
    assert "_traded_sweeps[\"keys\"].discard" in none_branch, (
        "Gold Micro scheduler None-branch missing in-memory blacklist discard. "
        "A1 regression — see docs/bugs/A1_SWEEP_BLACKLIST_ROLLBACK.md"
    )


# ─────────────────────────────────────────────────────────────────────────
# Test 3 — Exception branch UNCHANGED (sweep stays blacklisted)
# ─────────────────────────────────────────────────────────────────────────


def test_oil_micro_exception_branch_does_NOT_unmark_sweep():
    """The fix must NOT touch the exception branch — sweep stays blacklisted
    when execute_signal raises, since an order may have been placed."""
    src = (REPO_ROOT / "backend-oil-micro" / "scanner" / "scheduler.py").read_text()
    exc_idx = src.find("execute_signal_raised")
    assert exc_idx > 0, "execute_signal_raised marker not found"
    # Capture the exception branch — from `except Exception as e:` to the
    # next blank-line block boundary or end-of-loop.
    except_start = src.rfind("except Exception as e:", 0, exc_idx)
    assert except_start > 0
    # Reasonable bound — 1500 chars of context after `except`.
    exc_branch = src[except_start: except_start + 1500]
    assert "unmark_sweep_consumed" not in exc_branch, (
        "Oil Micro exception branch must NOT unmark the sweep. "
        "An exception means an order may already be live; retrying would duplicate. "
        "See docs/bugs/A1_SWEEP_BLACKLIST_ROLLBACK.md."
    )


def test_gold_micro_exception_branch_does_NOT_unmark_sweep():
    """Same exception-branch invariant for Gold Micro."""
    src = (REPO_ROOT / "backend-micro" / "scanner" / "scheduler.py").read_text()
    exc_idx = src.find("execute_signal_raised")
    assert exc_idx > 0
    except_start = src.rfind("except Exception as e:", 0, exc_idx)
    assert except_start > 0
    exc_branch = src[except_start: except_start + 1500]
    assert "unmark_sweep_consumed" not in exc_branch, (
        "Gold Micro exception branch must NOT unmark the sweep."
    )
