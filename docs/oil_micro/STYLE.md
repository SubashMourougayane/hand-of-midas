# `oil_micro/` — Code Style

> Every line written under the unified-engine plan ships against these standards. Not negotiable.
> Scope: anything in `oil_micro/` and `tests/oil_micro/`.

## Why these rules exist

Five parity bugs in 24 hours. Three of the five had module-level mutable state as a contributing factor. Two had ambiguous None returns where a typed enum would have made the bug impossible to ship. We're rewriting for clarity, not for cleverness.

## Module-level rules

- **Single responsibility.** Top-of-file docstring states the one thing this module does. If you can't write that in one sentence, the module is wrong.
- **Hard size limit: ~300 lines per file.** If a module grows past 300 lines or starts mixing concerns, it splits before you commit.
- **Type hints everywhere.** `from __future__ import annotations` at the top. Public functions, return types, dataclass fields, every method signature. `mypy --strict` clean.
- **No module-level mutable state.** No `_daily_state = {}`, no `_traded_sweeps = set()`, no `_max_hold_deferred = {}` at the module level. State lives in instance attributes (`OilMicroEngine`, `PositionManager`, etc.). The legacy code's module-dict pattern is what made parity bugs hard to reason about — banned here.
- **No global side-effects on import.** No DB connections, no env reads, no `register_adapter` calls fired during `import oil_micro.core.state_store`. Anything that touches the outside world goes inside an explicit `__init__` or factory function. Importing the package must be free.
- **Protocols, not inheritance.** Adapters implement `typing.Protocol` interfaces. No abstract base classes; no `metaclass=ABCMeta`. Duck typing with structural conformance, checked by `mypy`.
- **Pure functions when possible.** `compute_bias`, `apply_gates.evaluate`, `_compute_limit_price` etc. take inputs + config, return decisions. No I/O, no state mutation. Easy to test, impossible to misorder.
- **Constants in one place per module.** No magic numbers in mid-function. Top-of-module:
  ```python
  COOLDOWN_SECS: int = 300        # 5-min between same-window signals
  MAX_BARS: int = 80              # MAX_HOLD = 4 hours of M3 bars
  ```
  Each constant has a one-line "why" comment.

## Function-level rules

- **Functions ≤ 40 lines.** If a function exceeds ~40 lines or 4 levels of nesting, extract helpers BEFORE you ship.
- **One concern per function.** A function either DECIDES, COMPUTES, or PERFORMS I/O — never two of the three. The legacy `execute_signal()` function does all three across 535 lines; that's the antipattern we're escaping.
- **Explicit None handling.** No `or` chains for fallback values where None is meaningful:
  ```python
  # BAD — hides whether None is a real answer or a fallback
  equity = nav_usd or balance or 10000

  # GOOD — explicit branches, future-readers know None is possible
  if nav_usd is not None:
      equity = nav_usd
  elif balance is not None:
      equity = balance
  else:
      equity = FALLBACK_EQUITY
  ```
- **Errors named, not stringified.** Define exception classes; callers catch by type, never regex on `.args[0]`:
  ```python
  class TradeRejected(Exception):
      def __init__(self, reason: SkipReason, ...): ...
  ```
  Where today's `execute_signal` returns `None` on 17 different failure modes, new code returns `Decision.skip(reason: SkipReason)` where `SkipReason` is a `StrEnum`.
- **Logging is structured.** Every `_log.info / .warn / .exception` call uses keyword args, never f-strings:
  ```python
  # GOOD
  _log.info("BROKER", "limit_placed", trade_ref=trade_ref, ticket=ticket, limit_price=limit)

  # BAD
  _log.info(f"placed limit for {trade_ref} at {limit}")
  ```
  Today's `_log` already does this — keep the discipline.

## Naming

- **`snake_case` for functions and variables.** Python convention.
- **`PascalCase` for classes and `Protocol`s.** `OilMicroEngine`, `Executor`, `OrderRef`.
- **`UPPER_SNAKE` for module-level constants.** `COOLDOWN_SECS`, `MAX_BARS`.
- **No abbreviations except common ones.** `bt` (backtest), `m3`/`h1`/`d` (timeframes), `pl` (P&L), `sl`/`tp`. Spelling out `position_exit_time` is fine; `pet` is not.
- **No `data` / `info` / `manager` / `helper` in module names.** Be specific: `state_store`, not `state_data`. `position_manager`, not `position_helper`.
- **Private with `_` only when truly internal.** A test helper that's used by tests in another file isn't private — give it a real name.

## Documentation

Every NEW module has a paired `.md` doc in `docs/oil_micro/`. **No code without a doc.** Template (enforced):

```markdown
# `oil_micro/<path>/<module>.py`

## Purpose
One paragraph — what problem this solves, why we couldn't reuse existing code.

## Contract
Public interface, semantics, error conditions. What can callers depend on.

## Implementation notes
Non-obvious choices, why this approach over alternatives. Rules of thumb for future readers.

## Tested by
- `tests/oil_micro/test_<module>.py`
- (any integration tests that hit this code)

## Related
- [[other-module]] — how it depends on this
- (cross-references to the rest of the doc set)
```

Cross-reference using `[[doc-name]]` style; future-you maintains the link by renaming both at once.

## Code review (self + automated)

- **Pre-commit hook**: `ruff check`, `ruff format`, `mypy --strict` on `oil_micro/`. CI fails on any warning.
- **Every PR has a "What this changes" + "Why" + "Testing notes" section.** Even self-merged commits.
- **No `# TODO` without a date + initials.** `# TODO(SM, 2026-06-25): handle weekend gap`. Bare TODOs are forbidden — they rot.
- **No commented-out code.** Git keeps history. If we might bring something back, comment-out is a smell — describe it in a commit message instead, or open a tracked task.

## Enforcement

Phase 1a deliverables include CI integration:
- `pyproject.toml` adds `ruff` config scoped to `oil_micro/`
- `pyproject.toml` adds `mypy` config with `strict = true` for `oil_micro/`
- `.github/workflows/ci.yml` adds the `oil_micro` lint + type job

Every Phase 1+ task explicitly references this doc. Phase 2 ship gate adds a code-quality review pass alongside the parity gate — if the code passes parity but fails style review, it doesn't ship.

## Related

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [TESTING.md](./TESTING.md)
- [PERFORMANCE.md](./PERFORMANCE.md)
