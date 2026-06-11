"""TEST 21: Scheduler import/usage parity across systems.

Regression guard for commit cd7c843 (June 10 2026): Gold Micro's
backend-micro/scanner/scheduler.py called get_open_trades() at line ~307
but did not import it. Every scan cycle from June 6 (origin commit
b6bfced) to June 10 (fix cd7c843) silently crashed with NameError —
swallowed by the outer try/except at line ~124. Production journal
showed 100/100 most recent events as ERROR with that NameError.

This test enforces the invariant: any name a scheduler module CALLS at
runtime must also be IMPORTED at module load time. We check this for
the specific call sites that matter (cross-system orphan check via
get_open_trades) without binding the test to text-by-line specifics
that refactors would break.

Static source check, ~5 ms total runtime, no DB or network deps.
"""
import sys
import os
import re
import ast
import importlib.util
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)


def _module_imports(path: str) -> set[str]:
    """Return the set of bare names imported at module top level.

    Examples:
      'from x import a, b'   -> {'a', 'b'}
      'from x import a as A' -> {'A'}
      'import x.y'           -> {'x'}   (not 'x.y' — bare-name lookup)
      'import x as X'        -> {'X'}
    """
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
    return imported


def _module_calls(path: str) -> set[str]:
    """Return the set of bare-name function calls at module level (i.e.
    names called as `f(...)` not `obj.f(...)`).

    We intentionally restrict to bare-name calls because attribute calls
    look up the attribute on the parent (e.g. `os.path.join` only needs
    `os` to be in scope). The bug class this test guards is missing
    bare-name imports.
    """
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
    return called


# ----------------------------------------------------------------------
# Per-system contract: which executor names a scheduler must import
# IF it calls them. Macro schedulers don't call get_open_trades at all
# (only their live_engine does), so we don't require it for them.
# ----------------------------------------------------------------------

# Specific regression for cd7c843 — Gold Micro and Oil Micro schedulers
# both reach into MT5 directly via get_open_trades() to cross-check
# orphan positions. Both must import what they call.
REQUIRED_IF_CALLED = {
    "get_open_trades",
    "get_account_summary",
    "get_current_price",
    "get_candles",
}


@pytest.mark.parametrize("module_path", [
    "backend/scanner/scheduler.py",
    "backend-oil/scanner/scheduler.py",
    "backend-micro/scanner/scheduler.py",
    "backend-oil-micro/scanner/scheduler.py",
])
def test_scheduler_calls_match_imports(module_path):
    """If the scheduler CALLS one of the executor functions as a bare
    name, it must IMPORT it at module top level. Catches the cd7c843
    bug class (call added but import not updated)."""
    full_path = os.path.join(PROJECT_ROOT, module_path)
    assert os.path.exists(full_path), f"Source file missing: {module_path}"

    imported = _module_imports(full_path)
    called = _module_calls(full_path)

    missing = []
    for name in REQUIRED_IF_CALLED:
        if name in called and name not in imported:
            missing.append(name)

    assert not missing, (
        f"{module_path} calls {missing} as bare name(s) but does not import them. "
        f"This recreates the cd7c843 bug class — runtime NameError on scan.\n"
        f"  Imported (bare names): {sorted(imported)[:20]}...\n"
        f"  Called (bare names):   {sorted(called)[:30]}..."
    )


@pytest.mark.parametrize("module_path", [
    "backend-micro/scanner/scheduler.py",
    "backend-oil-micro/scanner/scheduler.py",
])
def test_micro_scheduler_imports_get_open_trades(module_path):
    """Specific lock-in for the cd7c843 fix: Micro schedulers MUST import
    get_open_trades because they cross-check MT5 directly to catch
    orphans within their 3-min scan cycle (Macro schedulers do this only
    in live_engine, on a slower cadence)."""
    full_path = os.path.join(PROJECT_ROOT, module_path)
    imported = _module_imports(full_path)
    assert "get_open_trades" in imported, (
        f"{module_path} must import get_open_trades (it cross-checks MT5 "
        f"open positions inline — see the call site at scheduler.py "
        f"line ~307 for Gold Micro / ~269 for Oil Micro). "
        f"Without this import, every sweep that survives the DB-empty "
        f"check will silently NameError. See commit cd7c843."
    )


# Note: a runtime smoke-load test (importlib.util.spec_from_file_location +
# exec_module) was intentionally NOT added here. Each per-system scheduler
# does `from config import ...`, which resolves through sys.path. Earlier
# tests in the suite (test_14_oil_micro, test_15_oil_macro) import sibling
# config.py modules into sys.modules['config'], so a load-by-spec smoke
# test fails non-deterministically depending on test order. The two AST
# checks above give the same coverage without the cross-test fragility.
