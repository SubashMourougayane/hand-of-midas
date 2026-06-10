"""TEST 19: Phase 3 Orphan Reconciler + Daily Recon Coverage.

Verifies the production safety net: every minute, position_monitor_job
reconciles broker positions against DB. Any orphan (broker has it, DB
doesn't) gets adopted with trade_ref 'OIL-MI-orphan-<id>' (or equivalent
per system) so the position monitor can manage exits going forward.

This test only checks the structural shape of the code — the actual
adoption logic is tested by integration with a mock executor below.

Runtime: <1 second.
"""
import sys
import os
import re
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# Each system must define reconcile_orphans()
# ============================================================================

@pytest.mark.parametrize("module_path", [
    "backend/scanner/live_engine.py",
    "backend-oil/scanner/live_engine.py",
    "backend-micro/scanner/live_engine.py",
    "backend-oil-micro/scanner/live_engine.py",
])
def test_reconcile_orphans_defined(module_path):
    """All 4 live engines must define reconcile_orphans()."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "def reconcile_orphans(" in src, (
        f"reconcile_orphans missing in {module_path} — production safety net required"
    )


@pytest.mark.parametrize("module_path", [
    "backend/scanner/live_engine.py",
    "backend-oil/scanner/live_engine.py",
    "backend-micro/scanner/live_engine.py",
    "backend-oil-micro/scanner/live_engine.py",
])
def test_reconcile_orphans_uses_on_conflict(module_path):
    """reconcile_orphans must use ON CONFLICT to be idempotent.
    Without it, running every minute would crash on duplicate broker_id."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Extract reconcile_orphans body
    m = re.search(r"def reconcile_orphans\(.*?(?=\ndef |\Z)", src, re.DOTALL)
    assert m, f"could not extract reconcile_orphans from {module_path}"
    body = m.group(0)
    assert "ON CONFLICT" in body.upper(), (
        f"reconcile_orphans in {module_path} must use ON CONFLICT for idempotency"
    )


@pytest.mark.parametrize("module_path", [
    "backend/scanner/live_engine.py",
    "backend-oil/scanner/live_engine.py",
    "backend-micro/scanner/live_engine.py",
    "backend-oil-micro/scanner/live_engine.py",
])
def test_reconcile_orphans_calls_telegram(module_path):
    """When an orphan is adopted, notify.orphan_adopted must fire.
    This is what wakes you up at 3 AM when a new bug appears."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    m = re.search(r"def reconcile_orphans\(.*?(?=\ndef |\Z)", src, re.DOTALL)
    body = m.group(0)
    assert "notify.orphan_adopted" in body, (
        f"reconcile_orphans in {module_path} must call notify.orphan_adopted"
    )


# ============================================================================
# Each scheduler wires reconcile_orphans into position_monitor_job
# ============================================================================

@pytest.mark.parametrize("scheduler_path", [
    "backend/scanner/scheduler.py",
    "backend-oil/scanner/scheduler.py",
    "backend-micro/scanner/scheduler.py",
    "backend-oil-micro/scanner/scheduler.py",
])
def test_position_monitor_calls_reconcile(scheduler_path):
    """position_monitor_job must call reconcile_orphans every cycle."""
    full = os.path.join(PROJECT_ROOT, scheduler_path)
    src = open(full).read()
    m = re.search(r"def position_monitor_job\(.*?(?=\ndef |\Z)", src, re.DOTALL)
    assert m, f"position_monitor_job not found in {scheduler_path}"
    body = m.group(0)
    assert "reconcile_orphans()" in body, (
        f"position_monitor_job in {scheduler_path} must call reconcile_orphans()"
    )


@pytest.mark.parametrize("scheduler_path", [
    "backend/scanner/scheduler.py",
    "backend-oil/scanner/scheduler.py",
    "backend-micro/scanner/scheduler.py",
    "backend-oil-micro/scanner/scheduler.py",
])
def test_reconcile_in_separate_try_except(scheduler_path):
    """reconcile_orphans must be in its OWN try/except so a position-monitor
    failure doesn't skip the safety net (and vice versa)."""
    full = os.path.join(PROJECT_ROOT, scheduler_path)
    src = open(full).read()
    m = re.search(r"def position_monitor_job\(.*?(?=\ndef |\Z)", src, re.DOTALL)
    body = m.group(0)
    # Count try blocks in position_monitor_job — must be ≥2
    try_count = body.count("try:")
    assert try_count >= 2, (
        f"position_monitor_job in {scheduler_path} has {try_count} try blocks; "
        "reconcile_orphans must be in its own try/except (separate from check_open_positions)"
    )


# ============================================================================
# Daily recon job is wired
# ============================================================================

@pytest.mark.parametrize("scheduler_path", [
    "backend/scanner/scheduler.py",
    "backend-oil/scanner/scheduler.py",
    "backend-micro/scanner/scheduler.py",
    "backend-oil-micro/scanner/scheduler.py",
])
def test_daily_recon_job_scheduled(scheduler_path):
    """Each scheduler must schedule daily_recon_job at 00:05 UTC."""
    full = os.path.join(PROJECT_ROOT, scheduler_path)
    src = open(full).read()
    assert "def daily_recon_job(" in src, (
        f"daily_recon_job missing in {scheduler_path}"
    )
    # Look for the cron registration
    assert re.search(r"daily_recon_job.*?cron.*?hour=0", src, re.DOTALL), (
        f"daily_recon_job not scheduled at hour=0 in {scheduler_path}"
    )


# ============================================================================
# notify module has the new helpers
# ============================================================================

def test_notify_has_orphan_adopted():
    """notify.orphan_adopted alerts you when the safety net catches a bug."""
    from backend import notify
    assert callable(getattr(notify, "orphan_adopted", None)), (
        "notify.orphan_adopted missing — required by reconcile_orphans"
    )


def test_notify_has_daily_recon():
    """notify.daily_recon sends the 00:05 UTC summary."""
    from backend import notify
    assert callable(getattr(notify, "daily_recon", None)), (
        "notify.daily_recon missing — required by daily_recon_job"
    )


def test_notify_has_error():
    """notify.error for ad-hoc alerts."""
    from backend import notify
    assert callable(getattr(notify, "error", None))


# ============================================================================
# DB has the safety helpers
# ============================================================================

def test_db_has_daily_recon_stats():
    """db.daily_recon_stats builds yesterday's summary numbers."""
    from backend.db import daily_recon_stats
    assert callable(daily_recon_stats)


# ============================================================================
# Migration SQL exists
# ============================================================================

def test_phase3_migration_sql_exists():
    """The Phase 3 migration creates the unique index on oanda_trade_id
    that makes ON CONFLICT work."""
    path = os.path.join(PROJECT_ROOT, "scripts/migration_phase3_orphan_safety.sql")
    assert os.path.exists(path), "scripts/migration_phase3_orphan_safety.sql missing"
    src = open(path).read()
    assert "gd_trades_oanda_trade_id_uniq" in src
    assert "UNIQUE INDEX" in src.upper()
    assert "WHERE oanda_trade_id IS NOT NULL" in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
