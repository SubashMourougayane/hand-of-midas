"""Tests for Filter #27 pending_order_monitor + Fix B grace fallback.

Covers BUG_FILTER_27_PENDING_RECONCILER_GAP:
- Broker silent-expire (pending TTL elapsed without OnTradeTransaction event)
- Grace-period TTL_EXPIRED fallback resolves zombie rows safely
- Throttled Telegram alert (1× per orphan ticket)
- No regressions to existing fill / cancel branches

Two layers of test:
1. Structural — every backend has the Fix B + Fix C code (text shape check)
2. Runtime — pure mock-based test of the orphan+grace logic on Oil Macro
   canonical implementation. Mock DWX file reads, DB execute, notify, _log.
"""
import sys
import os
import re
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# Structural — every backend must have Fix B + Fix C
# ============================================================================

LIMIT_BACKENDS = [
    "backend-oil/scanner/live_engine.py",       # Oil Macro (canonical)
    "backend-micro/scanner/live_engine.py",     # Gold Micro
    "backend-oil-micro/scanner/live_engine.py", # Oil Micro
]

# backend/scanner/live_engine.py (Gold Macro) is INTENTIONALLY excluded —
# Filter #27 stashed there per yearly-slice gate (project-filter-27-limit-orders).
# Gold Macro stays on market entry; no pending_order_monitor needed.


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_pending_grace_constant_defined(module_path):
    """Fix B: every limit-shipped backend must define PENDING_GRACE_SECONDS."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "PENDING_GRACE_SECONDS" in src, (
        f"PENDING_GRACE_SECONDS missing in {module_path} — Fix B incomplete"
    )
    # Also assert default is 60 (per design)
    m = re.search(r"PENDING_GRACE_SECONDS\s*=\s*(\d+)", src)
    assert m, f"PENDING_GRACE_SECONDS assignment not found in {module_path}"
    assert int(m.group(1)) == 60, (
        f"PENDING_GRACE_SECONDS in {module_path} = {m.group(1)} expected 60"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_orphan_alerted_set_defined(module_path):
    """Fix C: throttle set must be module-level (so it persists across calls)."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "_orphan_alerted" in src, (
        f"_orphan_alerted set missing in {module_path} — Fix C throttle incomplete"
    )
    # Must be module-level (not inside a function — that would reset every call)
    assert re.search(r"^_orphan_alerted\s*:", src, re.MULTILINE), (
        f"_orphan_alerted in {module_path} must be defined at module level"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_orphan_lookup_ttl_defined(module_path):
    """Fix B: _orphan_lookup_ttl_seconds helper must be defined."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "def _orphan_lookup_ttl_seconds" in src, (
        f"_orphan_lookup_ttl_seconds missing in {module_path}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_grace_fallback_uses_distinct_exit_reason(module_path):
    """The grace-fallback path must use 'LIMIT_TTL_EXPIRED_GRACE' (not the
    same 'LIMIT_TTL_EXPIRED' used by the cancelled-file branch). This lets
    us tell from telemetry which path resolved the row — Fix A's positive
    notify (cancelled_orders.json) vs Fix B's grace fallback."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "LIMIT_TTL_EXPIRED_GRACE" in src, (
        f"{module_path} must use LIMIT_TTL_EXPIRED_GRACE for grace-fallback "
        f"distinct from LIMIT_TTL_EXPIRED for cancelled-file path"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_orphan_alerted_cleared_on_resolution(module_path):
    """Fix C: the throttle set MUST be cleared (discard) when a ticket resolves
    (filled / cancelled / grace-expired). Otherwise an orphan that flips to
    filled still occupies the alerted-set, blocking re-alert if that ticket
    were ever to recur (unlikely but defensive)."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Count discard calls — should appear in fill, cancel, AND grace branches
    discard_count = src.count("_orphan_alerted.discard(ticket)")
    assert discard_count >= 3, (
        f"{module_path}: expected ≥3 _orphan_alerted.discard calls "
        f"(fill, cancel, grace branches); found {discard_count}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_grace_fallback_logs_journal_event(module_path):
    """Grace fallback must write LIMIT_TTL_EXPIRED journal event (with
    fallback=fix_b_grace marker) — same shape as cancelled-branch."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "fix_b_grace" in src, (
        f"{module_path}: grace fallback must journal fallback='fix_b_grace' for telemetry"
    )


# ============================================================================
# Runtime — Oil Macro pending_order_monitor with mocked DWX + DB
# ============================================================================

@pytest.fixture
def oil_monitor_env(monkeypatch):
    """Set up mock environment for testing Oil Macro pending_order_monitor.

    Mocks:
    - execute() — DB query returning the pending row(s) we set up
    - _read_dwx_json() — file reads return whatever pending/open/cancelled we configure
    - notify.* — capture Telegram calls
    - _log_journal_safe — capture journal events
    """
    # Late-import after sys.path is set up
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))
    from scanner import live_engine as oil_le

    captured = {
        "executes": [],
        "journal": [],
        "telegrams": [],
        "dwx_files": {},  # filename → content
    }

    def fake_execute(sql, params=None, fetch=False):
        captured["executes"].append({"sql": sql, "params": params, "fetch": fetch})
        # Return rows when asked SELECT, else nothing
        if fetch and "SELECT" in sql.upper():
            # Two query shapes:
            # 1. SELECT * FROM gd_trades ... mode='pending' — return preset rows
            # 2. SELECT context FROM gd_journal — return preset ttl_seconds
            if "gd_journal" in sql:
                return captured.get("journal_lookup_result", [])
            return captured.get("pending_rows", [])
        return None

    def fake_read_dwx(filename):
        return captured["dwx_files"].get(filename)

    def fake_journal(trade_ref, strategy, event_type, price=None, context=None):
        captured["journal"].append({
            "trade_ref": trade_ref, "strategy": strategy,
            "event_type": event_type, "price": price, "context": context,
        })

    fake_notify = MagicMock()
    fake_notify.limit_orphan_warn = MagicMock(side_effect=lambda *a, **k: captured["telegrams"].append(("orphan_warn", a, k)))
    fake_notify.limit_ttl_expired = MagicMock(side_effect=lambda *a, **k: captured["telegrams"].append(("ttl_expired", a, k)))
    fake_notify.trade_filled = MagicMock(side_effect=lambda *a, **k: captured["telegrams"].append(("filled", a, k)))

    monkeypatch.setattr(oil_le, "execute", fake_execute)
    monkeypatch.setattr(oil_le, "_read_dwx_json", fake_read_dwx)
    monkeypatch.setattr(oil_le, "_log_journal_safe", fake_journal)
    monkeypatch.setattr(oil_le, "notify", fake_notify)
    # Reset throttle set between tests
    oil_le._orphan_alerted.clear()

    return oil_le, captured


def _pending_row(trade_ref="OIL-AS-test", ticket="9999", strategy="alpha_sweep_oil",
                  side="LONG", entry_price=82.50, sl=82.00, tp=83.00,
                  units=1000, entry_time_offset_seconds=-30):
    """Build a fake gd_trades row dict (RealDictCursor shape)."""
    entry_time = datetime.now(timezone.utc) + timedelta(seconds=entry_time_offset_seconds)
    return {
        "trade_ref": trade_ref,
        "oanda_trade_id": ticket,
        "strategy": strategy,
        "side": side,
        "entry_price": entry_price,
        "sl_price": sl,
        "tp_price": tp,
        "units": units,
        "entry_time": entry_time,
    }


# ----------------------------------------------------------------------------
# Test 1: happy path — fill detected (regression: ensure FIX B didn't break it)
# ----------------------------------------------------------------------------

def test_fill_detected_unchanged(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999")]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {"9999": {"open_price": 82.51, "open_time": "2026.06.17 11:00:00"}},
        "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    # Update should be the fill update with mode='live'
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    assert "mode='live'" in updates[0]["sql"]
    # Journal should be LIMIT_FILLED
    assert any(j["event_type"] == "LIMIT_FILLED" for j in cap["journal"])
    # Telegram should be trade_filled
    assert any(t[0] == "filled" for t in cap["telegrams"])


# ----------------------------------------------------------------------------
# Test 2: cancel detected via DWX file (regression)
# ----------------------------------------------------------------------------

def test_cancel_detected_unchanged(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999")]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [{"ticket": "9999", "state": "EXPIRED"}],
    }
    oil_le.pending_order_monitor()
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    assert "LIMIT_TTL_EXPIRED" in updates[0]["sql"]
    assert "GRACE" not in updates[0]["sql"], (
        "cancel-via-DWX path should use LIMIT_TTL_EXPIRED, not LIMIT_TTL_EXPIRED_GRACE"
    )
    assert any(t[0] == "ttl_expired" for t in cap["telegrams"])


# ----------------------------------------------------------------------------
# Test 3: orphan within grace — no DB change, alert fires once
# ----------------------------------------------------------------------------

def test_orphan_within_grace_no_db_change(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    # Entry 30s ago, TTL 900s → 870s remaining → well within grace
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    # NO DB UPDATE
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 0, "within grace, should NOT update DB"
    # Telegram fired once
    assert sum(1 for t in cap["telegrams"] if t[0] == "orphan_warn") == 1


# ----------------------------------------------------------------------------
# Test 4: orphan past grace — marked LIMIT_TTL_EXPIRED_GRACE
# ----------------------------------------------------------------------------

def test_orphan_past_grace_resolves(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    # Entry 1000s ago, TTL 900s → 100s past TTL > 60s grace → resolve
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-1000)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    assert "LIMIT_TTL_EXPIRED_GRACE" in updates[0]["sql"]
    # Journal event written with fix_b_grace marker
    journal_evt = [j for j in cap["journal"] if j["event_type"] == "LIMIT_TTL_EXPIRED"]
    assert len(journal_evt) == 1
    assert journal_evt[0]["context"].get("fallback") == "fix_b_grace"
    # Telegram: ttl_expired sent
    assert any(t[0] == "ttl_expired" for t in cap["telegrams"])


# ----------------------------------------------------------------------------
# Test 5: idempotent — past-grace + already resolved → no-op
# ----------------------------------------------------------------------------

def test_grace_resolution_idempotent(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    # First call: resolves the row
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-1000)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    n_updates_first = len([e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")])
    # Second call simulates "row no longer in pending state" — empty pending_rows
    cap["executes"].clear()
    cap["journal"].clear()
    cap["telegrams"].clear()
    cap["pending_rows"] = []  # row already updated to mode='live' — DB filter excludes
    oil_le.pending_order_monitor()
    # No UPDATE, no journal, no telegram
    assert len([e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]) == 0
    assert len(cap["journal"]) == 0
    assert len(cap["telegrams"]) == 0


# ----------------------------------------------------------------------------
# Test 6: throttle — orphan called 5× within grace, only 1 telegram
# ----------------------------------------------------------------------------

def test_orphan_alert_throttled(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    for _ in range(5):
        oil_le.pending_order_monitor()
    n_alerts = sum(1 for t in cap["telegrams"] if t[0] == "orphan_warn")
    assert n_alerts == 1, f"expected 1 throttled alert across 5 calls, got {n_alerts}"


# ----------------------------------------------------------------------------
# M8: orphan-within-grace MUST write a LIMIT_ORPHAN journal event
# (so postmortem can reconstruct the broker-visibility gap from DB even
#  after file logs rotate). Throttled identically to the Telegram alert.
# ----------------------------------------------------------------------------

def test_m8_orphan_within_grace_writes_journal(oil_monitor_env):
    """Within-grace orphan must persist a LIMIT_ORPHAN row to gd_journal."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()

    orphan_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_ORPHAN"]
    assert len(orphan_evts) == 1, (
        f"expected exactly 1 LIMIT_ORPHAN journal event, got {len(orphan_evts)}"
    )
    ctx = orphan_evts[0]["context"]
    assert ctx.get("ticket") == "9999"
    assert ctx.get("ttl_seconds") == 900
    assert "elapsed_seconds" in ctx
    assert ctx.get("instrument") == "BCO_USD"  # Oil Macro
    assert "intended_limit" in ctx


def test_m8_orphan_journal_throttled_across_calls(oil_monitor_env):
    """Same throttle gate as Telegram: 1× journal event per ticket per session."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    for _ in range(5):
        oil_le.pending_order_monitor()

    orphan_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_ORPHAN"]
    assert len(orphan_evts) == 1, (
        f"M8: expected 1 throttled LIMIT_ORPHAN across 5 calls, got {len(orphan_evts)}; "
        f"throttle must use same _orphan_alerted set as Telegram"
    )
    # Telegram throttle still works
    assert sum(1 for t in cap["telegrams"] if t[0] == "orphan_warn") == 1


def test_m8_no_journal_when_past_grace(oil_monitor_env):
    """Past-grace path resolves the row → goes through LIMIT_TTL_EXPIRED journal,
    NOT LIMIT_ORPHAN. The two events are distinct: ORPHAN = within-grace warning,
    TTL_EXPIRED+fix_b_grace = resolution."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-1000)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()

    orphan_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_ORPHAN"]
    ttl_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_TTL_EXPIRED"]
    assert len(orphan_evts) == 0, "past-grace must NOT also write LIMIT_ORPHAN"
    assert len(ttl_evts) == 1


# ----------------------------------------------------------------------------
# M8 structural: every limit-shipped backend writes LIMIT_ORPHAN in the
# within-grace branch.
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m8_limit_orphan_journal_event_in_grace_branch(module_path):
    """M8: every limit-shipped backend must call _log_journal_safe with
    "LIMIT_ORPHAN" in the within-grace path. Locates the segment between
    'Within grace' and the orphan_alert_notify_failed exception handler,
    asserts LIMIT_ORPHAN is journaled there."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Locate within-grace block. Two markers exist for it:
    #   - "Within grace window" (oil)  /  "Within grace:" (micro, oil-micro)
    grace_marker = re.search(r"Within grace[^\n]*\n", src)
    assert grace_marker, f"{module_path}: 'Within grace' block marker not found"
    end_marker = src.find("orphan_alert_notify_failed", grace_marker.end())
    assert end_marker > 0, f"{module_path}: orphan-alert block end not found"
    block = src[grace_marker.end():end_marker]
    assert '"LIMIT_ORPHAN"' in block, (
        f"M8: {module_path} within-grace block must journal LIMIT_ORPHAN; "
        f"block was:\n{block[:500]}"
    )
    # Also assert it's gated by the throttle set so journal isn't spammed
    assert "_orphan_alerted.add" in block, (
        f"M8: {module_path} LIMIT_ORPHAN journal must be inside throttle gate"
    )


# ----------------------------------------------------------------------------
# M9: state + detected_via fields must be surfaced in LIMIT_TTL_EXPIRED journal
# context so postmortem can distinguish:
#   - state="EXPIRED"           detected_via="ontradetrans"  → broker normal-close
#   - state="EXPIRED_POLLED"    detected_via="poll"          → Fix A poll-detected
#                                                              (signals broker silent-expire)
#   - state="CANCELED"          detected_via="ontradetrans"  → manual cancel
#   - state="CANCELED_POLLED"   detected_via="poll"          → Fix A poll, was canceled
# ----------------------------------------------------------------------------

def test_m9_ontradetrans_state_in_journal(oil_monitor_env):
    """OnTradeTransaction-caught cancel: journal context must record state +
    detected_via. EA writes state='EXPIRED' detected_via='ontradetrans'."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999")]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [{
            "ticket": "9999",
            "state": "EXPIRED",
            "detected_via": "ontradetrans",
        }],
    }
    oil_le.pending_order_monitor()

    ttl_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_TTL_EXPIRED"]
    assert len(ttl_evts) == 1
    ctx = ttl_evts[0]["context"]
    assert ctx.get("state") == "EXPIRED"
    assert ctx.get("detected_via") == "ontradetrans"


def test_m9_poll_state_in_journal(oil_monitor_env):
    """Fix A poll-detected cancel: journal must record state='EXPIRED_POLLED'
    detected_via='poll'. This is the signal-of-interest for broker silent expire."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999")]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [{
            "ticket": "9999",
            "state": "EXPIRED_POLLED",
            "detected_via": "poll",
        }],
    }
    oil_le.pending_order_monitor()

    ttl_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_TTL_EXPIRED"]
    assert len(ttl_evts) == 1
    ctx = ttl_evts[0]["context"]
    assert ctx.get("state") == "EXPIRED_POLLED"
    assert ctx.get("detected_via") == "poll"


def test_m9_missing_state_backward_compat(oil_monitor_env):
    """Old EA writes (pre-M9 contract): if state/detected_via fields missing,
    journal still fires successfully with empty/default values (no crash)."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999")]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [{"ticket": "9999"}],  # NO state field
    }
    oil_le.pending_order_monitor()

    ttl_evts = [j for j in cap["journal"] if j["event_type"] == "LIMIT_TTL_EXPIRED"]
    assert len(ttl_evts) == 1, "must not crash when state field is missing"
    ctx = ttl_evts[0]["context"]
    assert ctx.get("state") == ""
    # detected_via defaults to 'ontradetrans' since old EAs were ontradetrans-only
    assert ctx.get("detected_via") == "ontradetrans"


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m9_cancelled_tickets_is_dict_with_state_metadata(module_path):
    """Structural: every limit-shipped backend must store cancelled_tickets as
    a dict (not set) with state + detected_via metadata, so cancel branch can
    look them up."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # cancelled_tickets must NOT be `= set()` anymore (M9 contract change)
    # Allow only the dict typed version: `cancelled_tickets: dict = {}` or similar.
    assert "cancelled_tickets: dict" in src or "cancelled_tickets = {}" in src, (
        f"M9: {module_path} cancelled_tickets must be a dict (was set) "
        f"to carry state + detected_via metadata"
    )
    # State/detected_via must be extracted from each entry
    assert '"state":' in src or "'state':" in src, (
        f"M9: {module_path} must extract state from cancelled_orders entries"
    )
    assert '"detected_via":' in src or "'detected_via':" in src, (
        f"M9: {module_path} must extract detected_via from cancelled_orders entries"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m9_journal_context_includes_state_fields(module_path):
    """Structural: every cancel-branch journal call must include 'state' and
    'detected_via' in the context dict."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Locate cancel branch: starts at `if ticket in cancelled_tickets:` and
    # ends at the next `if past_grace:` (or any other top-level branch).
    cancel_branch_start = src.find("if ticket in cancelled_tickets:")
    assert cancel_branch_start > 0, f"{module_path}: cancel branch not found"
    cancel_branch_end = src.find("# Orphan", cancel_branch_start)
    if cancel_branch_end < 0:
        cancel_branch_end = src.find("# Fix B:", cancel_branch_start)
    assert cancel_branch_end > 0, f"{module_path}: cancel branch end not found"
    branch = src[cancel_branch_start:cancel_branch_end]

    # Must journal LIMIT_TTL_EXPIRED with state + detected_via in context
    assert '"LIMIT_TTL_EXPIRED"' in branch
    assert '"state"' in branch, (
        f"M9: {module_path} cancel branch must include 'state' in journal context"
    )
    assert '"detected_via"' in branch, (
        f"M9: {module_path} cancel branch must include 'detected_via' in journal context"
    )


# ----------------------------------------------------------------------------
# M10: distinct Telegram for grace-fallback path. limit_ttl_expired() now
# takes via_grace=False/True. Cancel branch sends default (clean expiry);
# grace branch sends via_grace=True (suffix "(grace fallback)" so operator
# can distinguish broker silent-expire from broker normal-cancel).
# ----------------------------------------------------------------------------

def test_m10_clean_cancel_telegram_no_via_grace(oil_monitor_env):
    """Cancel branch (broker normal-cancel) → notify.limit_ttl_expired called
    with via_grace=False (default). Operator sees plain '⏱ LIMIT EXPIRED'."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999")]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {},
        "cancelled_orders.json": [{
            "ticket": "9999", "state": "EXPIRED", "detected_via": "ontradetrans",
        }],
    }
    oil_le.pending_order_monitor()

    ttl_calls = [t for t in cap["telegrams"] if t[0] == "ttl_expired"]
    assert len(ttl_calls) == 1
    name, args, kwargs = ttl_calls[0]
    # via_grace must be either absent (default) or False
    assert kwargs.get("via_grace", False) is False, (
        f"M10: cancel branch must NOT pass via_grace=True; got kwargs={kwargs}"
    )


def test_m10_grace_fallback_telegram_via_grace_true(oil_monitor_env):
    """Past-grace branch (broker silent-expire, Fix B resolves) →
    notify.limit_ttl_expired called with via_grace=True. Operator sees
    suffixed '⏱ LIMIT EXPIRED (grace fallback)'."""
    oil_le, cap = oil_monitor_env
    # Entry 1000s ago, TTL 900s → past grace
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-1000)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()

    ttl_calls = [t for t in cap["telegrams"] if t[0] == "ttl_expired"]
    assert len(ttl_calls) == 1
    name, args, kwargs = ttl_calls[0]
    assert kwargs.get("via_grace") is True, (
        f"M10: grace-fallback branch must pass via_grace=True; got kwargs={kwargs}"
    )


def test_m10_notify_signature_accepts_via_grace():
    """The notify.limit_ttl_expired signature must take via_grace kwarg
    with a default. Backward-compatible: existing callers still work."""
    import inspect
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify
    sig = inspect.signature(notify.limit_ttl_expired)
    params = sig.parameters
    assert "via_grace" in params, (
        "M10: notify.limit_ttl_expired must accept via_grace kwarg"
    )
    # Must have a default (backward compat)
    assert params["via_grace"].default is False, (
        f"M10: via_grace must default to False (backward compat); "
        f"got {params['via_grace'].default}"
    )


def test_m10_notify_grace_suffix_in_message():
    """When via_grace=True, the message body must contain a distinguishing
    marker. Sanity-check the actual string the operator sees."""
    import importlib
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify
    importlib.reload(notify)

    # Capture what would be sent
    sent_messages = []
    original_send = notify.send
    notify.send = lambda msg: sent_messages.append(msg)
    try:
        notify.limit_ttl_expired("OIL-AS-test", "BCO_USD", 82.50, via_grace=False)
        notify.limit_ttl_expired("OIL-AS-test", "BCO_USD", 82.50, via_grace=True)
    finally:
        notify.send = original_send

    assert len(sent_messages) == 2
    clean_msg, grace_msg = sent_messages
    # Clean message should NOT contain the grace marker
    assert "grace fallback" not in clean_msg.lower(), (
        f"M10: clean cancel msg should not contain 'grace fallback'; got:\n{clean_msg}"
    )
    # Grace message MUST contain the marker
    assert "grace fallback" in grace_msg.lower() or "silent expire" in grace_msg.lower(), (
        f"M10: grace fallback msg must contain distinguishing marker; got:\n{grace_msg}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m10_grace_branch_passes_via_grace_true(module_path):
    """Structural: every limit-shipped backend's grace branch must pass
    via_grace=True. The grace branch is identified by the 'fix_b_grace'
    journal context fingerprint."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Locate the grace branch via its unique journal context.
    grace_marker = src.find('"fallback": "fix_b_grace"')
    assert grace_marker > 0, f"{module_path}: fix_b_grace journal marker not found"
    # Look forward 800 chars for the notify.limit_ttl_expired call after marker
    snippet = src[grace_marker:grace_marker + 800]
    notify_call = snippet.find("notify.limit_ttl_expired")
    assert notify_call > 0, (
        f"{module_path}: notify.limit_ttl_expired not found after grace journal"
    )
    # Find the closing paren of that call
    call_start = grace_marker + notify_call
    call_end = src.find(")", call_start)
    assert call_end > 0
    call_text = src[call_start:call_end + 1]
    assert "via_grace=True" in call_text, (
        f"M10: {module_path} grace branch must pass via_grace=True; "
        f"call was: {call_text}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m10_cancel_branch_does_not_pass_via_grace(module_path):
    """Structural: cancel branch (clean cancel) must NOT pass via_grace=True
    — that's the grace branch's signal. Cancel branch keeps default."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    cancel_branch_start = src.find("if ticket in cancelled_tickets:")
    assert cancel_branch_start > 0
    # End at past_grace branch (next branch)
    cancel_branch_end = src.find("if past_grace:", cancel_branch_start)
    if cancel_branch_end < 0:
        cancel_branch_end = src.find("# Orphan", cancel_branch_start)
    assert cancel_branch_end > 0
    branch = src[cancel_branch_start:cancel_branch_end]
    assert "notify.limit_ttl_expired" in branch, (
        f"{module_path}: cancel branch missing notify.limit_ttl_expired"
    )
    assert "via_grace=True" not in branch, (
        f"M10: {module_path} cancel branch must NOT pass via_grace=True "
        f"(that's grace-branch only)"
    )


# ----------------------------------------------------------------------------
# M11: Filter #27 limit-success path was missing _log_signal(taken=True).
# Effect: gd_signals had NO row for limit-fired trades → cooldown query
# `SELECT timestamp FROM gd_signals ORDER BY timestamp DESC LIMIT 1` found
# the LAST signal (could be hours earlier) → 5-min cooldown gate fails open
# → next scan tick could re-fire the same engulfing setup.
#
# Fix: add _log_signal(strategy, direction, intended_limit, sl, tp,
# taken=True, trade_ref=trade_ref) BEFORE `return trade_ref` in the limit
# success path of all 3 limit-shipped backends. Wrap in try/except — broker
# order is already on the wire, must not crash before journaling.
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m11_limit_success_path_has_log_signal_taken_true(module_path):
    """Limit-success path (between notify.limit_placed and `return trade_ref`)
    must call _log_signal(...,taken=True). Without it, cooldown is broken."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Locate notify.limit_placed call (only 1 per backend in the success path)
    notify_placed = src.find("notify.limit_placed")
    assert notify_placed > 0, f"{module_path}: notify.limit_placed not found"
    # Find the next `return trade_ref` after notify.limit_placed
    return_pos = src.find("return trade_ref", notify_placed)
    assert return_pos > 0, f"{module_path}: return trade_ref after notify.limit_placed not found"
    # Block between notify.limit_placed and return trade_ref must contain
    # _log_signal(...,taken=True,...)
    block = src[notify_placed:return_pos]
    assert "_log_signal" in block, (
        f"M11: {module_path} limit-success path missing _log_signal between "
        f"notify.limit_placed and `return trade_ref`. cooldown will be broken."
    )
    assert "taken=True" in block, (
        f"M11: {module_path} _log_signal in limit path must pass taken=True; "
        f"block was:\n{block[:500]}"
    )


def _real_lines(text: str) -> str:
    """Strip comment-only lines (preserves inline comments after code)."""
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m11_log_signal_uses_intended_limit_not_entry_price(module_path):
    """The cooldown row should record the actual intended limit price (the
    price the broker was asked to fill at), not the strategy's entry_price.
    Asserts _log_signal is called with `intended_limit` as the price arg."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    notify_placed = src.find("notify.limit_placed")
    return_pos = src.find("return trade_ref", notify_placed)
    block = _real_lines(src[notify_placed:return_pos])  # strip comment-only lines
    # Find the _log_signal call in this block
    log_signal_idx = block.find("_log_signal(")
    assert log_signal_idx > 0, f"{module_path}: no _log_signal call found"
    # Extract the call args (find matching close paren by counting)
    depth = 0
    end = log_signal_idx
    for i, ch in enumerate(block[log_signal_idx:], start=log_signal_idx):
        if ch == "(": depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    call_text = block[log_signal_idx:end]
    assert "intended_limit" in call_text, (
        f"M11: {module_path} _log_signal in limit path should record "
        f"intended_limit (broker-side price) not entry_price (strategy-side); "
        f"call was:\n{call_text}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m11_log_signal_wrapped_in_try_except(module_path):
    """Like the market path, the limit-path _log_signal must be wrapped in
    try/except. Broker order is already on the wire — _log_signal raising
    (e.g. numpy serialization) must not crash before `return trade_ref`.

    Heuristic: find the LAST `try:` before the `_log_signal(` call in the
    limit-success block — that try must be on the same indent or deeper than
    the _log_signal line, and the next non-blank line after _log_signal's
    body should be `except ... :`."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    notify_placed = src.find("notify.limit_placed")
    return_pos = src.find("return trade_ref", notify_placed)
    block = _real_lines(src[notify_placed:return_pos])

    # Find the _log_signal( call (real one, not comment) and confirm a `try:`
    # line appears immediately above it (within 3 non-blank lines).
    lines = block.split("\n")
    log_idx = None
    for i, line in enumerate(lines):
        if "_log_signal(" in line and "#" not in line.split("_log_signal(")[0]:
            log_idx = i
            break
    assert log_idx is not None, f"{module_path}: _log_signal( call line not found"
    # Walk backwards looking for `try:` within 3 non-blank lines
    found_try = False
    seen_nonblank = 0
    for j in range(log_idx - 1, max(-1, log_idx - 6), -1):
        s = lines[j].strip()
        if not s:
            continue
        seen_nonblank += 1
        if s == "try:":
            found_try = True
            break
        if seen_nonblank >= 3:
            break
    assert found_try, (
        f"M11: {module_path} _log_signal in limit path must immediately follow "
        f"`try:`; preceding lines were:\n" + "\n".join(lines[max(0, log_idx - 5):log_idx + 1])
    )
    # Walk forward looking for `except` within 6 non-blank lines after _log_signal
    found_except = False
    seen_nonblank = 0
    for j in range(log_idx + 1, min(len(lines), log_idx + 10)):
        s = lines[j].strip()
        if not s:
            continue
        seen_nonblank += 1
        if s.startswith("except"):
            found_except = True
            break
        if seen_nonblank >= 6:
            break
    assert found_except, (
        f"M11: {module_path} _log_signal in limit path must have `except` handler; "
        f"following lines were:\n" + "\n".join(lines[log_idx:log_idx + 8])
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m11_no_silent_return_in_limit_path(module_path):
    """Regression guard: ensure no `return trade_ref` appears in the limit
    success path WITHOUT a preceding _log_signal call. Catches future re-
    introduction of the bug if someone refactors and drops the call."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Find every "return trade_ref" in the file and check each that's between
    # notify.limit_placed and the next non-limit code section
    notify_placed = src.find("notify.limit_placed")
    if notify_placed < 0:
        return  # Gold Macro / non-limit backends N/A
    # Look for `return trade_ref` within 1500 chars after notify.limit_placed
    region = src[notify_placed:notify_placed + 1500]
    # Count return statements within that limit-success region
    return_count = region.count("return trade_ref")
    assert return_count >= 1, f"{module_path}: limit success region missing return trade_ref"
    # _log_signal MUST appear between notify.limit_placed and the first return
    first_return = region.find("return trade_ref")
    pre_return = region[:first_return]
    assert "_log_signal" in pre_return, (
        f"M11: {module_path} `return trade_ref` in limit path appears WITHOUT "
        f"a preceding _log_signal — bug re-introduced?"
    )


# ----------------------------------------------------------------------------
# M13: stuck-on-bad-open_price escalation. H4 alone (skip cycle, retry) loops
# forever silently if DWX writes bad data persistently. M13 adds a per-ticket
# counter; after BAD_OPEN_PRICE_THRESHOLD cycles, fire Telegram + force-cancel
# the pending order + mark exit_reason='LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED'.
# Sentinel value (-1) suppresses re-fire after escalation.
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m13_bad_open_price_state_defined(module_path):
    """Module-level _bad_open_price_cycles dict + threshold constant must
    exist for every limit-shipped backend."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "_bad_open_price_cycles" in src, (
        f"M13: {module_path} missing _bad_open_price_cycles dict"
    )
    # Must be module-level (not inside a function — would reset every cycle)
    assert re.search(r"^_bad_open_price_cycles\s*:", src, re.MULTILINE), (
        f"M13: {module_path} _bad_open_price_cycles must be module-level"
    )
    assert "BAD_OPEN_PRICE_THRESHOLD" in src, (
        f"M13: {module_path} missing BAD_OPEN_PRICE_THRESHOLD constant"
    )
    # Default threshold = 5 (5 × 30s = ~2.5 min)
    m = re.search(r"BAD_OPEN_PRICE_THRESHOLD\s*=\s*(\d+)", src)
    assert m, f"{module_path}: BAD_OPEN_PRICE_THRESHOLD assignment not found"
    assert int(m.group(1)) == 5, (
        f"M13: {module_path} BAD_OPEN_PRICE_THRESHOLD = {m.group(1)} expected 5"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m13_h4_block_increments_counter(module_path):
    """H4 block (raw_open_price <= 0) must increment _bad_open_price_cycles
    counter for the ticket. Otherwise threshold never reached.

    Searches the entire H4 branch — from the `if raw_open_price is None`
    test through the `continue` statement — for the increment pattern."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Anchor at the bad-data branch start (covers counter inc + warn + escalation)
    branch_start = src.find("if raw_open_price is None")
    assert branch_start > 0, f"{module_path}: H4 branch start not found"
    # Walk ~5000 chars from the branch start
    block = src[branch_start:branch_start + 5000]
    assert "_bad_open_price_cycles" in block, (
        f"M13: {module_path} H4 block must reference _bad_open_price_cycles"
    )
    # Increment pattern: counter += 1 OR explicit assignment from prev_count + 1
    assert ("prev_count + 1" in block or "+= 1" in block), (
        f"M13: {module_path} H4 block must increment counter; block was:\n{block[:1200]}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m13_threshold_triggers_force_cancel(module_path):
    """After BAD_OPEN_PRICE_THRESHOLD cycles, must:
    - Journal LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED
    - Call cancel_pending_order
    - UPDATE gd_trades SET exit_reason='LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED'
    - Send Telegram via notify.bad_open_price_persistent
    - Set sentinel (-1) to suppress re-fire"""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    branch_start = src.find("if raw_open_price is None")
    block = src[branch_start:branch_start + 5000]

    assert ">= BAD_OPEN_PRICE_THRESHOLD" in block, (
        f"M13: {module_path} must compare bad_count >= BAD_OPEN_PRICE_THRESHOLD"
    )
    assert "LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED" in block, (
        f"M13: {module_path} must journal LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED"
    )
    assert "cancel_pending_order(ticket)" in block, (
        f"M13: {module_path} must call cancel_pending_order(ticket) on escalation"
    )
    assert "notify.bad_open_price_persistent" in block, (
        f"M13: {module_path} must notify.bad_open_price_persistent on escalation"
    )
    # Sentinel: must set counter to -1 after escalation
    assert "_bad_open_price_cycles[ticket] = -1" in block, (
        f"M13: {module_path} must set sentinel (-1) to suppress re-fire"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m13_counter_cleared_on_valid_fill(module_path):
    """When a valid open_price arrives (transient bad data resolved), counter
    must be cleared so a future bad-data sequence starts fresh."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    h4_marker = src.find("limit_filled_missing_open_price")
    # The valid-fill path follows the H4 block (after `actual_fill = float(...)`)
    actual_fill_marker = src.find("actual_fill = float(raw_open_price)", h4_marker)
    assert actual_fill_marker > 0, f"{module_path}: actual_fill assignment not found"
    # Walk forward ~200 chars; must clear the per-ticket counter
    after = src[actual_fill_marker:actual_fill_marker + 300]
    assert "_bad_open_price_cycles.pop" in after, (
        f"M13: {module_path} valid-fill path must clear bad-data counter; "
        f"after-context:\n{after}"
    )


def test_m13_notify_helper_exists():
    """notify.bad_open_price_persistent must be defined with expected sig."""
    import inspect
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify
    assert hasattr(notify, "bad_open_price_persistent"), (
        "M13: notify.bad_open_price_persistent helper must exist"
    )
    sig = inspect.signature(notify.bad_open_price_persistent)
    expected_params = {"trade_ref", "instrument", "ticket",
                        "intended_limit", "bad_cycles", "raw_value"}
    actual_params = set(sig.parameters.keys())
    assert expected_params.issubset(actual_params), (
        f"M13: notify.bad_open_price_persistent missing params; "
        f"have {actual_params}, need {expected_params}"
    )


def test_m13_notify_message_contains_diagnostic_info():
    """Telegram message body must include trade_ref, ticket, raw_value, and
    bad_cycles count so operator has enough info to diagnose without grep."""
    import importlib
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify
    importlib.reload(notify)

    sent = []
    original_send = notify.send
    notify.send = lambda msg: sent.append(msg)
    try:
        notify.bad_open_price_persistent(
            trade_ref="OIL-AS-test123",
            instrument="BCO_USD",
            ticket="9999",
            intended_limit=82.50,
            bad_cycles=5,
            raw_value=0,
        )
    finally:
        notify.send = original_send

    assert len(sent) == 1
    msg = sent[0]
    assert "OIL-AS-test123" in msg, "msg must include trade_ref"
    assert "9999" in msg, "msg must include ticket"
    assert "5" in msg, "msg must include bad_cycles count"
    assert "open_price" in msg.lower() or "BAD OPEN_PRICE" in msg, (
        "msg must mention open_price diagnostic"
    )
    assert "Force-cancel" in msg or "force-cancel" in msg, (
        "msg must indicate force-cancel action"
    )


# ----------------------------------------------------------------------------
# Test 7: ttl_seconds missing from journal — no false-positive grace resolution
# ----------------------------------------------------------------------------

def test_no_journal_uses_config_fallback_h3(oil_monitor_env):
    """H3 (2026-06-17): when LIMIT_PLACED journal is missing, _orphan_lookup_ttl_seconds
    falls back to ALPHA_SWEEP['limit_ttl_bars'] * 180 from config. Long-elapsed
    rows now resolve cleanly via grace path (was a forever-stuck scenario before)."""
    oil_le, cap = oil_monitor_env
    # Long-elapsed row, ttl_seconds NOT in journal. Pre-H3: stuck forever. Post-H3:
    # config fallback returns ALPHA_SWEEP['limit_ttl_bars'] * 180 (5*180=900),
    # row is past TTL+grace → resolves cleanly.
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-99999)]
    cap["journal_lookup_result"] = []  # no journal context
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    # H3: NOW resolves via grace path (config fallback returned 900s, elapsed >> 900+60)
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 1, "H3: config fallback should let grace resolve the orphan"
    assert "LIMIT_TTL_EXPIRED_GRACE" in updates[0]["sql"]
    # Telegram: ttl_expired sent (resolution path)
    assert any(t[0] == "ttl_expired" for t in cap["telegrams"]), (
        "H3: grace-resolved orphan should fire ttl_expired Telegram"
    )


# ----------------------------------------------------------------------------
# Test 8: orphan that resolves clears the throttle set
# ----------------------------------------------------------------------------

def test_throttle_cleared_on_resolution(oil_monitor_env):
    oil_le, cap = oil_monitor_env
    # First: orphan within grace → adds to throttle set
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 900}}]
    cap["dwx_files"] = {
        "pending_orders.json": {}, "open_orders.json": {}, "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    assert "9999" in oil_le._orphan_alerted

    # Then ticket appears in cancelled → resolves + discards
    cap["executes"].clear()
    cap["journal"].clear()
    cap["telegrams"].clear()
    cap["dwx_files"]["cancelled_orders.json"] = [{"ticket": "9999", "state": "EXPIRED"}]
    oil_le.pending_order_monitor()
    assert "9999" not in oil_le._orphan_alerted, (
        "ticket resolved via cancelled-branch must be discarded from throttle"
    )


# ============================================================================
# Structural — EA Fix A (text shape on .mq5)
# ============================================================================

EA_PATH = os.path.join(PROJECT_ROOT, "mql5", "DWX_Server.mq5")


def test_ea_fix_a_tracks_prev_pending_tickets():
    """Fix A: EA must track ticket SET between ticks (not just count)."""
    src = open(EA_PATH).read()
    assert "g_prevPendingTickets" in src, (
        "EA Fix A missing — must track g_prevPendingTickets array"
    )
    assert "FIX_A_MAX_PENDING" in src, (
        "EA Fix A must define FIX_A_MAX_PENDING bound"
    )


def test_ea_fix_a_writes_polled_state():
    """Fix A: when ticket lost, EA writes cancelled_orders.json with
    state='EXPIRED_POLLED' or 'CANCELED_POLLED' (distinct from
    'EXPIRED'/'CANCELED' written by OnTradeTransaction)."""
    src = open(EA_PATH).read()
    assert "EXPIRED_POLLED" in src, "EA Fix A missing EXPIRED_POLLED state tag"
    assert "CANCELED_POLLED" in src, "EA Fix A missing CANCELED_POLLED state tag"
    assert "detected_via\\\":\\\"poll" in src, (
        "EA Fix A entries must include detected_via='poll' marker"
    )


def test_ea_fix_a_idempotent_with_ontradetransaction():
    """Fix A must NOT double-write if OnTradeTransaction already added the
    ticket to cancelled_orders.json. Achieved by reading existing file +
    string-search for ticket key before append."""
    src = open(EA_PATH).read()
    # The Fix A loop must read cancelled_orders.json and skip if ticket already there
    assert "ReadFile(g_folder + \"/cancelled_orders.json\")" in src, (
        "Fix A must read cancelled_orders.json to dedup against OnTradeTransaction"
    )


def test_ea_version_bumped():
    """EA version must reflect the latest in-flight contract change.
    Currently v2.14 (H5 history retry pool). Update this assertion when
    a new EA-side contract change ships."""
    src = open(EA_PATH).read()
    assert "v2.14" in src, "EA version not bumped to v2.14 — required to verify recompile on VPS"


# ============================================================================
# C1 — IsOrderAccepted retcode-aware acceptance
# ============================================================================

def test_ea_has_is_order_accepted_helper():
    """C1: EA must have IsOrderAccepted(sent, retcode) helper that requires
    BOTH OrderSend delivery AND retcode in {DONE, PLACED, DONE_PARTIAL}."""
    src = open(EA_PATH).read()
    assert "bool IsOrderAccepted(" in src, "C1: IsOrderAccepted helper missing"
    assert "TRADE_RETCODE_DONE" in src, "C1: must check TRADE_RETCODE_DONE"
    assert "TRADE_RETCODE_PLACED" in src, "C1: must check TRADE_RETCODE_PLACED"


def test_ea_no_bare_ordersend_success_assignment():
    """C1: no callsite should bind `bool success = OrderSend(...)` directly.
    Must use `bool sent = OrderSend(...); bool accepted = IsOrderAccepted(sent, result.retcode);`
    pattern. Otherwise rejection-with-success-true semantics return.
    """
    src = open(EA_PATH).read()
    # Old pattern that we no longer want anywhere:
    bad_pattern = "bool success = OrderSend("
    assert bad_pattern not in src, (
        f"C1: found '{bad_pattern}' — bad pre-fix pattern. "
        f"All callsites must use IsOrderAccepted helper."
    )


def test_ea_response_uses_accepted_not_sent():
    """C1: every JSON response after OrderSend must serialize `accepted` (not
    just `sent`) into the success field. We assert the count of `accepted ?` in
    response StringFormat lines matches the count of OrderSend(request, result)
    callsites (6 today)."""
    src = open(EA_PATH).read()
    # Count OrderSend callsites that should be retcode-aware (in Execute* funcs)
    ordersend_count = src.count("OrderSend(request, result)")
    accepted_serializations = src.count("accepted ? \"true\" : \"false\"")
    assert accepted_serializations >= ordersend_count, (
        f"C1: {ordersend_count} OrderSend calls but only "
        f"{accepted_serializations} 'accepted ? true : false' serializations. "
        f"Some callsite is still using `success` instead of `accepted`."
    )


# ============================================================================
# C2 — SL wrong-side defensive guard (structural + runtime)
# ============================================================================

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c2_wrong_side_sl_long_guard_present(module_path):
    """C2: every limit-shipped backend must have the LONG wrong-side SL guard
    BEFORE place_limit_order. Pattern: `direction == "long" and sl_price >= intended_limit`.
    """
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'direction == "long" and sl_price >= intended_limit' in src, (
        f"C2: {module_path} missing LONG wrong-side SL guard"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c2_wrong_side_sl_short_guard_present(module_path):
    """C2: every limit-shipped backend must have the SHORT wrong-side SL guard
    BEFORE place_limit_order. Pattern: `direction == "short" and sl_price <= intended_limit`.
    """
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'direction == "short" and sl_price <= intended_limit' in src, (
        f"C2: {module_path} missing SHORT wrong-side SL guard"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c2_journals_limit_invalid_sl(module_path):
    """C2: wrong-side SL guard must journal LIMIT_INVALID_SL with full context
    so postmortem can reconstruct what was attempted."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "LIMIT_INVALID_SL" in src, (
        f"C2: {module_path} must journal LIMIT_INVALID_SL on wrong-side SL"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c2_logs_skip_reason(module_path):
    """C2: wrong-side guard must record gd_signals row with
    skip_reason='limit_invalid_sl_wrong_side' so the cooldown query
    in scheduler.py picks it up."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "limit_invalid_sl_wrong_side" in src, (
        f"C2: {module_path} must use skip_reason='limit_invalid_sl_wrong_side' "
        f"so 5-min cooldown picks it up via gd_signals"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c2_guard_runs_BEFORE_place_limit_order(module_path):
    """C2: the wrong-side guard must execute BEFORE place_limit_order to prevent
    a guaranteed-reject order from hitting the broker. Verify the LONG guard
    text appears before the place_limit_order callsite in the file."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    long_guard_pos = src.find('direction == "long" and sl_price >= intended_limit')
    place_limit_pos = src.find("place_limit_order(")
    assert long_guard_pos > 0, f"C2: LONG guard not found in {module_path}"
    assert place_limit_pos > 0, f"C2: place_limit_order callsite not found in {module_path}"
    assert long_guard_pos < place_limit_pos, (
        f"C2: {module_path} — LONG guard at byte {long_guard_pos} must come "
        f"BEFORE place_limit_order at byte {place_limit_pos}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c2_guard_does_not_swallow_valid_signals(module_path):
    """C2 negative test: ensure the guard predicate is sl >= limit (LONG) and
    sl <= limit (SHORT). Off-by-one operators (`>` vs `>=`) would silently
    swallow boundary cases or fail to catch them."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # The guard MUST use >= for LONG (sl exactly at limit is invalid — broker
    # would reject because there's no room for the SL between fill and limit)
    # and <= for SHORT (mirror).
    assert "sl_price >= intended_limit" in src, (
        f"C2: {module_path} LONG guard must use >= (not >)"
    )
    assert "sl_price <= intended_limit" in src, (
        f"C2: {module_path} SHORT guard must use <= (not <)"
    )


# ============================================================================
# C3 — Broker-pending-without-DB-row reconciliation (structural + runtime)
# ============================================================================

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c3_reconcile_broker_pending_orphans_defined(module_path):
    """C3: every limit-shipped backend must define reconcile_broker_pending_orphans().
    This handles the timeout-orphan race where broker accepted a pending limit
    but Python timed out before it could INSERT the DB row."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "def reconcile_broker_pending_orphans(" in src, (
        f"C3: {module_path} missing reconcile_broker_pending_orphans()"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c3_called_from_pending_order_monitor(module_path):
    """C3: reconcile_broker_pending_orphans() must be called from
    pending_order_monitor — preferably BEFORE the DB pending_db query so
    the early-return on empty pending_db doesn't skip orphan reconciliation."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Find call site
    assert "reconcile_broker_pending_orphans()" in src, (
        f"C3: {module_path} must call reconcile_broker_pending_orphans()"
    )
    # Verify ordering: call must be inside pending_order_monitor + BEFORE the
    # `if not pending_db: return` early-exit
    monitor_def = src.find("def pending_order_monitor(")
    assert monitor_def > 0
    monitor_body = src[monitor_def:]
    call_pos = monitor_body.find("reconcile_broker_pending_orphans()")
    early_return = monitor_body.find("if not pending_db:")
    assert call_pos > 0, f"C3: {module_path} call site not inside pending_order_monitor"
    assert early_return > 0, f"C3: {module_path} early-return guard missing"
    assert call_pos < early_return, (
        f"C3: {module_path} reconcile_broker_pending_orphans must run BEFORE "
        f"the `if not pending_db: return` early-exit, otherwise empty DB skips it"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c3_filters_by_magic(module_path):
    """C3: must check `OUR_MAGIC` (or equivalent) so we never adopt manual MT5
    trades placed by the user via the platform UI."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "OUR_MAGIC = 200000" in src, (
        f"C3: {module_path} must define OUR_MAGIC=200000 to filter manual MT5 trades"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c3_skips_known_db_tickets(module_path):
    """C3: must skip tickets that ARE in any DB row (mode='pending' or live —
    those are handled by the existing pending_order_monitor flow)."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Verify db_known_tickets set is built and ticket presence is checked
    assert "db_known_tickets" in src, (
        f"C3: {module_path} must build db_known_tickets set"
    )
    assert "if ticket in db_known_tickets:" in src, (
        f"C3: {module_path} must check `if ticket in db_known_tickets`"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_c3_journal_event_distinct(module_path):
    """C3: must journal LIMIT_ORPHAN_PENDING_CANCELLED — distinct from
    LIMIT_TTL_EXPIRED (broker silent-expire) and LIMIT_TTL_EXPIRED_GRACE
    (Fix B fallback). Telemetry should be able to count race-orphan rate
    independently of normal expiry rate."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "LIMIT_ORPHAN_PENDING_CANCELLED" in src, (
        f"C3: {module_path} must journal LIMIT_ORPHAN_PENDING_CANCELLED"
    )


# ----------------------------------------------------------------------------
# Runtime: C3 functional tests on Oil Macro canonical
# ----------------------------------------------------------------------------

def test_c3_no_orphans_no_op(oil_monitor_env):
    """C3: when pending_orders.json is empty OR all tickets are in DB,
    reconcile_broker_pending_orphans does nothing (no cancel calls)."""
    oil_le, cap = oil_monitor_env
    # Test 1: empty pending_file
    cap["dwx_files"]["pending_orders.json"] = {}
    cap["dwx_files"]["open_orders.json"] = {}
    cap["dwx_files"]["cancelled_orders.json"] = []
    cap["pending_rows"] = []
    cancel_calls = []
    import unittest.mock as m
    with m.patch.object(oil_le, "cancel_pending_order",
                        side_effect=lambda t: cancel_calls.append(t) or {"success": True}):
        oil_le.reconcile_broker_pending_orphans()
    assert len(cancel_calls) == 0


def test_c3_cancels_orphan_pending_at_our_magic(oil_monitor_env):
    """C3: a ticket in pending_orders.json with our magic AND no DB row
    triggers cancel_pending_order + journal."""
    oil_le, cap = oil_monitor_env
    cap["dwx_files"]["pending_orders.json"] = {
        "9999": {"symbol": "BRENT.ecn", "type": "BUY_LIMIT", "price": 82.50,
                 "magic": 200000, "comment": "alpha_sweep_oil|orphaned-test"}
    }
    cap["dwx_files"]["open_orders.json"] = {}
    cap["dwx_files"]["cancelled_orders.json"] = []
    cap["pending_rows"] = []  # No DB rows

    cancel_calls = []
    import unittest.mock as m
    with m.patch.object(oil_le, "cancel_pending_order",
                        side_effect=lambda t: cancel_calls.append(t) or {"success": True}):
        oil_le.reconcile_broker_pending_orphans()

    assert cancel_calls == ["9999"], f"expected cancel call for ticket 9999, got {cancel_calls}"
    assert any(j["event_type"] == "LIMIT_ORPHAN_PENDING_CANCELLED" for j in cap["journal"])


def test_c3_skips_wrong_magic(oil_monitor_env):
    """C3: a ticket in pending_orders.json with someone else's magic (manual
    MT5 trade) must NOT be cancelled. Critical safety property."""
    oil_le, cap = oil_monitor_env
    cap["dwx_files"]["pending_orders.json"] = {
        "9999": {"symbol": "BRENT.ecn", "type": "BUY_LIMIT", "price": 82.50,
                 "magic": 12345, "comment": "manual user trade"}  # NOT our magic
    }
    cap["dwx_files"]["open_orders.json"] = {}
    cap["dwx_files"]["cancelled_orders.json"] = []
    cap["pending_rows"] = []

    cancel_calls = []
    import unittest.mock as m
    with m.patch.object(oil_le, "cancel_pending_order",
                        side_effect=lambda t: cancel_calls.append(t) or {"success": True}):
        oil_le.reconcile_broker_pending_orphans()

    assert len(cancel_calls) == 0, (
        f"C3 SAFETY: must NOT cancel non-our-magic tickets; got {cancel_calls}"
    )


def test_c3_skips_db_known_tickets(oil_monitor_env):
    """C3: a ticket already in DB (with exit_time IS NULL) must NOT be cancelled.
    Those tickets are handled by the existing pending_order_monitor flow."""
    oil_le, cap = oil_monitor_env
    cap["dwx_files"]["pending_orders.json"] = {
        "9999": {"symbol": "BRENT.ecn", "type": "BUY_LIMIT", "price": 82.50,
                 "magic": 200000, "comment": "alpha_sweep_oil|known-trade"}
    }
    cap["dwx_files"]["open_orders.json"] = {}
    cap["dwx_files"]["cancelled_orders.json"] = []
    # Override the SELECT oanda_trade_id query to return this ticket
    # (separate from pending_rows which mocks SELECT * FROM gd_trades)
    original_execute = cap["executes"]
    def fake_execute_with_known(sql, params=None, fetch=False):
        cap["executes"].append({"sql": sql, "params": params, "fetch": fetch})
        if fetch and "oanda_trade_id" in sql and "FROM gd_trades" in sql:
            return [{"oanda_trade_id": "9999"}]  # this ticket IS known to DB
        if fetch and "gd_journal" in sql:
            return []
        return None
    import unittest.mock as m
    with m.patch.object(oil_le, "execute", fake_execute_with_known):
        cancel_calls = []
        with m.patch.object(oil_le, "cancel_pending_order",
                            side_effect=lambda t: cancel_calls.append(t) or {"success": True}):
            oil_le.reconcile_broker_pending_orphans()

    assert len(cancel_calls) == 0, (
        f"C3: must skip DB-known tickets; got {cancel_calls}"
    )


def test_c3_handles_malformed_magic(oil_monitor_env):
    """C3: malformed magic field (e.g. None or string) must NOT cause crash;
    must skip the ticket conservatively."""
    oil_le, cap = oil_monitor_env
    cap["dwx_files"]["pending_orders.json"] = {
        "9999": {"symbol": "BRENT.ecn", "type": "BUY_LIMIT", "price": 82.50,
                 "magic": None, "comment": "?"},
        "8888": {"symbol": "BRENT.ecn", "type": "BUY_LIMIT", "price": 82.50,
                 "magic": "weird", "comment": "?"},
    }
    cap["dwx_files"]["open_orders.json"] = {}
    cap["dwx_files"]["cancelled_orders.json"] = []
    cap["pending_rows"] = []

    cancel_calls = []
    import unittest.mock as m
    with m.patch.object(oil_le, "cancel_pending_order",
                        side_effect=lambda t: cancel_calls.append(t) or {"success": True}):
        # Should NOT raise
        oil_le.reconcile_broker_pending_orphans()

    assert len(cancel_calls) == 0, (
        f"C3: malformed magic must skip; got {cancel_calls}"
    )


# ============================================================================
# H1 — LIMIT_DRY_RUN env var hardening (parse_dry_run_env helper)
# ============================================================================

class TestH1ParseDryRunEnv:
    """Pure-function tests for parse_dry_run_env(). Tests run against the
    helper directly — no monkey-patching engines needed.

    Bug class fixed: old code `os.environ.get("LIMIT_DRY_RUN","true").lower() == "true"`
    silently flipped `'true '` (trailing space) to dry_run=False (REAL LIMIT, opposite
    of intent). Also silently treated typos (`'fasle'`) and shorthand (`'0'`/`'no'`)
    as REAL LIMIT.
    """

    def setup_method(self):
        # Clear all relevant env vars before each test (isolation).
        for key in ("LIMIT_DRY_RUN", "OIL_LIMIT_DRY_RUN", "MICRO_LIMIT_DRY_RUN",
                    "OIL_MICRO_LIMIT_DRY_RUN"):
            os.environ.pop(key, None)

    def teardown_method(self):
        for key in ("LIMIT_DRY_RUN", "OIL_LIMIT_DRY_RUN", "MICRO_LIMIT_DRY_RUN",
                    "OIL_MICRO_LIMIT_DRY_RUN"):
            os.environ.pop(key, None)

    def _get(self):
        from backend.execution.limit_price import parse_dry_run_env
        return parse_dry_run_env

    def test_unset_returns_default_true(self):
        f = self._get()
        assert f() is True

    def test_unset_can_override_default(self):
        f = self._get()
        assert f(default=False) is False

    def test_canonical_true(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "true"
        assert f() is True

    def test_canonical_false(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "false"
        assert f() is False

    def test_trailing_space_true(self):
        """The smoking-gun bug: 'true ' → False under old code, → True now."""
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "true "
        assert f() is True, "trailing space must NOT flip 'true' to False"

    def test_trailing_space_false(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "false "
        assert f() is False

    def test_leading_space(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = " false"
        assert f() is False

    def test_uppercase(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "TRUE"
        assert f() is True
        os.environ["LIMIT_DRY_RUN"] = "FALSE"
        assert f() is False

    def test_title_case(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "True"
        assert f() is True
        os.environ["LIMIT_DRY_RUN"] = "False"
        assert f() is False

    def test_recognised_synonyms_true(self):
        f = self._get()
        for v in ("1", "yes", "on"):
            os.environ["LIMIT_DRY_RUN"] = v
            assert f() is True, f"value {v!r} must parse to True"

    def test_recognised_synonyms_false(self):
        f = self._get()
        for v in ("0", "no", "off"):
            os.environ["LIMIT_DRY_RUN"] = v
            assert f() is False, f"value {v!r} must parse to False"

    def test_typo_defaults_to_default(self, caplog):
        """Typo = unrecognised value. Must default to safe (default=True) AND
        log WARNING so ops can spot it."""
        import logging
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "fasle"
        with caplog.at_level(logging.WARNING):
            assert f() is True
        assert any("limit_dry_run_unrecognised_value" in r.getMessage()
                   for r in caplog.records), (
            "typo must produce a WARNING log line"
        )

    def test_empty_string_defaults(self, caplog):
        import logging
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = ""
        with caplog.at_level(logging.WARNING):
            assert f() is True
        assert any("limit_dry_run_unrecognised_value" in r.getMessage()
                   for r in caplog.records)

    def test_per_system_override_wins(self):
        """M7 hook: per-system override beats global LIMIT_DRY_RUN."""
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "false"
        os.environ["OIL_LIMIT_DRY_RUN"] = "true"
        assert f(system_prefix="OIL") is True
        # Without prefix → still uses global
        assert f() is False

    def test_per_system_falls_back_to_global(self):
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "false"
        # OIL_LIMIT_DRY_RUN is unset → falls back to global LIMIT_DRY_RUN=false
        assert f(system_prefix="OIL") is False

    def test_per_system_empty_string_skipped_to_global(self):
        """If per-system var is unset (None), fall back to global. (Note: an
        empty-string per-system would be 'set' and would hit the unrecognised
        path with default=True; that is intentional — the operator clearly
        meant to override but typo'd, so safe-default + warn fires.)"""
        f = self._get()
        os.environ["LIMIT_DRY_RUN"] = "false"
        # OIL_LIMIT_DRY_RUN not set at all
        assert f(system_prefix="OIL") is False


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h1_no_bare_environ_get(module_path):
    """H1: no live engine should use the bare `os.environ.get("LIMIT_DRY_RUN", ...)`
    pattern — must use parse_dry_run_env() helper. Otherwise whitespace + typo
    foot-guns return."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'os.environ.get("LIMIT_DRY_RUN"' not in src, (
        f"H1: {module_path} still has bare os.environ.get('LIMIT_DRY_RUN', ...) "
        f"— must call parse_dry_run_env() instead"
    )
    assert "parse_dry_run_env" in src, (
        f"H1: {module_path} must import + call parse_dry_run_env()"
    )


# ============================================================================
# H6 — Through-market sanity check
# ============================================================================

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h6_through_market_long_guard_present(module_path):
    """H6: every limit-shipped backend must have the LONG through-market guard.
    Pattern: limit > current_ask → skip + journal LIMIT_PRICE_THROUGH_MARKET."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'direction == "long" and live_ask_now and intended_limit > live_ask_now' in src, (
        f"H6: {module_path} missing LONG through-market guard"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h6_through_market_short_guard_present(module_path):
    """H6: every limit-shipped backend must have the SHORT through-market guard.
    Pattern: limit < current_bid → skip + journal LIMIT_PRICE_THROUGH_MARKET."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'direction == "short" and live_bid_now and intended_limit < live_bid_now' in src, (
        f"H6: {module_path} missing SHORT through-market guard"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h6_journal_event_distinct(module_path):
    """H6: must journal LIMIT_PRICE_THROUGH_MARKET — distinct from LIMIT_INVALID_SL
    (C2) and LIMIT_ORDER_FAILED (broker reject after placement). Operator can
    count pre-broker-skip frequency from journal queries."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "LIMIT_PRICE_THROUGH_MARKET" in src, (
        f"H6: {module_path} must journal LIMIT_PRICE_THROUGH_MARKET"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h6_skip_reason_logged(module_path):
    """H6: gd_signals row written with skip_reason='limit_price_through_market'
    so 5-min cooldown query in scheduler.py picks it up correctly."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'skip_reason="limit_price_through_market"' in src, (
        f"H6: {module_path} must use skip_reason='limit_price_through_market'"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h6_runs_BEFORE_place_limit_order(module_path):
    """H6: through-market check must execute BEFORE place_limit_order to
    prevent broker-reject and avoid sending bad orders to the EA."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    h6_long_pos = src.find('intended_limit > live_ask_now')
    place_limit_pos = src.find("place_limit_order(")
    assert h6_long_pos > 0, f"H6: LONG guard not found in {module_path}"
    assert place_limit_pos > 0, f"H6: place_limit_order callsite not found"
    assert h6_long_pos < place_limit_pos, (
        f"H6: {module_path} — LONG through-market guard at byte {h6_long_pos} "
        f"must come BEFORE place_limit_order at byte {place_limit_pos}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h6_handles_missing_live_price(module_path):
    """H6: if live_price is None or missing bid/ask, skip the check rather than
    crashing. The broker will catch any actual through-market case via 10015
    reject — pre-emptive guard is best-effort."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Verify guard wraps in `if live_price:` check
    assert "if live_price:" in src, (
        f"H6: {module_path} must guard the through-market check on live_price truthiness"
    )
    # Verify per-direction guard checks bid/ask for None
    assert "live_ask_now and intended_limit" in src, (
        f"H6: {module_path} LONG guard must check live_ask_now is truthy"
    )
    assert "live_bid_now and intended_limit" in src, (
        f"H6: {module_path} SHORT guard must check live_bid_now is truthy"
    )


# ============================================================================
# M12 — sl_too_close_to_price check parity across all 4 backends
# ============================================================================

ALL_BACKENDS = [
    "backend/scanner/live_engine.py",       # Gold Macro
    "backend-micro/scanner/live_engine.py", # Gold Micro
    "backend-oil/scanner/live_engine.py",   # Oil Macro (was missing — M12 fix)
    "backend-oil-micro/scanner/live_engine.py",  # Oil Micro
]


@pytest.mark.parametrize("module_path", ALL_BACKENDS)
def test_m12_sl_too_close_to_price_check_present(module_path):
    """M12: every backend (including Gold Macro non-limit + all 3 limit-shipped)
    must have the upstream sl_too_close_to_price check. Catches market-order
    SL-too-close before it reaches the broker. Production evidence: 4 historical
    OIL-AS retcode=10016 rejects that this check would have pre-empted."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'skip_reason="sl_too_close_to_price"' in src, (
        f"M12: {module_path} missing upstream sl_too_close_to_price check"
    )


@pytest.mark.parametrize("module_path", ALL_BACKENDS)
def test_m12_check_runs_BEFORE_oanda_units(module_path):
    """M12: the sl_too_close_to_price check must run BEFORE the order is sent
    to the broker. Easy-to-test proxy: it must come before `oanda_units = ...`
    line where the order direction is finalized."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    sl_check_pos = src.find('skip_reason="sl_too_close_to_price"')
    oanda_units_pos = src.find("oanda_units = units")
    assert sl_check_pos > 0
    assert oanda_units_pos > 0
    assert sl_check_pos < oanda_units_pos, (
        f"M12: {module_path} — sl_too_close check at byte {sl_check_pos} must "
        f"come BEFORE oanda_units at byte {oanda_units_pos}"
    )


@pytest.mark.parametrize("module_path,expected_buffer", [
    ("backend/scanner/live_engine.py", "1.0"),       # XAU buffer = $1
    ("backend-micro/scanner/live_engine.py", "1.0"), # XAU buffer = $1
    ("backend-oil/scanner/live_engine.py", "0.05"),  # BCO buffer = $0.05
    ("backend-oil-micro/scanner/live_engine.py", "0.05"),  # BCO buffer = $0.05
])
def test_m12_uses_instrument_appropriate_buffer(module_path, expected_buffer):
    """M12: XAU systems use $1 buffer (instrument scale), BCO systems use
    $0.05 (BRENT scale ~10x smaller). Wrong buffer would cause false positives
    or false negatives. Verify per-instrument scaling preserved."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Find the SHORT clause (sl_price <= current_ask + BUFFER)
    import re
    m = re.search(r"sl_price\s*<=\s*current_ask\s*\+\s*([\d.]+)", src)
    assert m, f"M12: {module_path} SHORT clause not found"
    actual_buffer = m.group(1)
    assert actual_buffer == expected_buffer, (
        f"M12: {module_path} expected buffer {expected_buffer}, got {actual_buffer}"
    )


# ============================================================================
# H3 — _orphan_lookup_ttl_seconds config fallback
# ============================================================================

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h3_helper_logs_db_error(module_path):
    """H3: bare `except: return None` is replaced with `_log.exception` so
    DB errors during journal lookup are observable, not silent."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'orphan_ttl_lookup_db_error' in src, (
        f"H3: {module_path} must log DB errors via orphan_ttl_lookup_db_error event"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h3_helper_falls_back_to_config(module_path):
    """H3: when journal returns no row OR the lookup raises, fall back to
    ALPHA_SWEEP/MICRO_ALPHA_SWEEP `limit_ttl_bars` from config and compute
    ttl_seconds = bars * 180. Without this, orphan rows never resolve."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'orphan_ttl_lookup_config_fallback' in src, (
        f"H3: {module_path} must log fallback via orphan_ttl_lookup_config_fallback event"
    )
    assert 'limit_ttl_bars' in src, (
        f"H3: {module_path} fallback must read limit_ttl_bars from config"
    )
    # The fallback must do bars * 180 (M3 cadence)
    assert '* 180' in src, (
        f"H3: {module_path} fallback must compute bars * 180 (M3 = 180s)"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h3_helper_logs_no_journal_path(module_path):
    """H3: when journal lookup returns empty (rows == None or empty), log
    a warn so we can see the fallback being exercised in practice."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'orphan_ttl_lookup_no_journal' in src, (
        f"H3: {module_path} must log orphan_ttl_lookup_no_journal warn when no rows found"
    )


def test_h3_helper_returns_int_when_journal_has_ttl(oil_monitor_env):
    """H3 happy path: journal has ttl → return int."""
    oil_le, cap = oil_monitor_env
    cap["journal_lookup_result"] = [{"context": {"ttl_seconds": 600}}]
    result = oil_le._orphan_lookup_ttl_seconds("OIL-AS-test")
    assert result == 600, f"H3 happy path: expected 600, got {result}"


def test_h3_helper_falls_back_when_journal_empty(oil_monitor_env, monkeypatch):
    """H3: journal lookup returns empty → fall back to config (5*180=900)."""
    oil_le, cap = oil_monitor_env
    cap["journal_lookup_result"] = []  # empty rows
    # Mock ALPHA_SWEEP to known value
    monkeypatch.setattr(oil_le, "ALPHA_SWEEP", {"limit_ttl_bars": 5})
    result = oil_le._orphan_lookup_ttl_seconds("OIL-AS-orphan-pre-h3")
    assert result == 900, f"H3 fallback: expected 900 (5*180), got {result}"


def test_h3_helper_falls_back_when_journal_missing_field(oil_monitor_env, monkeypatch):
    """H3: journal row exists but no ttl_seconds field → fall back to config."""
    oil_le, cap = oil_monitor_env
    cap["journal_lookup_result"] = [{"context": {"sl": 92.0}}]  # missing ttl_seconds
    monkeypatch.setattr(oil_le, "ALPHA_SWEEP", {"limit_ttl_bars": 5})
    result = oil_le._orphan_lookup_ttl_seconds("OIL-AS-bad-journal")
    assert result == 900, f"H3 fallback: expected 900, got {result}"


def test_h3_helper_falls_back_on_db_exception(oil_monitor_env, monkeypatch):
    """H3: DB raises → fall back to config (was bare `except: return None` before)."""
    oil_le, cap = oil_monitor_env
    monkeypatch.setattr(oil_le, "execute", lambda *a, **kw: (_ for _ in ()).throw(Exception("DB hiccup")))
    monkeypatch.setattr(oil_le, "ALPHA_SWEEP", {"limit_ttl_bars": 5})
    result = oil_le._orphan_lookup_ttl_seconds("OIL-AS-db-error")
    assert result == 900, f"H3 fallback on DB error: expected 900, got {result}"


def test_h3_helper_returns_none_if_config_also_broken(oil_monitor_env, monkeypatch):
    """H3: pathological case — both journal AND config fail. Return None
    rather than crash. Caller treats None as "can't determine, leave alone"."""
    oil_le, cap = oil_monitor_env
    cap["journal_lookup_result"] = []  # empty
    # Mock ALPHA_SWEEP to a non-dict that will raise on .get()
    class _Broken:
        def get(self, *a, **kw): raise RuntimeError("config broken")
    monkeypatch.setattr(oil_le, "ALPHA_SWEEP", _Broken())
    result = oil_le._orphan_lookup_ttl_seconds("OIL-AS-config-broken")
    assert result is None, f"H3 pathological: expected None, got {result}"


# ============================================================================
# H4 — Warn on missing/zero open_price in fill detection
# ============================================================================

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h4_no_silent_default_to_intended_limit(module_path):
    """H4: no CALLSITE should silently default to intended_limit when
    open_price is missing. Old pattern was `.get("open_price", intended_limit)`
    which collapsed three failure modes (missing/zero/None) into one bad path.

    We allow the bad-pattern string to appear in COMMENTS (the new code's
    docstring references it as 'old pattern') — only callsites matter.
    Verify by counting: each occurrence in a comment line vs code line."""
    full = os.path.join(PROJECT_ROOT, module_path)
    bad_pattern = '.get("open_price", intended_limit)'
    code_hits = []
    for i, line in enumerate(open(full), 1):
        if bad_pattern not in line:
            continue
        # Skip if the line is a comment (#) or a docstring continuation
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # If we see this in actual code, that's the bug
        code_hits.append(f"{module_path}:{i}: {stripped[:120]}")
    assert not code_hits, (
        f"H4: {module_path} still has the bad-default pattern in CODE "
        f"(not just comments). Hits: {code_hits}"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h4_validates_raw_open_price(module_path):
    """H4: must validate raw_open_price is not None and > 0 before float()."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "raw_open_price = fill_info.get(\"open_price\")" in src, (
        f"H4: {module_path} must extract raw_open_price separately"
    )
    assert "raw_open_price is None or float(raw_open_price) <= 0" in src, (
        f"H4: {module_path} must check None and <= 0 before using raw_open_price"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h4_logs_warning_on_invalid(module_path):
    """H4: when open_price is invalid, log warn with structured fields."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "limit_filled_missing_open_price" in src, (
        f"H4: {module_path} must log limit_filled_missing_open_price warn"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_h4_skips_cycle_on_invalid(module_path):
    """H4: must use `continue` (skip cycle, retry next 30s tick) NOT `break`
    or `return`. Other tickets in pending_db should still be processed."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Find the H4 warn block, verify a `continue` follows shortly after
    import re
    # Match: limit_filled_missing_open_price ... [some chars] ... continue
    # Window expanded to 4000 chars to accommodate M13 escalation block
    # (force-cancel + journal + Telegram inserted between warn and continue).
    m = re.search(
        r"limit_filled_missing_open_price[\s\S]{0,4000}?continue",
        src
    )
    assert m, (
        f"H4: {module_path} must use `continue` (not break/return) after "
        f"the missing-open-price warn — other tickets in same cycle must still process"
    )


def test_h4_runtime_skips_when_open_price_zero(oil_monitor_env):
    """H4 runtime: open_orders.json has open_price=0 → skip cycle, no DB UPDATE.
    Pre-H4: would write entry_price=$0 to DB (garbage state)."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {"9999": {"open_price": 0, "open_time": "..."}},  # ZERO
        "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 0, "H4: open_price=0 must NOT trigger UPDATE (would write garbage entry_price)"
    journals = [j for j in cap["journal"] if j["event_type"] == "LIMIT_FILLED"]
    assert len(journals) == 0, "H4: no LIMIT_FILLED journal when open_price invalid"


def test_h4_runtime_skips_when_open_price_missing(oil_monitor_env):
    """H4 runtime: open_orders.json missing open_price field → skip cycle.
    Pre-H4: would silently write actual_fill=intended_limit (fake clean fill)."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {"9999": {"open_time": "..."}},  # NO open_price field
        "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 0, (
        "H4: missing open_price must NOT trigger UPDATE (would silently default to intended_limit)"
    )


def test_h4_runtime_skips_when_open_price_none(oil_monitor_env):
    """H4 runtime: open_orders.json has open_price=None → skip cycle, no crash.
    Pre-H4: float(None) would raise TypeError."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {"9999": {"open_price": None, "open_time": "..."}},
        "cancelled_orders.json": [],
    }
    # Should NOT raise
    oil_le.pending_order_monitor()
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 0, "H4: open_price=None must NOT crash, must skip cycle"


def test_h4_runtime_valid_fill_unchanged(oil_monitor_env):
    """H4 regression: a valid fill (open_price=82.51) must STILL trigger
    the UPDATE + LIMIT_FILLED journal. We didn't break the happy path."""
    oil_le, cap = oil_monitor_env
    cap["pending_rows"] = [_pending_row(ticket="9999", entry_time_offset_seconds=-30)]
    cap["dwx_files"] = {
        "pending_orders.json": {},
        "open_orders.json": {"9999": {"open_price": 82.51, "open_time": "..."}},
        "cancelled_orders.json": [],
    }
    oil_le.pending_order_monitor()
    updates = [e for e in cap["executes"] if e["sql"].strip().upper().startswith("UPDATE")]
    assert len(updates) == 1, "H4 regression: valid fill must still UPDATE"
    assert "mode='live'" in updates[0]["sql"]
    assert any(j["event_type"] == "LIMIT_FILLED" for j in cap["journal"]), (
        "H4 regression: valid fill must journal LIMIT_FILLED"
    )


# ============================================================================
# H2 — Cross-process last_response.json race / per-cmd response correlation
# ============================================================================

def test_h2_cmd_filename_includes_pid():
    """H2: command filename must include PID so concurrent processes never
    collide on the same millisecond. Pattern: cmd_<unix_ms>_<pid>.txt."""
    from backend.execution import mt5_executor
    src = open(mt5_executor.__file__).read()
    assert "os.getpid()" in src, (
        "H2: _write_command must include os.getpid() in filename to prevent "
        "cross-process collisions"
    )


def test_h2_wait_response_uses_per_cmd_file():
    """H2: _wait_response must look at responses/<filename> path first, NOT
    last_response.json. Per-cmd response is the canonical correlation path."""
    from backend.execution import mt5_executor
    src = open(mt5_executor.__file__).read()
    assert 'os.path.join(resp_dir, filename)' in src, (
        "H2: _wait_response must construct responses/<filename> path"
    )
    # Verify the per-cmd path is checked BEFORE the shared file fallback
    h2_canonical_pos = src.find("# H2 canonical path: per-cmd response file")
    fallback_pos = src.find("# Backward-compat: if EA is older")
    assert h2_canonical_pos > 0
    assert fallback_pos > 0
    assert h2_canonical_pos < fallback_pos, (
        "H2: per-cmd canonical path must be checked BEFORE shared-file fallback"
    )


def test_h2_wait_response_signature_takes_filename():
    """H2: _wait_response must accept filename as first positional arg.
    Old signature was _wait_response(timeout=10) — caller couldn't pass a
    correlation key, hence the race."""
    from backend.execution import mt5_executor
    import inspect
    sig = inspect.signature(mt5_executor._wait_response)
    params = list(sig.parameters.keys())
    assert params[0] == "filename", (
        f"H2: _wait_response first param must be 'filename', got {params}"
    )


def test_h2_send_command_threads_filename_to_wait():
    """H2: _send_command must capture the filename returned by _write_command
    and pass it to _wait_response."""
    from backend.execution import mt5_executor
    src = open(mt5_executor.__file__).read()
    # Verify the wiring: filename = _write_command(...) ; _wait_response(filename, ...)
    assert "filename = _write_command(cmd_string)" in src, (
        "H2: _send_command must capture filename = _write_command(...)"
    )
    assert "_wait_response(filename, timeout)" in src, (
        "H2: _send_command must pass filename to _wait_response"
    )


# EA-side structural tests
def test_h2_ea_has_write_final_response_helper():
    """H2: EA must define WriteFinalResponse(content, filename) helper."""
    src = open(EA_PATH).read()
    assert "void WriteFinalResponse(string content, string filename)" in src, (
        "H2: EA missing WriteFinalResponse helper"
    )


def test_h2_ea_writes_per_cmd_response():
    """H2: WriteFinalResponse must write to responses/<filename> when filename
    is non-empty."""
    src = open(EA_PATH).read()
    assert 'WriteFile(g_folder + "/responses/" + filename, content)' in src, (
        "H2: WriteFinalResponse must write to responses/ subfolder"
    )


def test_h2_ea_no_bare_last_response_writes():
    """H2: every WriteFile to last_response.json should now go through
    WriteFinalResponse helper (which writes BOTH per-cmd file AND shared
    file). Only ONE direct write should remain — inside the helper itself."""
    src = open(EA_PATH).read()
    # Count actual `WriteFile(g_folder + "/last_response.json"` occurrences
    direct_writes = src.count('WriteFile(g_folder + "/last_response.json"')
    assert direct_writes == 1, (
        f"H2: expected exactly 1 direct WriteFile to last_response.json (the "
        f"helper), got {direct_writes}. Other paths must use WriteFinalResponse."
    )


def test_h2_ea_execute_signatures_take_filename():
    """H2: every Execute* function (except CloseAll which is summary-only)
    must accept `string filename` as last param so per-cmd responses can be
    correlated."""
    src = open(EA_PATH).read()
    required = [
        "void ExecuteOpen(string symbol, string type, double volume, double price, double sl, double tp, string comment, string filename)",
        "void ExecuteOpenPending(string symbol, string type, double volume, double price,\n                       double sl, double tp, int ttl_seconds, string comment, string filename)",
        "void ExecuteCancelPending(ulong ticket, string filename)",
        "void ExecuteModify(ulong ticket, double sl, double tp, string filename)",
        "void ExecuteClose(ulong ticket, string filename)",
        "void ExecuteClosePartial(ulong ticket, double volumeLots, string filename)",
        "void ExecuteCloseAll(string filename)",
    ]
    for sig in required:
        assert sig in src, f"H2: EA missing signature: {sig[:80]}"


def test_h2_ea_version_bumped_to_213():
    """H2: EA version bumped to v2.13 to mark the per-cmd response contract.
    (Note: the in-flight EA version may have moved beyond v2.13; this test
    ensures we never regress BELOW v2.13.)"""
    src = open(EA_PATH).read()
    # Accept v2.13 OR higher
    import re
    m = re.search(r'#property version\s+"(2\.\d+)"', src)
    assert m, "H2: could not find #property version in EA"
    major, minor = m.group(1).split(".")
    assert int(minor) >= 13, (
        f"H2: EA version regressed below v2.13 (currently {m.group(1)})"
    )


# ============================================================================
# H5 — EA HistorySelect retry pool
# ============================================================================

def test_h5_retry_pool_state_defined():
    """H5: EA must define the retry pool static arrays + counter."""
    src = open(EA_PATH).read()
    assert "FIX_A_RETRY_POOL" in src, "H5: missing FIX_A_RETRY_POOL constant"
    assert "FIX_A_RETRY_MAX_AGE" in src, "H5: missing FIX_A_RETRY_MAX_AGE constant"
    assert "static ulong  g_retryTickets" in src, "H5: missing g_retryTickets array"
    assert "static int    g_retryAge" in src, "H5: missing g_retryAge array"
    assert "static int    g_retryCount" in src, "H5: missing g_retryCount counter"


def test_h5_try_process_helper_extracted():
    """H5: TryProcessLostTicket helper must be defined as a separate function
    (so both diff-path and retry-pool can call it). Old code had this logic
    inline, making it impossible to retry."""
    src = open(EA_PATH).read()
    assert "int TryProcessLostTicket(ulong prevTicket)" in src, (
        "H5: TryProcessLostTicket helper missing"
    )


def test_h5_helper_returns_three_states():
    """H5: helper must return 0 (retry), 1 (resolved), or -1 (skip permanently).
    Caller branches on this to decide retry-pool insertion."""
    src = open(EA_PATH).read()
    # Verify all three return values appear inside TryProcessLostTicket
    helper_start = src.find("int TryProcessLostTicket(ulong prevTicket)")
    helper_end = src.find("\n}\n", helper_start)
    assert helper_start > 0 and helper_end > 0
    helper_body = src[helper_start:helper_end]
    assert "return 0;" in helper_body, "H5: helper must return 0 for retry-needed"
    assert "return 1;" in helper_body, "H5: helper must return 1 for resolved"
    assert "return -1;" in helper_body, "H5: helper must return -1 for permanent-skip"


def test_h5_retry_pool_processed_first():
    """H5: WritePendingOrders must process retry pool BEFORE the diff loop,
    so retried tickets get attention before fresh ones (and don't pile up
    under load)."""
    src = open(EA_PATH).read()
    retry_pool_pos = src.find("// ---- H5 (2026-06-17): retry pool")
    diff_loop_pos  = src.find("// ---- Fix A — detect tickets in prev set")
    assert retry_pool_pos > 0, "H5: retry pool block not found"
    assert diff_loop_pos > 0, "H5: diff loop block not found"
    assert retry_pool_pos < diff_loop_pos, (
        "H5: retry pool must be processed BEFORE the diff loop"
    )


def test_h5_retry_pool_drops_after_max_age():
    """H5: tickets that fail HistoryOrderSelect for FIX_A_RETRY_MAX_AGE ticks
    must be dropped (with Print warn) so the pool doesn't grow unbounded.
    Python Fix B grace fallback handles DB resolution after that."""
    src = open(EA_PATH).read()
    # Verify the retry-exhausted Print line exists
    assert "retry exhausted" in src, (
        "H5: must Print when retry exhausted so ops can spot persistent failures"
    )
    # Verify the age comparison uses the constant (not hardcoded 3)
    assert "retryAge + 1 >= FIX_A_RETRY_MAX_AGE" in src, (
        "H5: age check must use FIX_A_RETRY_MAX_AGE constant, not hardcoded value"
    )


def test_h5_no_duplicate_in_retry_pool():
    """H5: a ticket already in the retry pool that ALSO appears in the diff
    loop's lost set must not be duplicated in newRetryTickets. Otherwise
    the pool fills up with the same ticket twice."""
    src = open(EA_PATH).read()
    assert "alreadyQueued" in src, (
        "H5: must check `alreadyQueued` before adding to retry pool from diff loop"
    )


# ============================================================================
# M5 — EA Fix A overflow warn
# ============================================================================

@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m3_compute_fail_journals_fallback(module_path):
    """M3: when compute_limit_price raises, journal LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET
    so operators see in journal trail (not just _log.exception) that the
    fallback fired."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET" in src, (
        f"M3: {module_path} must journal LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET"
    )
    # Must be inside the except block, before intended_limit = None or after
    fallback_pos = src.find("LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET")
    except_pos = src.find('_log.exception("BROKER", "compute_limit_price_failed"')
    assert except_pos > 0 and fallback_pos > except_pos, (
        f"M3: journal event must follow the _log.exception"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_m2_entry_mode_resolved_logged(module_path):
    """M2: every limit-shipped backend must log resolved entry_mode + boolean
    will_use_limit so typos like 'Limit'/'LIMIT' are observable."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert 'entry_mode_resolved' in src, (
        f"M2: {module_path} must log 'entry_mode_resolved' event"
    )
    assert 'will_use_limit' in src, (
        f"M2: {module_path} must log will_use_limit boolean"
    )
    # Verify it runs BEFORE the if-branch (otherwise can't catch typo path)
    log_pos = src.find("entry_mode_resolved")
    branch_pos = src.find('if cfg_entry_mode == "limit":')
    assert log_pos > 0 and branch_pos > 0
    assert log_pos < branch_pos, (
        f"M2: {module_path} entry_mode_resolved log must come BEFORE the if-branch"
    )


@pytest.mark.parametrize("module_path,expected_prefix", [
    ("backend-oil/scanner/live_engine.py", "OIL"),
    ("backend-micro/scanner/live_engine.py", "MICRO"),
    ("backend-oil-micro/scanner/live_engine.py", "OIL_MICRO"),
])
def test_m7_per_system_dry_run_prefix(module_path, expected_prefix):
    """M7: each backend must call parse_dry_run_env(system_prefix=<correct>)
    so per-system override env vars (OIL_LIMIT_DRY_RUN /
    MICRO_LIMIT_DRY_RUN / OIL_MICRO_LIMIT_DRY_RUN) work for selective rollback."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    expected = f'parse_dry_run_env(system_prefix="{expected_prefix}")'
    assert expected in src, (
        f"M7: {module_path} must call {expected}"
    )


def test_m4_ontradetransaction_dedups_against_cancelled_file():
    """M4: OnTradeTransaction ORDER_DELETE branch must dedup against
    cancelled_orders.json before AppendCancelledOrder. The Fix A poll-path
    has this guard; OnTradeTransaction race could double-write."""
    src = open(EA_PATH).read()
    # Verify dedup logic exists in OnTradeTransaction context
    assert "M4: skipping double-write" in src, (
        "M4: OnTradeTransaction must dedup with M4 marker in Print"
    )
    # Find OnTradeTransaction body
    on_trans_start = src.find("void OnTradeTransaction(")
    append_pos = src.find("AppendCancelledOrder(entry_json)", on_trans_start)
    dedup_pos = src.find("M4: skipping double-write", on_trans_start)
    assert on_trans_start > 0
    assert append_pos > 0
    assert dedup_pos > 0
    assert dedup_pos < append_pos, (
        "M4: dedup guard must run BEFORE AppendCancelledOrder in OnTradeTransaction"
    )


def test_m5_overflow_warn_present():
    """M5: when pending count > FIX_A_MAX_PENDING, EA must Print a warn.
    Otherwise silent diff-truncation hides lost-ticket detection failures."""
    src = open(EA_PATH).read()
    assert "M5 pending count" in src, (
        "M5: must Print 'M5 pending count ... > FIX_A_MAX_PENDING' on overflow"
    )
    # Verify it's in the WritePendingOrders block (not retry pool)
    write_pending_pos = src.find("void WritePendingOrders()")
    overflow_warn_pos = src.find("M5 pending count")
    assert write_pending_pos > 0 and overflow_warn_pos > write_pending_pos, (
        "M5: overflow warn must live inside WritePendingOrders"
    )


# ============================================================================
# O3 — Daily recon must surface Filter #27 lifecycle counters
# ============================================================================

def test_o3_daily_recon_stats_returns_filter27_keys():
    """daily_recon_stats must return 5 new Filter #27 keys."""
    src = open(os.path.join(PROJECT_ROOT, "backend", "db.py")).read()
    expected_keys = [
        '"limit_placed"',
        '"limit_filled"',
        '"limit_ttl_expired"',
        '"limit_orphan"',
        '"limit_bad_open_price"',
    ]
    for key in expected_keys:
        assert key in src, (
            f"O3: backend/db.py daily_recon_stats must include {key} in return dict"
        )
    # Each key must use count_event() with the matching journal event_type
    expected_event_types = [
        '"LIMIT_PLACED"',
        '"LIMIT_FILLED"',
        '"LIMIT_TTL_EXPIRED"',
        '"LIMIT_ORPHAN"',
        '"LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED"',
    ]
    for evt in expected_event_types:
        assert f"count_event({evt})" in src, (
            f"O3: daily_recon_stats must call count_event({evt})"
        )


def test_o3_notify_daily_recon_signature_extended():
    """notify.daily_recon must accept the 5 new kwargs with default=0
    (backward-compatible — old callers pass through **stats unchanged)."""
    import inspect
    sys.path.insert(0, PROJECT_ROOT)
    import importlib
    from backend import notify as _notify
    importlib.reload(_notify)
    sig = inspect.signature(_notify.daily_recon)
    params = sig.parameters
    expected_kwargs = ["limit_placed", "limit_filled", "limit_ttl_expired",
                       "limit_orphan", "limit_bad_open_price"]
    for kw in expected_kwargs:
        assert kw in params, f"O3: notify.daily_recon must accept {kw} kwarg"
        assert params[kw].default == 0, (
            f"O3: {kw} default must be 0 for backward compat"
        )


def test_o3_notify_renders_filter27_line_when_active():
    """When limit_placed/filled/expired > 0, message body must contain a
    Filter #27 line with placed/filled/expired counts + fill_rate %."""
    import importlib
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify as _notify
    importlib.reload(_notify)

    sent = []
    original_send = _notify.send
    _notify.send = lambda msg: sent.append(msg)
    try:
        _notify.daily_recon(
            "Oil Macro", "2026-06-17",
            total_trades=4, orphans_adopted=0, db_insert_failed=0,
            journal_errors=0, net_pnl=-160.32, exit_ambiguous=0,
            limit_placed=10, limit_filled=4, limit_ttl_expired=6,
            limit_orphan=0, limit_bad_open_price=0,
        )
    finally:
        _notify.send = original_send

    assert len(sent) == 1
    msg = sent[0]
    assert "Filter #27" in msg, (
        "O3: when limit events occurred, msg must include Filter #27 line"
    )
    assert "placed=10" in msg
    assert "filled=4" in msg
    assert "expired=6" in msg
    assert "40%" in msg, "O3: fill rate (4/10 = 40%) must render"


def test_o3_notify_omits_filter27_line_when_idle():
    """When NO limit events occurred (e.g. Gold Macro day), the Filter #27
    line should be omitted to keep the message compact."""
    import importlib
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify as _notify
    importlib.reload(_notify)

    sent = []
    original_send = _notify.send
    _notify.send = lambda msg: sent.append(msg)
    try:
        _notify.daily_recon(
            "Gold Macro", "2026-06-17",
            total_trades=2, orphans_adopted=0, db_insert_failed=0,
            journal_errors=0, net_pnl=295.51, exit_ambiguous=0,
        )  # NO limit_* kwargs — should default to 0
    finally:
        _notify.send = original_send

    assert len(sent) == 1
    msg = sent[0]
    assert "Filter #27" not in msg, (
        "O3: when 0 limit events, msg should NOT include Filter #27 line"
    )


# ============================================================================
# O4 — time_to_fill computation in LIMIT_FILLED journal context
# ============================================================================

def test_o4_compute_time_to_fill_helper_exists():
    """The helper must live in backend/execution/mt5_executor.py and have a
    documented signature."""
    import inspect
    sys.path.insert(0, PROJECT_ROOT)
    from backend.execution import mt5_executor
    assert hasattr(mt5_executor, "compute_time_to_fill"), (
        "O4: backend/execution/mt5_executor.py must expose compute_time_to_fill"
    )
    sig = inspect.signature(mt5_executor.compute_time_to_fill)
    params = sig.parameters
    assert "placement_dt" in params
    assert "broker_open_time_str" in params


def test_o4_compute_time_to_fill_seconds():
    from datetime import datetime, timezone
    sys.path.insert(0, PROJECT_ROOT)
    from backend.execution.mt5_executor import compute_time_to_fill
    # Placement: 2026-06-17 14:42:00 UTC
    placement = datetime(2026, 6, 17, 14, 42, 0, tzinfo=timezone.utc)
    # Broker fill: 17:42:45 GMT+3 server time = 14:42:45 UTC = 45s after placement
    assert compute_time_to_fill(placement, "2026.06.17 17:42:45") == "45s"


def test_o4_compute_time_to_fill_minutes():
    from datetime import datetime, timezone
    sys.path.insert(0, PROJECT_ROOT)
    from backend.execution.mt5_executor import compute_time_to_fill
    placement = datetime(2026, 6, 17, 14, 42, 0, tzinfo=timezone.utc)
    # 17:49:12 GMT+3 = 14:49:12 UTC = 7m12s
    assert compute_time_to_fill(placement, "2026.06.17 17:49:12") == "7m12s"
    # Round number: 17:56:00 = 14m
    assert compute_time_to_fill(placement, "2026.06.17 17:56:00") == "14m"


def test_o4_compute_time_to_fill_unknown_inputs():
    from datetime import datetime, timezone
    sys.path.insert(0, PROJECT_ROOT)
    from backend.execution.mt5_executor import compute_time_to_fill
    placement = datetime(2026, 6, 17, 14, 42, 0, tzinfo=timezone.utc)
    # Empty string
    assert compute_time_to_fill(placement, "") == "unknown"
    # Malformed broker time
    assert compute_time_to_fill(placement, "garbage") == "unknown"
    # None placement
    assert compute_time_to_fill(None, "2026.06.17 17:43:00") == "unknown"


def test_o4_compute_time_to_fill_negative_clock_skew():
    """Broker timestamp BEFORE placement = clock skew. Surface explicitly,
    don't silently render '-3m'."""
    from datetime import datetime, timezone
    sys.path.insert(0, PROJECT_ROOT)
    from backend.execution.mt5_executor import compute_time_to_fill
    placement = datetime(2026, 6, 17, 14, 42, 0, tzinfo=timezone.utc)
    # 17:41:00 GMT+3 = 14:41:00 UTC = 60s BEFORE placement
    result = compute_time_to_fill(placement, "2026.06.17 17:41:00")
    assert result.startswith("negative"), (
        f"O4: backwards-time fill must return 'negative(...)' marker; got {result!r}"
    )


def test_o4_compute_time_to_fill_naive_placement_assumed_utc():
    """If placement_dt has no tzinfo, helper must assume UTC, not crash."""
    from datetime import datetime
    sys.path.insert(0, PROJECT_ROOT)
    from backend.execution.mt5_executor import compute_time_to_fill
    placement_naive = datetime(2026, 6, 17, 14, 42, 0)  # NO tzinfo
    result = compute_time_to_fill(placement_naive, "2026.06.17 17:42:30")
    assert result == "30s"


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_o4_backend_calls_compute_time_to_fill(module_path):
    """Each limit-shipped backend's pending_order_monitor must call
    compute_time_to_fill in the fill-detection branch."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "compute_time_to_fill" in src, (
        f"O4: {module_path} must call compute_time_to_fill in fill branch"
    )
    # Also assert it's used in the LIMIT_FILLED journal context (not just imported)
    fill_idx = src.find("LIMIT_FILLED")
    assert fill_idx > 0
    block = src[max(0, fill_idx - 600):fill_idx + 600]
    assert "compute_time_to_fill" in block, (
        f"O4: {module_path} compute_time_to_fill must be near LIMIT_FILLED journal block"
    )


@pytest.mark.parametrize("module_path", LIMIT_BACKENDS)
def test_o4_journal_context_has_time_to_fill_key(module_path):
    """LIMIT_FILLED journal context dict must include time_to_fill."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    fill_idx = src.find('"LIMIT_FILLED"')
    assert fill_idx > 0, f"{module_path}: LIMIT_FILLED marker not found"
    # Look forward 600 chars for the context dict
    block = src[fill_idx:fill_idx + 600]
    assert '"time_to_fill"' in block, (
        f"O4: {module_path} LIMIT_FILLED journal context must include time_to_fill key"
    )


# ============================================================================
# O1 — Dashboard pending vs live mode badge
# Backend: state.py + stream.py must SELECT mode and surface in db_positions JSON.
# Frontend: live page must render a "PENDING" badge for mode === "pending" rows.
# ============================================================================

# All 4 systems' state.py must surface mode in db_positions
ALL_STATE_FILES = [
    "backend/routes/state.py",
    "backend-oil/routes/state.py",
    "backend-micro/routes/state.py",
    "backend-oil-micro/routes/state.py",
]


@pytest.mark.parametrize("module_path", ALL_STATE_FILES)
def test_o1_state_surfaces_mode_in_db_positions(module_path):
    """The state JSON's db_positions array must include `mode` per row.
    For limit-shipped backends, comes from SQL COALESCE(mode, 'live').
    For Gold Macro, fallback to t.get('mode') or 'live' (default 'live').
    """
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # The db_positions list comprehension or append must include "mode" key
    assert '"mode"' in src, (
        f"O1: {module_path} db_positions must include 'mode' key in JSON output"
    )


# Limit-shipped state.py + stream.py must SELECT mode from SQL
LIMIT_ROUTE_FILES = [
    "backend-oil/routes/state.py",
    "backend-oil/routes/stream.py",
    "backend-micro/routes/state.py",
    "backend-oil-micro/routes/state.py",
]


@pytest.mark.parametrize("module_path", LIMIT_ROUTE_FILES)
def test_o1_state_sql_selects_mode(module_path):
    """SQL query for db_positions must SELECT COALESCE(mode, 'live').
    Without the SELECT, p['mode'] would KeyError when serializing."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "COALESCE(mode, 'live')" in src, (
        f"O1: {module_path} SQL must SELECT COALESCE(mode, 'live') AS mode "
        f"so the row dict has the field"
    )


def test_o1_frontend_live_page_renders_pending_badge():
    """Live page must render a 'PENDING' badge for rows where mode === 'pending'."""
    full = os.path.join(PROJECT_ROOT, "frontend", "app", "live", "page.tsx")
    src = open(full).read()
    # TS interface must declare mode field (optional for back-compat)
    assert "mode?: string" in src or "mode: string" in src, (
        "O1: frontend/app/live/page.tsx db_positions interface must include mode field"
    )
    # The PENDING badge text must appear
    assert "PENDING" in src, (
        "O1: live page must render 'PENDING' label for pending rows"
    )
    # Conditional render based on mode === 'pending'
    assert 'mode === "pending"' in src or "mode === 'pending'" in src, (
        "O1: live page must conditionally render badge based on mode === 'pending'"
    )


def test_o1_frontend_dim_pending_rows():
    """Pending rows should be visually de-emphasized (e.g. opacity-60) so they
    don't look like real positions."""
    full = os.path.join(PROJECT_ROOT, "frontend", "app", "live", "page.tsx")
    src = open(full).read()
    # Some opacity / muted styling tied to isPending
    assert "isPending" in src, (
        "O1: live page must compute isPending boolean for visual styling"
    )
    assert "opacity-60" in src or "opacity-50" in src or "muted" in src.lower(), (
        "O1: pending rows should be visually de-emphasized via opacity"
    )


# ============================================================================
# O2 — Trades page mode column + exit reason filter
# ============================================================================

# All 4 systems' trades.py must serialize 'mode' field
ALL_TRADES_FILES = [
    "backend/routes/trades.py",
    "backend-oil/routes/trades.py",
    "backend-micro/routes/trades.py",
    "backend-oil-micro/routes/trades.py",
]


@pytest.mark.parametrize("module_path", ALL_TRADES_FILES)
def test_o2_trades_api_serializes_mode(module_path):
    """The /api/<system>/trades response must include 'mode' field per row."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert '"mode"' in src, (
        f"O2: {module_path} /trades response must serialize 'mode' per row"
    )


def test_o2_frontend_trades_page_has_mode_column():
    """Trades table must render a Mode column with PENDING badge for pending."""
    full = os.path.join(PROJECT_ROOT, "frontend", "app", "trades", "page.tsx")
    src = open(full).read()
    # TS interface declares mode field
    assert "mode: string" in src or "mode?: string" in src, (
        "O2: LiveTrade interface must include mode field"
    )
    # Mode column registered in the live cols definition (key: 'mode')
    assert 'key: "mode"' in src or "key: 'mode'" in src, (
        "O2: liveCols must include a key='mode' column entry"
    )
    # Render PENDING label conditional on mode === 'pending'
    assert "PENDING" in src, (
        "O2: trades page must render 'PENDING' label for pending rows"
    )
    assert 'mode === "pending"' in src or "mode === 'pending'" in src, (
        "O2: PENDING badge must conditionally render based on mode === 'pending'"
    )


def test_o2_frontend_trades_page_has_exit_reason_filter():
    """A filter dropdown must let user filter by Filter #27 lifecycle exit reasons."""
    full = os.path.join(PROJECT_ROOT, "frontend", "app", "trades", "page.tsx")
    src = open(full).read()
    # filter state holds exitReason
    assert "exitReason" in src, (
        "O2: filter state must include exitReason for client-side filtering"
    )
    # dropdown options include the F27 lifecycle exit reasons
    assert "LIMIT_TTL_EXPIRED" in src, (
        "O2: filter dropdown must include LIMIT_TTL_EXPIRED option"
    )
    assert "LIMIT_TTL_EXPIRED_GRACE" in src, (
        "O2: filter dropdown must include LIMIT_TTL_EXPIRED_GRACE option (Fix B distinction)"
    )
    assert "LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED" in src, (
        "O2: filter dropdown must include LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED option (M13)"
    )


def test_o2_frontend_trades_page_filter_applied_client_side():
    """When exitReason is set, liveTrades is filtered before passing to the table."""
    full = os.path.join(PROJECT_ROOT, "frontend", "app", "trades", "page.tsx")
    src = open(full).read()
    # The filter chain: liveTrades.filter((t) => t.exit_reason === filter.exitReason)
    assert "filter.exitReason" in src, (
        "O2: rendered rows must depend on filter.exitReason"
    )
    assert "exit_reason === filter.exitReason" in src or \
           "filter((t) =>" in src or \
           "filter.exitReason" in src, (
        "O2: liveTrades must be filtered before passing to <Table />"
    )


def test_o3_orphan_and_bad_open_price_appear_in_status_flags():
    """Non-zero limit_orphan or limit_bad_open_price counts must surface in
    the Status: line as a flag (operator's eye-catching signal)."""
    import importlib
    sys.path.insert(0, PROJECT_ROOT)
    from backend import notify as _notify
    importlib.reload(_notify)

    sent = []
    original_send = _notify.send
    _notify.send = lambda msg: sent.append(msg)
    try:
        _notify.daily_recon(
            "Oil Micro", "2026-06-17",
            total_trades=8, orphans_adopted=0, db_insert_failed=0,
            journal_errors=0, net_pnl=120.0, exit_ambiguous=0,
            limit_placed=10, limit_filled=8, limit_ttl_expired=2,
            limit_orphan=2, limit_bad_open_price=1,
        )
    finally:
        _notify.send = original_send

    msg = sent[0]
    assert "limit-orphans" in msg, (
        "O3: limit_orphan>0 must appear in Status: flags"
    )
    assert "bad-open-price" in msg, (
        "O3: limit_bad_open_price>0 must appear in Status: flags"
    )
    # And clean status not used
    assert "✅ clean" not in msg, (
        "O3: status must not say 'clean' when red flags exist"
    )
