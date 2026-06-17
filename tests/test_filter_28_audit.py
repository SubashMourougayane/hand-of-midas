"""Tests for F28 audit backlog items.

Mirrors tests/test_filter_27_pending_monitor.py's structure: structural tests
across all 4 systems + runtime tests for behavior. Items added per audit doc
docs/FILTER_28_AUDIT_BACKLOG.md.
"""
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# Per-system path constants
# ============================================================================

# All 4 systems' state.py route files
ALL_STATE_FILES = [
    "backend/routes/state.py",
    "backend-oil/routes/state.py",
    "backend-micro/routes/state.py",
    "backend-oil-micro/routes/state.py",
]

# Macro systems have their own SSE stream code (not delegating to state.py:get_state)
MACRO_STREAM_FILES = [
    "backend/routes/stream.py",       # Gold Macro
    "backend-oil/routes/stream.py",   # Oil Macro
]

# Micro systems delegate stream.py → state.py:get_state, so bias_mode comes for free
MICRO_STREAM_FILES = [
    "backend-micro/routes/stream.py",      # Gold Micro
    "backend-oil-micro/routes/stream.py",  # Oil Micro
]

# All 4 schedulers (where F28 override block lives)
ALL_SCHEDULER_FILES = [
    "backend/scanner/scheduler.py",       # Gold Macro
    "backend-micro/scanner/scheduler.py", # Gold Micro
    "backend-oil/scanner/scheduler.py",   # Oil Macro
    "backend-oil-micro/scanner/scheduler.py",  # Oil Micro
]

# All 4 configs
ALL_CONFIG_FILES = [
    "backend/config.py",
    "backend-micro/config.py",
    "backend-oil/config.py",
    "backend-oil-micro/config.py",
]


# ============================================================================
# F28-C1 — Stream endpoints surface bias_mode (Macro fix; Micro inherits via state.py)
# ============================================================================


@pytest.mark.parametrize("module_path", MACRO_STREAM_FILES)
def test_c1_macro_stream_includes_bias_mode_in_return_dict(module_path):
    """Gold Macro and Oil Macro have their own _build_state() that the SSE
    stream payload comes from. F28 Phase 3 patched routes/state.py but missed
    these two parallel implementations — frontend badge would never appear.
    Fix: add `"bias_mode": _get_bias_mode_safe()` to each return dict.
    """
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # The return dict must include bias_mode key
    assert '"bias_mode"' in src, (
        f"F28-C1: {module_path} stream return dict must include 'bias_mode' "
        f"so frontend SSE-driven F28 badge can render"
    )


@pytest.mark.parametrize("module_path", MACRO_STREAM_FILES)
def test_c1_macro_stream_has_get_bias_mode_safe_helper(module_path):
    """Each Macro stream.py defines _get_bias_mode_safe() helper that wraps
    the config import in try/except — so the SSE stream never breaks if
    config can't be imported."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "_get_bias_mode_safe" in src, (
        f"F28-C1: {module_path} must define _get_bias_mode_safe() helper "
        f"to wrap BIAS_MODE config read defensively"
    )
    # Helper must default to "production" on import failure (not raise)
    helper_block_start = src.find("def _get_bias_mode_safe")
    assert helper_block_start > 0
    helper_block = src[helper_block_start:helper_block_start + 400]
    assert "production" in helper_block, (
        f"F28-C1: {module_path} _get_bias_mode_safe must default to "
        f"'production' on any error"
    )


@pytest.mark.parametrize("module_path", MICRO_STREAM_FILES)
def test_c1_micro_stream_delegates_to_state_get_state(module_path):
    """Gold Micro and Oil Micro stream.py CORRECTLY delegate to state.py:
    get_state() — so bias_mode comes for free from state.py's patch.
    This test guards against future regressions where someone duplicates
    the build-state logic into the micro stream.py (which would then need
    its own bias_mode fix).
    """
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "from routes.state import get_state" in src or \
           "from routes.state import" in src and "get_state" in src, (
        f"F28-C1: {module_path} should delegate to routes.state:get_state "
        f"so it inherits bias_mode automatically. If you change this, you "
        f"MUST add explicit bias_mode handling like the Macro stream files."
    )


@pytest.mark.parametrize("module_path", ALL_STATE_FILES)
def test_c1_state_includes_bias_mode_in_return_dict(module_path):
    """All 4 systems' state.py /state endpoints include bias_mode (this was
    Phase 3 Step 5; verifies regression hasn't occurred)."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert '"bias_mode"' in src, (
        f"F28-C1: {module_path} /state endpoint must include bias_mode"
    )
    assert "_get_bias_mode_safe" in src, (
        f"F28-C1: {module_path} must define _get_bias_mode_safe() helper"
    )


# ============================================================================
# F28-H1 — parse_bias_mode_env helper (whitespace / case / typo safety)
# ============================================================================


def test_h1_parse_bias_mode_env_helper_exists():
    """The helper must be importable from backend.backtest.neutral_bias."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    assert callable(parse_bias_mode_env)


def test_h1_parse_handles_trailing_whitespace(monkeypatch):
    """Trailing-space copy-paste hazard — was the bug. 'neutral ' must
    normalize to 'neutral', not silently fall back to 'production'."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    monkeypatch.setenv("F28_TEST_VAR", "neutral ")
    assert parse_bias_mode_env("F28_TEST_VAR", "production") == "neutral"


def test_h1_parse_handles_leading_whitespace(monkeypatch):
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    monkeypatch.setenv("F28_TEST_VAR", " neutral")
    assert parse_bias_mode_env("F28_TEST_VAR", "production") == "neutral"


@pytest.mark.parametrize("raw_value,expected", [
    ("neutral", "neutral"),
    ("NEUTRAL", "neutral"),
    ("Neutral", "neutral"),
    ("nEuTrAl", "neutral"),
    ("production", "production"),
    ("PRODUCTION", "production"),
    ("Production", "production"),
])
def test_h1_parse_handles_case_variants(raw_value, expected, monkeypatch):
    """Case-insensitive matching via .lower() normalization."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    monkeypatch.setenv("F28_TEST_VAR", raw_value)
    assert parse_bias_mode_env("F28_TEST_VAR", "production") == expected


def test_h1_parse_typo_falls_back_to_default(monkeypatch, caplog):
    """Typo 'neutrol' must NOT silently fall through to neutral; must warn
    + return default."""
    import logging
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    monkeypatch.setenv("F28_TEST_VAR", "neutrol")
    with caplog.at_level(logging.WARNING):
        result = parse_bias_mode_env("F28_TEST_VAR", "production")
    assert result == "production"
    # Loud warning emitted
    assert any("F28-H1" in rec.message for rec in caplog.records), (
        f"F28-H1: typo must trigger WARNING-level log; caplog records: "
        f"{[rec.message for rec in caplog.records]}"
    )


def test_h1_parse_unrelated_string_falls_back(monkeypatch):
    """Garbage value like 'true' or '1' (legit for boolean kwargs but not
    here) must fall back to default with warning, not silently activate
    neutral."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    for bad in ("1", "0", "true", "false", "yes", "no", "on", "off"):
        monkeypatch.setenv("F28_TEST_VAR", bad)
        result = parse_bias_mode_env("F28_TEST_VAR", "production")
        assert result == "production", (
            f"F28-H1: bad value {bad!r} must fall back to production"
        )


def test_h1_parse_empty_string_uses_default(monkeypatch):
    """Empty value (e.g. user sets `GOLD_MACRO_BIAS_MODE=` with nothing
    after) treated as 'use default' rather than raising."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    monkeypatch.setenv("F28_TEST_VAR", "")
    assert parse_bias_mode_env("F28_TEST_VAR", "production") == "production"
    monkeypatch.setenv("F28_TEST_VAR", "   ")  # whitespace-only
    assert parse_bias_mode_env("F28_TEST_VAR", "production") == "production"


def test_h1_parse_unset_var_uses_default(monkeypatch):
    """Env var not set at all → return default."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    monkeypatch.delenv("F28_TEST_VAR", raising=False)
    assert parse_bias_mode_env("F28_TEST_VAR", "production") == "production"


def test_h1_parse_invalid_default_raises():
    """Function-author guard: caller must pass a valid default. Catches
    typos like default='Production' or default=None during refactors."""
    sys.path.insert(0, PROJECT_ROOT)
    from backend.backtest.neutral_bias import parse_bias_mode_env
    with pytest.raises(ValueError, match="default must be one of"):
        parse_bias_mode_env("F28_TEST_VAR", default="Production")  # capitalized — bug
    with pytest.raises(ValueError):
        parse_bias_mode_env("F28_TEST_VAR", default="bullish")


@pytest.mark.parametrize("module_path", ALL_CONFIG_FILES)
def test_h1_all_configs_use_parse_bias_mode_env(module_path):
    """STRUCTURAL: every config.py must use parse_bias_mode_env helper —
    not raw os.getenv. Catches future regressions where someone reverts
    to the unsafe pattern."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "parse_bias_mode_env" in src, (
        f"F28-H1: {module_path} must use parse_bias_mode_env helper, not "
        f"raw os.getenv (whitespace/case-fragile)"
    )
    # Negative check: no raw `os.getenv("..._BIAS_MODE", ...)` patterns left
    bias_var_patterns = [
        r'os\.getenv\(\s*["\']\w+_BIAS_MODE["\']',
    ]
    for pat in bias_var_patterns:
        m = re.search(pat, src)
        assert m is None, (
            f"F28-H1: {module_path} has raw os.getenv for *_BIAS_MODE — "
            f"must use parse_bias_mode_env. Match: {m.group(0) if m else None}"
        )


# ============================================================================
# F28-H2 — _log_journal → _log_journal_safe in 4 scheduler F28 override blocks
# ============================================================================


@pytest.mark.parametrize("module_path", ALL_SCHEDULER_FILES)
def test_h2_f28_block_uses_log_journal_safe_not_log_journal(module_path):
    """F28 override block emits journal event on every scan tick. If it
    uses _log_journal (raises on DB blip), the outer try/except in
    position_monitor_job aborts the entire scan tick — F28 introduces a
    new failure mode for the observability event. Must use _log_journal_safe
    (swallows exceptions) instead."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    # Locate the F28 override block by finding F28_BIAS_RESOLVED
    f28_idx = src.find('"F28_BIAS_RESOLVED"')
    assert f28_idx > 0, f"F28-H2: {module_path} missing F28_BIAS_RESOLVED journal event"
    # Look BACKWARDS up to ~500 chars for the journal call name
    look_back = src[max(0, f28_idx - 500):f28_idx]
    # Find the most-recent journal call before F28_BIAS_RESOLVED
    last_safe = look_back.rfind("_log_journal_safe")
    last_unsafe_match = re.findall(r"\b_log_journal\(", look_back)
    last_unsafe = look_back.rfind("_log_journal(")  # the unsafe variant
    # Note: '_log_journal_safe' contains '_log_journal' as substring; use word-boundary regex
    # Easiest: assert the IMMEDIATELY-PRECEDING call is _log_journal_safe(
    # by checking that "_log_journal_safe(" appears closer to F28_BIAS_RESOLVED than "_log_journal(" does
    # (where _log_journal( means strictly the unsafe variant — not _log_journal_safe).
    # Use regex: \b_log_journal\( (with word boundary before)
    safe_matches = [m.start() for m in re.finditer(r"_log_journal_safe\(", look_back)]
    # Unsafe = _log_journal( with NOT _safe before the (
    unsafe_matches = [m.start() for m in re.finditer(r"_log_journal\((?!.*_safe)", look_back)]
    # Filter unsafe to those NOT followed by 'safe(' — easier: use negative lookahead
    # Simpler: find positions of "_log_journal(" and "_log_journal_safe(" separately
    journal_unsafe_positions = []
    for m in re.finditer(r"_log_journal\(", look_back):
        # Check this isn't actually _log_journal_safe (would be position - 5 chars before)
        before = look_back[max(0, m.start()-5):m.start()]
        if not before.endswith("_safe"):
            # But wait — _log_journal( with _safe behind would mean _log_journal_safe(
            # which we want to EXCLUDE. m.start() points to "_log_journal(" — if literal
            # text immediately preceding m.start() is "" then m matches the unsafe variant;
            # if preceding is "_safe" then m matches the END of _log_journal_safe( and we skip.
            journal_unsafe_positions.append(m.start())

    if journal_unsafe_positions:
        # The most recent unsafe call before F28_BIAS_RESOLVED
        last_unsafe_pos = max(journal_unsafe_positions)
        last_safe_pos = max(safe_matches) if safe_matches else -1
        if last_unsafe_pos > last_safe_pos:
            assert False, (
                f"F28-H2: {module_path} F28_BIAS_RESOLVED preceded by "
                f"_log_journal( (raises on DB blip). Must be _log_journal_safe(. "
                f"Look-back: {look_back[max(0, last_unsafe_pos-50):last_unsafe_pos+30]!r}"
            )

    # Positive assertion: _log_journal_safe MUST appear within the look-back window
    assert "_log_journal_safe" in look_back, (
        f"F28-H2: {module_path} F28_BIAS_RESOLVED block must use "
        f"_log_journal_safe immediately before — none found in look-back."
    )


@pytest.mark.parametrize("module_path", ALL_SCHEDULER_FILES)
def test_h2_log_journal_safe_imported(module_path):
    """All 4 schedulers must import _log_journal_safe (otherwise the H2 fix
    references undefined name)."""
    full = os.path.join(PROJECT_ROOT, module_path)
    src = open(full).read()
    assert "_log_journal_safe" in src, (
        f"F28-H2: {module_path} must import _log_journal_safe"
    )


# ============================================================================
# F28-H3 — Parity harness F28-aware
# ============================================================================


def test_h3_parity_runner_has_resolve_system_bias_mode_helper():
    """Parity runner.py must define _resolve_system_bias_mode() to read
    the system's live BIAS_MODE config (so the harness mirrors live state)."""
    full = os.path.join(PROJECT_ROOT, "tests/harness/parity/runner.py")
    src = open(full).read()
    assert "_resolve_system_bias_mode" in src, (
        "F28-H3: parity runner.py must define _resolve_system_bias_mode helper"
    )
    # Must default to "production" on any error (harness must not break on
    # F28 config issues — parity check itself surfaces drift)
    helper_block_start = src.find("def _resolve_system_bias_mode")
    assert helper_block_start > 0
    helper_block = src[helper_block_start:helper_block_start + 1000]
    assert "production" in helper_block, (
        "F28-H3: helper must default to 'production' on import error"
    )
    assert "except" in helper_block, (
        "F28-H3: helper must wrap config import in try/except"
    )


def test_h3_parity_runner_swaps_daily_bias_when_neutral():
    """STRUCTURAL: parity runner.py must check the resolved bias mode and,
    when 'neutral', swap daily_bias for NeutralBiasDict before passing to
    extractors. Otherwise BT side blocks signals that live fires → false
    drift on every run."""
    full = os.path.join(PROJECT_ROOT, "tests/harness/parity/runner.py")
    src = open(full).read()
    # Look for the check + swap pattern
    assert "bias_mode == \"neutral\"" in src or "bias_mode == 'neutral'" in src, (
        "F28-H3: runner.py must conditionally swap daily_bias when bias_mode=neutral"
    )
    assert "NeutralBiasDict" in src, (
        "F28-H3: runner.py must reference NeutralBiasDict for the swap"
    )
    # Find the swap block and verify it's BEFORE extract_backtest_signals call
    swap_idx = src.find("daily_bias = NeutralBiasDict()")
    bt_call_idx = src.find("extract_backtest_signals(")
    assert swap_idx > 0, "F28-H3: must assign daily_bias = NeutralBiasDict() in neutral path"
    assert bt_call_idx > 0
    assert swap_idx < bt_call_idx, (
        "F28-H3: NeutralBiasDict swap must happen BEFORE extract_backtest_signals "
        f"(swap_idx={swap_idx}, bt_call_idx={bt_call_idx})"
    )


def test_h3_parity_runner_handles_neutral_bias_import_failure_gracefully():
    """If NeutralBiasDict can't be imported (older branch / missing module),
    runner must NOT crash — print warning and fall back to V1+V2."""
    full = os.path.join(PROJECT_ROOT, "tests/harness/parity/runner.py")
    src = open(full).read()
    # Find the F28 mirror block
    f28_block_start = src.find("F28-H3 — bias-mode mirroring")
    assert f28_block_start > 0
    f28_block = src[f28_block_start:f28_block_start + 1500]
    # Must wrap NeutralBiasDict import in try/except ImportError
    assert "ImportError" in f28_block, (
        "F28-H3: NeutralBiasDict import must be wrapped in try/except ImportError "
        "so harness doesn't crash on older branches without the module"
    )
    # Must log warning if import fails
    assert "WARNING" in f28_block or "warning" in f28_block, (
        "F28-H3: ImportError fallback must log a warning"
    )


def test_h3_parity_harness_full_suite_still_passes():
    """RUNTIME: parity harness must still pass after F28-H3 changes.
    Catches any breaking refactor."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/harness/test_22_parity.py", "--tb=short"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # The parity harness has pre-existing soft warnings (60-77% baseline).
    # We just need exit code 0 — no test failures.
    assert result.returncode == 0, (
        f"F28-H3: parity harness must still pass.\n"
        f"stdout: {result.stdout[-2000:]}\n"
        f"stderr: {result.stderr[-1000:]}"
    )
