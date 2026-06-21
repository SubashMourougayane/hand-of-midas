# A1 — Sweep blacklist rollback on clean None return

## What this fix does and does not do

### Does
- Stops a specific class of "missed trade" cases where a sweep gets marked as `gd_traded_sweeps` but no trade actually fires, blocking later signals on the same sweep_key for the rest of the day.

### Does not
- Touch signal generation logic
- Change any strategy parameters
- Change BT behavior
- Refactor anything
- Touch Gold Macro / Oil Macro code
- Add new gates or filters
- Modify the database schema

If the diff includes anything not in the "Does" list, the fix is wrong. Reject it.

## The bug

Live scheduler currently:

1. Detects a sweep + engulfing → has a `signal` object.
2. INSERTs into `gd_traded_sweeps` (sweep_key, day) — marking the sweep as consumed.
3. Calls `execute_signal(...)` to actually place the order.

If step 3 returns `None` for any reason that is **not an exception** — examples: account_summary call returned an error dict, equity below floor, sl_distance was 0, risk computation produced units < 1 — then:

- `gd_traded_sweeps` row stays inserted.
- No trade was placed.
- The sweep is now blacklisted for the rest of the day.
- Any later H1 bar that re-detects the same sweep will skip it.

This **silently loses legitimate trade opportunities** when an early-day signal hits a soft skip. The blacklist was supposed to dedupe FILLED trades, not protect skipped-but-attempted trades.

## Scope of files touched

Per the codebase grep, both Micros have the same disease:

- `backend-oil-micro/scanner/live_engine.py` — Oil Micro live engine
- `backend-micro/scanner/live_engine.py` — Gold Micro live engine

Macros (`backend/scanner/...`, `backend-oil/scanner/...`) are retired per `scripts/start-win.bat` — out of scope for this fix.

## The fix

**Pattern:** wrap the insert + execute pair so the blacklist row is only committed when the trade actually fires. Two acceptable shapes:

**Shape A (preferred — minimal change):** flip the order. Call `execute_signal` first; only INSERT into `gd_traded_sweeps` if the call returns a non-None trade_ref AND the trade was placed (not just an order error).

**Shape B (transaction-safe):** keep the order, wrap in a try/finally that DELETEs the blacklist row when execute_signal returns None.

Shape A is preferred because it removes a write rather than adding one.

## Acceptance criteria

The fix is accepted if and only if:

1. **Diff is small.** Two files touched. < 30 lines changed total. If it grows, scope is wrong.
2. **No new SQL columns.** No schema migration. Use only existing `gd_traded_sweeps` shape.
3. **Existing behavior preserved on FILLED:** when a trade actually fires, the sweep_key still ends up in `gd_traded_sweeps` for that day. (The fix protects against the None case; it must not regress the success case.)
4. **Existing behavior preserved on EXCEPTION:** if `execute_signal` raises, the bug is different and not in scope. Don't touch the exception path.
5. **Regression test added.** A pytest that:
   - Calls a stubbed `execute_signal` that returns None.
   - Asserts `gd_traded_sweeps` does NOT contain the sweep_key after.
   - Calls a stubbed `execute_signal` that returns a valid trade_ref.
   - Asserts `gd_traded_sweeps` DOES contain the sweep_key after.
6. **Manual verification** — I'll grep both `live_engine.py` files post-fix and confirm: only one INSERT into `gd_traded_sweeps` per scheduler call, gated on trade fired.

## What I will check before claiming done

1. `git diff` — visual review of both files.
2. `pytest` — new regression test passes.
3. `grep "gd_traded_sweeps" backend-{oil-,}micro/scanner/live_engine.py` — confirm both files match the same fix shape.
4. No other files modified.

If any of those fail, I rollback and tell you. I do NOT commit until all four pass.

## What I will NOT do

- Add new logging beyond what already exists (existing `_log` calls only).
- Add docstrings beyond a one-line comment naming this doc.
- Move code blocks around for readability.
- "While I'm here" cleanups.
- Touch any other audit-list item (M14, A2, A10).

## Rollback path

If the fix breaks anything, revert to `midas-deploy@HEAD` which is the pre-fix state:

```
git checkout midas-deploy -- backend-oil-micro/scanner/live_engine.py backend-micro/scanner/live_engine.py
git checkout midas-deploy -- tests/  # if I added a test file
```

## Sign-off

The user will:
- Read the diff
- Approve or reject it
- Commit only after explicit approval

I will not commit without explicit "yes commit it" from the user.

---

**Status when this doc was written:** scoped, not yet implemented. Next step: read the actual code in both files, identify the exact line range, write the fix.
