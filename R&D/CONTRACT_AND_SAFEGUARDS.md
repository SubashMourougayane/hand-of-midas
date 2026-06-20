# Contract and Safeguards — R&D Lab

> **Locked: 2026-06-20.** Six safeguards designed assuming the assistant's logic will fail. The user enforces these, not the assistant.

---

## Why this document exists

The assistant has a track record in this project of:
- Writing code that "looks right" but contains lookahead bugs
- Inflating numbers when memory contradicts disk
- Confirming itself via unit tests that test its own logic instead of ground truth
- Reporting success based on plausibility instead of verification

The user asked the right question: "what stops you from doing the same in R&D?"

These six safeguards are the answer. Each one specifically prevents a failure mode the assistant has demonstrated in this project. The user is the failsafe — these are tools the user uses to catch the assistant.

---

## Safeguard 1 — Sealed data access

### Rule
The lab CANNOT access raw CSV files directly. All data goes through `R&D/data_split.py:get_data(phase)` which:

- Takes a phase name as argument
- Returns ONLY the data slice allowed at that phase
- Logs every request to `R&D/data_access_log.txt` (append-only, tamper-evident)
- Refuses requests for locked phases until they unlock

### What this prevents
- Accidental peeking at validation/holdout data during development
- The assistant "just checking" what 2024 looks like before it's sealed
- Subtle parameter drift toward the unseen data via accidental observation

### How the user enforces it
- `grep -r "pd.read_csv" R&D/` should return nothing except the gateway in `data_split.py`
- `cat R&D/data_access_log.txt` shows every data request with a timestamp + phase + caller
- If a development-phase script logs a validation-phase request, the experiment is contaminated and we restart that phase

---

## Safeguard 2 — Pre-registered hypotheses with hash-locking

### Rule
Every test gets a `HYPOTHESES.md` entry written and committed to disk BEFORE the test runs. The entry includes:

- The hypothesis (one sentence)
- The prediction (specific numbers)
- The metric (PF, WR, total P&L, etc.)
- The pass/fail threshold
- A SHA256 hash of the file content at the time of writing
- A git commit reference

After the test runs, the result is appended below the hypothesis. **The hypothesis content is never edited.** If the prediction was wrong, that gets recorded as a wrong prediction, not silently corrected.

### What this prevents
- Moving the goalposts after seeing results
- "Reinterpreting" the prediction in the assistant's favor
- Post-hoc rationalization ("I actually predicted this, sort of")

### How the user enforces it
- For each result claimed, check `HYPOTHESES.md` for the prediction's hash
- Recompute the hash of the prediction text — if it differs, the prediction was edited after the fact
- If a prediction has no result yet, no claim of success or failure on that hypothesis is allowed

---

## Safeguard 3 — Automated lookahead audit

### Rule
For every signal-generation function written in Phase 1+, there's a paired test in `R&D/safeguards/test_no_lookahead.py` that proves the function uses no future data:

```python
def assert_no_lookahead(generate_signals, h1_full, m3_full):
    """For each timestamp T, the signal-gen output at T must be identical
    whether we feed it (full data) or (data truncated at T).
    """
    for T in sample_timestamps:
        full_signals = generate_signals(h1_full, m3_full, ...)
        signals_at_T_full = [s for s in full_signals if s.signal_ts <= T]

        truncated_signals = generate_signals(
            h1_full[h1_full.index <= T],
            m3_full[m3_full.index <= T],
            ...
        )
        signals_at_T_truncated = [s for s in truncated_signals if s.signal_ts <= T]

        assert signals_at_T_full == signals_at_T_truncated, (
            f"Lookahead detected at {T}: full version saw {len(signals_at_T_full)} "
            f"signals, truncated saw {len(signals_at_T_truncated)}"
        )
```

This test is written FIRST, before any signal-generation code exists. Every new signal function has its own parametrized invocation of this test.

### What this prevents
- The exact bug class found today (intra-bar M3 search inside a still-forming H1 bar)
- Any signal-gen function that reads future-relative-to-decision-time data
- The assistant "knowing" code is correct without proving it

### How the user enforces it
- `pytest R&D/safeguards/test_no_lookahead.py -v` runs after every signal-gen change
- If any signal function does not have a paired lookahead test, the function is considered broken
- A green test is REQUIRED before any phase advances

---

## Safeguard 4 — Codex as adversary

### Rule
After the assistant writes any signal-detection rule, the user takes a plain-English description of the rule (no code, just the concept) to Codex with this single prompt:

> "Here is a strategy detection rule the user wants implemented. Find every way it could contain lookahead, off-by-one, or subtle data-leakage bugs. Be adversarial. Assume the implementer has been wrong before."

The user collects Codex's findings, brings them back to the assistant. The assistant does NOT push back on findings without a concrete code-level disproof. Disagreements get resolved by running the actual ground-truth test, not by argument.

### What this prevents
- The assistant's blind spots being uniformly wrong (Codex has different blind spots)
- Single-implementation parity bugs (two adversarial implementations catch divergence)
- "Trust me, the code is right" — there is no trust, only ground-truth verification

### How the user enforces it
- For each phase, log Codex's findings in `DECISIONS.md` with: finding + assistant's response + resolution
- If the assistant pushes back without ground-truth proof, the user requires the ground-truth test to be written and run

---

## Safeguard 5 — Suspicion of "too good to be true" results

### Rule
If any phase produces results meeting ANY of these criteria, the result is **provisionally rejected** until a sanity-check test is run:

- Profit factor > 3.0
- Win rate > 60%
- Year-over-year consistency unusual for the asset class (every year green with low variance)
- Total P&L > expected by 2x or more

The sanity-check test:

```python
def random_baseline_test(strategy_module, data):
    """Replace strategy's signal-gen with random entries (matched signal frequency).
    Run the same BT engine. If random also looks profitable, the BT is broken."""
    random_signals = generate_random_signals(matched_count=actual_signal_count)
    random_pnl = run_bt(random_signals, data)
    assert random_pnl < 0, f"Random baseline produced ${random_pnl} — BT engine has positive bias"
```

This catches the lookahead class because lookahead-broken BT engines make any signal generator look profitable.

### What this prevents
- The "+$2.23M" trap from this morning — celebrating a result instead of questioning it
- Confirmation bias toward "great results"
- Stopping the audit when results are good but suspicious

### How the user enforces it
- After every phase, the user asks: "did random baseline produce a loss?"
- If the answer is "we didn't run it" — the phase is not complete

---

## Safeguard 6 — Phase audit + user sign-off

### Rule
At the end of each phase, the assistant writes a one-page audit covering:

1. **What I tested** — concrete list of code/tests run
2. **What I found** — results with numbers
3. **What might be wrong** — explicit list of bugs the assistant is worried about, even with no evidence
4. **What I'd want a skeptic to check** — specific verification steps

The user reads it. The user asks at least one skeptical question. The phase doesn't end until the user signs off in `R&D/README.md`.

### What this prevents
- The assistant declaring success unilaterally
- The user staying in the dark about what actually happened
- Silent drift between phases

### How the user enforces it
- The phase is "in progress" until the user writes their name + date in the README
- If the user doesn't understand the audit, they ask until they do
- The user's skeptical question gets a specific written response, not a hand-wave

---

## What these safeguards do NOT cover

- **Bugs the assistant doesn't think to check for.** That's why Safeguard 4 (Codex adversarial) exists.
- **Bugs that pass all 6 safeguards but still leak.** That's what Phase 4 (1% live sizing) is for.
- **The user choosing to override a safeguard.** The user can override any of these in writing in `DECISIONS.md`. The safeguards are tools, not chains.

---

## When a safeguard fires

The default response is **stop and fix**, not "I disagree, proceed anyway."

- Lookahead test fails → the signal function is wrong, fix it
- Random baseline produces profit → the BT engine is wrong, fix it
- Codex finds a bug → discuss it openly, run ground-truth test, decide
- Hash mismatch on hypothesis → the prediction was edited, restart that test with a fresh prediction
- User skeptical question can't be answered → the phase is not done

---

## Status

**2026-06-20 evening:** Safeguards committed to this document. Implementation code for safeguards 1, 3, 5 is pending in next session. Safeguards 2, 4, 6 are process-only (no code).
