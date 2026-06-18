# Discipline Plan — 30 Days

> **Start:** Thursday, June 18, 2026
> **End:** Friday, July 17, 2026
> **Goal:** Convert a build-velocity habit into a measurement-velocity habit.
> **Shipping budget:** Exactly ONE filter or fix in 30 days. No more.

---

## Phase 0 — FREEZE (Days 1–7) · Jun 18 – Jun 24

### What you do

- Run the system. Do nothing.
- F28 stays exactly as deployed today (neutral on all 4 systems).
- Daily ritual every day (see Daily Ritual section).
- Watch the Telegram channel + JM wallet.
- Note any behaviour that surprises you — write it in `ideas/IDEAS.md` (P2) or new audit doc (P1). **Do not act.**

### What you don't do

- No new filter research (F30, F31, F29 all parked).
- No config flips. No env-var tweaks. No "let me just try."
- No code commits except P0 hotfix.
- No new BT sweeps.
- No "quick UI cleanup."

### What you measure

- Number of trades per system per day.
- Wallet delta day-over-day.
- Any bugs / surprises (count + tag).
- Days you actually completed the daily ritual (target = 7/7).

### Exit gate (Day 7, Jun 24 evening)

Move to Phase 1 only if:
- ✅ 7 daily entries in `DAILY_LOG.md`, no skips
- ✅ Zero new filter commits (frontend hotfixes / dependency bumps allowed if P0)
- ✅ Wrote `reports/WEEK_1_FREEZE.md` with: trades count, wallet delta, surprises log

If any fails → **restart phase 0**. Do not advance.

---

## Phase 1 — MEASURE (Days 8–14) · Jun 25 – Jul 1

### What you do

- Continue daily ritual.
- **Postmortem every trade** as it closes. Skill: `trade-postmortem`. Script: `scripts/postmortem.py <ref>`.
- Move postmortem files to `docs/30-day-challenge/postmortems/`.
- Tag each in `DAILY_LOG.md`: `clean-strat / bug / drift / outlier`.
- Build N=15+ live trades sample.

### What you watch for in postmortems

| Tag | Meaning |
|---|---|
| **clean-strat** | Strategy fired as designed, outcome consistent with BT distribution |
| **bug** | Mechanical failure (DB row missing, Telegram dropped, EA didn't fire, parity broken) |
| **drift** | Strategy fired but live behaviour diverges from BT (slippage, BE timing, exit price) |
| **outlier** | R:R / range / hold time / lot size unusual vs peers — investigate |

### Postmortem requirements

- Run script first — never write from memory.
- Fill all 7 placeholders (verdict, tldr, strategy_alignment, bug_smell, pattern, counterfactual, recommendations).
- If JM wallet number contradicts DB pnl, that's a `bug` tag — not "I'll check later."
- Commit each postmortem with message: `Postmortem: <trade_ref> — <verdict>`.

### Exit gate (Day 14, Jul 1 evening)

- ✅ 15+ postmortem files in `postmortems/`
- ✅ Each tagged in `DAILY_LOG.md`
- ✅ `reports/WEEK_2_MEASURE.md` written with tag distribution + emerging patterns

If <15 trades fired in 7 days, **extend phase 1** by another 7 days. Do not advance with thin data.

---

## Phase 2 — DECIDE (Days 15–21) · Jul 2 – Jul 8

### What you do

- Continue daily ritual.
- Continue postmortems for any new trades.
- **Spend 1 hour/day on data review** (no code).
- Answer the F28 question.
- Rank the gaps revealed by postmortems.

### The F28 verdict question

Was F28 (bias filter disabled) net-positive on real money over 14 days?

Three honest answers allowed:
1. **Keep neutral** — wallet delta + tag distribution favours neutral. Document in `reports/WEEK_3_DECIDE.md`.
2. **Revert to production** — neutral hurt. Flip env back, document, consider F30 next cycle.
3. **Inconclusive** — N too small or noise dominates. Continue freeze, decide at day 60.

**Do NOT default to "keep" because shipping it felt good.** Wallet number is the judge.

### The gap-ranking question

Of all `bug` and `drift` tags in postmortems, which gap costs the most P&L?

Rank candidates by:
- Frequency (how many trades affected)
- Severity (avg P&L delta when bug fires)
- Fixability (1-line config flip vs new feature)
- Confidence (do you understand the root cause or guessing)

Top item = candidate for Phase 3 ship. Runners-up parked in `ideas/IDEAS.md` for next cycle.

### Exit gate (Day 21, Jul 8 evening)

- ✅ F28 verdict written
- ✅ Gap ranking written, top item identified
- ✅ `reports/WEEK_3_DECIDE.md` complete
- ✅ Phase 3 ship plan drafted (1 item, multi-stage opt-in spec)

If no gap is worth shipping → **Phase 3 = continue measuring**. Skipping Phase 3 is a valid outcome, not a failure.

---

## Phase 3 — ONE THING (Days 22–30) · Jul 9 – Jul 17

### What you do

- Ship the one item identified in Phase 2.
- Multi-stage opt-in protocol (see below).
- Continue daily ritual + postmortems.
- Watch the shipped change for 3+ trades.

### Multi-stage opt-in protocol

The standing rule from `feedback-user-explicit-opt-in`:

1. **Default OFF** — new code path gated behind env var.
2. **Pre-ship verification:**
   - Real BT engine run pre/post.
   - Parity harness check.
   - Unit tests added.
3. **Ship to one system first** — pick the lowest-volume system (Gold Macro typically) so observation is cheap.
4. **Watch 3 trades** before flipping to next system.
5. **No global flip** unless every per-system flip passed without surprise.
6. **No bundling** — ship the change alone, no surrounding cleanup.

### Forbidden during Phase 3

- Adding scope ("while I'm here, let me also fix…").
- Skipping multi-stage opt-in because "it's a small change."
- Flipping all 4 systems at once (the F28 mistake — overrode the rule).

### Exit gate (Day 30, Jul 17 evening)

- ✅ One filter or fix shipped, deployed to at least one system.
- ✅ 3+ live trades observed under the new code path.
- ✅ `reports/WEEK_4_ONE_THING.md` written: what shipped, what observed, was the BT projection honoured live?

If ship blew up → revert immediately, write postmortem, this is a phase 4 task next cycle.

---

## Daily ritual (mandatory, every day, weekends included)

### Morning (5 min)

```
1. Open docs/30-day-challenge/DAILY_LOG.md
2. Copy template from DAILY_TEMPLATE.md → append today's section
3. Note JM wallet number from yesterday close
4. Note today's plan (or "Phase 0 — observe only")
5. Note phase day number (e.g. "Phase 0, Day 3 of 7")
```

### Per-trade (5 min each)

```
1. python scripts/postmortem.py --latest
2. Move generated file → docs/30-day-challenge/postmortems/
3. Open file, fill 7 placeholders via trade-postmortem skill
4. Update DAILY_LOG.md with: [GD-XX-xxxx] tag + 1-line summary
5. git add + commit (do not push during freeze unless P0)
```

### Evening (10 min)

```
1. Tally today: trades count, P&L sum, JM wallet close
2. Note any P2 ideas → ideas/IDEAS.md
3. Note any P1 audit items → existing AUDIT_BACKLOG or new file
4. CLOSE LAPTOP. Even if you "feel productive."
```

### Sunday evening (30 min)

```
1. Open this week's reports/WEEK_N_*.md
2. Tally week: trades, wins, losses, wallet delta, bug count, postmortem count
3. Write 1-paragraph verdict
4. Identify carry-over for next week
5. Commit weekly report
```

---

## Exception ladder — when freeze breaks

### 🔴 P0 — STOP, ship now

Triggers (ALL must be true):
- Money is leaking right now (wallet visibly down vs expected)
- Will leak more in next 24 hours if untouched
- Cannot disable feature via env flag (code change required)

Examples:
- Orphan trade open on broker, no DB row
- Phantom fill: DB shows +$X, broker shows -$Y
- Position direction wrong vs strategy intent
- DB corruption affecting live decisions

Protocol:
1. Write 1-line: `🔴 P0 — <what's bleeding>` in `DAILY_LOG.md`
2. **Disable via env flag first** if possible — code change is last resort
3. If code change required: ONE commit, ONE file, no surrounding cleanup
4. Postmortem the bug next morning
5. Resume freeze

### 🟠 P1 — Investigate, don't ship

Triggers:
- Bug found but not bleeding right now
- Found because postmortem revealed drift
- "Should fix this" feeling

Examples:
- `is_latest` race condition (found Jun 18 — bug exists but didn't bleed)
- Trade fired with wrong bias once
- Telegram delivery flaked once
- Log spam annoying

Protocol:
1. Write up in new file under `docs/` root or extend existing `AUDIT_BACKLOG.md`
2. Tag P1 in title
3. **DO NOT FIX.** This is the discipline test.
4. Defer to Phase 3 (One Thing) ranking

### 🟡 P2 — Park the thought

Triggers:
- "What if I added X filter?"
- "F30 looks promising"
- "Oil Macro PF would improve if…"

Protocol:
1. Open `ideas/IDEAS.md`
2. Date-stamp + 2-sentence thought
3. **DO NOT RESEARCH.** This is the hardest discipline test.
4. Re-read at Phase 2 (Decide) for ranking

### 🟢 P3 — Itch, ignore

Triggers:
- "Quick refactor"
- "Clean up this comment"
- "While I'm here…"
- "Just one config tweak"

Protocol:
1. Close laptop
2. Walk away
3. The itch will be there tomorrow if it matters. It usually won't.

---

## Common traps and counter-rules

### Trap 1: "P0 disguised as P1"

You will rationalize. "This bug COULD bleed money tomorrow."

**Counter-rule:** P0 requires bleeding NOW, not "could." If wallet hasn't moved, it's P1.

### Trap 2: "Big finding detour"

"Wait, I found something HUGE. I have to investigate now."

**Counter-rule:** Findings don't expire. Park, continue freeze, investigate at Phase 2.

### Trap 3: "Quick fix while I'm in there"

Touching one file, see another smell. "Five-minute cleanup."

**Counter-rule:** ONE-FILE COMMIT-RULE. If a P0 fix touches 2+ files, you're cleaning, not fixing.

### Trap 4: "Builder's high"

Everything feels productive at hour 16. Decisions look obvious.

**Counter-rule:** 3-hour cap. Set timer. When it rings, close laptop. Continue tomorrow.

### Trap 5: "AI says it's validated"

I'll run a script and say "validated +$X". My script is not your evidence.

**Counter-rule:** Only YOU can validate. Wallet number + postmortem tags. AI verdicts go in postmortem `recommendations` section, not the action list.

### Trap 6: "Multi-stage opt-in is overkill for this small change"

You'll feel this in Phase 3. "It's just one config."

**Counter-rule:** F28 was "just one config." You flipped 4 systems same day. Now you can't isolate which system gave which signal. **Multi-stage is the signal-preservation tax. Pay it.**

---

## Day-30 retrospective questions

When you sit down on Jul 17 evening to write the final report, answer these honestly:

1. **Wallet delta:** Did real money go up, down, or sideways over 30 days?
2. **Discipline:** How many days did you skip the ritual? (Be honest. Skipping ≠ failure, but lying ≠ allowed.)
3. **Postmortems:** How many trades did you actually postmortem out of total? Target was 100%.
4. **F28 verdict:** Did you make the call based on data or vibes?
5. **Phase 3 ship:** Did you ship one thing, multi-stage? Or did you bundle / skip multi-stage?
6. **AI calibration:** How many of my verdicts in postmortems were proven wrong by the next trade? (You're keeping me honest.)
7. **Marathon count:** Any 6+ hour Hand of Midas sessions? If yes — fatigue cost?
8. **Itch ignored:** How many P2/P3 items in the ideas folder went un-built? That's wins.
9. **Next 30 days:** What's the next discipline block based on this evidence?

---

## What this plan is not

- ❌ A guarantee of profit. Strategy edge ≠ guaranteed by discipline.
- ❌ A fixed schedule. P0 events break the rhythm by design.
- ❌ A no-build zone forever. This is ONE 30-day block. The next block could be different.
- ❌ A solo project. Use the AI assistant — but for measurement, not for shipping.

## What this plan is

- ✅ A forced measurement habit.
- ✅ A defence against builder fatigue.
- ✅ A way to make Phase 3 shipping evidence-driven.
- ✅ A reusable template — every 30 days runs this same structure.

---

**This is the bible. Re-read every Sunday.**
