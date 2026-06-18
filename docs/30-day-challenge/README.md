# 30-Day Discipline Challenge — Hand of Midas

> **The bible for the next 30 days.**
> ~~**Start:** Thursday, June 18, 2026~~ **EXTENDED**
> **Revised Start:** **Monday, June 22, 2026** (Day 1)
> **Revised End:** Tuesday, July 21, 2026 (Day 30)
> **Owner:** Subash
> **Mode:** Solo. No new builds. Watch. Measure. Decide. One controlled ship.
>
> **Starting capital (Day 0 baseline):** **$10,000.00 USD** (JustMarkets MT5 wallet, post top-up Jun 18 morning)
> **Anchor metric:** every "wallet delta" reported in this folder is computed against the $10,000 baseline.
>
> **Pre-Day-1 (Jun 18–21):** "build week" — code changes ALLOWED to fix discovered bugs (cap counter, F28-in-BT). Phase 0 freeze starts Monday. Full reset of Phase 0 counter — Day 1 freeze test begins on Jun 22.

---

## Why this folder exists

Every session before this one ended with a new filter, a new feature, or a new sweep. P&L from real money has not validated the work. The pattern is **build velocity > evidence velocity**.

This 30-day block reverses that. **Every decision must be backed by data captured during the freeze.** No vibes. No "I think." Numbers from JM wallet, postmortems, and parity logs only.

If at the end of 30 days the system is net-positive on real money, the strategy compounds. If not, the data tells you which gap to attack next. **Either outcome wins, because both are based on evidence.**

---

## Folder layout

```
docs/30-day-challenge/
├── README.md                          ← you are here (the bible)
├── DISCIPLINE_PLAN_30DAY.md           ← phases, exit gates, exception ladder
├── DAILY_TEMPLATE.md                  ← copy-paste skeleton for each day
├── DAILY_LOG.md                       ← single rolling file, daily entries appended
├── postmortems/                       ← per-trade postmortem .md files
│   └── <trade_ref>.md                 ← (script-generated + skill-filled)
├── reports/                           ← weekly summaries + decision docs
│   ├── WEEK_1_FREEZE.md               ← end of day 7
│   ├── WEEK_2_MEASURE.md              ← end of day 14
│   ├── WEEK_3_DECIDE.md               ← end of day 21
│   └── WEEK_4_ONE_THING.md            ← end of day 30
└── ideas/                             ← future-self parking lot
    └── IDEAS.md                       ← P2 thoughts, do NOT act on during freeze
```

**Rule:** Every artifact for the next 30 days lives here. Postmortems, daily journal, weekly reports, parking-lot ideas. Nothing else gets created in `docs/` root unless it's a P0 hotfix writeup.

---

## The four phases

| Phase | Days | Theme | Exit gate |
|---|---|---|---|
| **0. FREEZE** | 1–7 (Jun 18 – Jun 24) | Zero new code. Watch the system run. Daily journal. | 7 consecutive days of journal entries, zero new filter commits |
| **1. MEASURE** | 8–14 (Jun 25 – Jul 1) | Postmortem every trade. Tag clean / bug / drift. | 15+ live trades postmortem'd |
| **2. DECIDE** | 15–21 (Jul 2 – Jul 8) | Look at the data. Verdict on F28. Identify highest-leverage gap. | Written verdict + ranked gap list |
| **3. ONE THING** | 22–30 (Jul 9 – Jul 17) | Ship ONE filter or fix. Multi-stage opt-in. Watch. | One controlled ship in production, 3+ trades observed |

Detailed action lists, daily rituals, and exception ladder live in `DISCIPLINE_PLAN_30DAY.md`.

---

## Standing rules (read once, follow always)

1. **No new filters during phases 0–2.** F30, F31, F29 all wait. Park them in `ideas/IDEAS.md` as you think of variants.
2. **No config flips during freeze.** F28 stays as it is on day 1 (currently neutral on all 4 systems). If you flip it, the 30-day data is contaminated.
3. **3-hour daily cap.** Hand of Midas work only. Marathon sessions cause cascades — June 10 orphan, June 15 dedup, every recurring incident is fatigue.
4. **Daily ritual is mandatory.** Skipping a day is failure. Even on weekends. Even on travel. 10 minutes minimum.
5. **JM wallet is the source of truth.** DB pnl, BT projections, my verdicts — all secondary. Wallet up or wallet down is the only honest signal.
6. **Postmortem every trade.** No exceptions. Not "I'll do it tomorrow." That's how the gap accumulates and signal disappears.
7. **P0 exception is real but rare.** See exception ladder in `DISCIPLINE_PLAN_30DAY.md`. Default everything to P1 unless money is bleeding right now.
8. **No "quick refactor."** No "while I'm here." No "let me just clean this up." Itches stay itches.
9. **Caveman replies stay.** Brevity forces clarity. If I drift into corporate prose, call me out.
10. **Weekly report is the compounding artifact.** Daily entries feed weekly. Weekly reports feed the day-30 decision. Without weekly reports, this challenge is wasted.

---

## What success looks like on day 30

- ✅ 30 daily journal entries in `DAILY_LOG.md`
- ✅ 15+ postmortems in `postmortems/`
- ✅ 4 weekly reports in `reports/`
- ✅ Verdict on F28 (keep / revert / inconclusive — needs more data)
- ✅ One controlled ship live (or explicit decision: nothing was worth shipping yet)
- ✅ Honest measurement of: real-money P&L, live↔BT gap, bug count, my-AI-trust calibration
- ✅ Day-30 JM wallet number recorded — the ONE number that judges the cycle vs $10,000 baseline

---

## What failure looks like (and how to know)

- ❌ Skipped 2+ daily entries → discipline breaking
- ❌ Shipped any filter outside the day-22+ window → freeze violation
- ❌ Postmortem skipped on any trade → measurement incomplete
- ❌ Marathon session (>3 hrs Hand of Midas work) → fatigue cascade risk
- ❌ "Bigger finding" detour without P0 justification → trap fallen for

If any of these happen, **don't quit the challenge — restart that phase**. The point isn't perfection, it's the practice of measurement-before-action.

---

## How to use this folder day-to-day

**Morning (5 min):**
1. Open `DAILY_LOG.md`
2. Copy the template from `DAILY_TEMPLATE.md`
3. Write today's date header
4. Note JM wallet number from yesterday close
5. Note today's plan (or "FREEZE — observe only" during phase 0)

**After each trade fires (5 min/trade):**
1. Run `python scripts/postmortem.py <trade_ref>` (writes to `docs/trades/`)
2. Move generated file to `docs/30-day-challenge/postmortems/`
3. Fill 7 placeholders using the trade-postmortem skill
4. Tag in `DAILY_LOG.md`: `[GD-MI-xxxx] clean / bug / drift / outlier`

**Evening (10 min):**
1. Update `DAILY_LOG.md` with: trades, P&L, JM wallet close, anything weird
2. If anything weird → log to `ideas/IDEAS.md` (P2) or new audit file (P1)
3. **Close laptop.** No "one more thing."

**Sunday evening (30 min):**
1. Open week's `reports/WEEK_N_*.md`
2. Tally: wallet delta, trade count, win count, bug count, postmortem count
3. Write 1-paragraph verdict: "this week showed X"
4. Identify carry-over for next week

---

## Linked memory

- [[user-profile]] — solo builder, ships fast, validates against real money
- [[feedback-no-auto-ship]] — every change needs sign-off
- [[feedback-user-explicit-opt-in]] — multi-stage opt-in for live changes
- [[feedback-architecture-decisions]] — edge = selective non-participation
- [[project-calibration-plan]] — was deferred until 30 clean trades; this challenge generates them

---

## Mode of operation summary

```
DEFAULT MODE = OBSERVE
TRIGGER FOR ACTION = data, not feeling
SHIP CADENCE = once per 30-day cycle
EXCEPTION = P0 only (money bleeding NOW)
ARTIFACTS = daily log + postmortems + weekly reports
SUCCESS METRIC = honest evidence, not P&L
```

The challenge is not "make money in 30 days." The challenge is **build the measurement habit so future shipping is evidence-driven.** P&L is a downstream byproduct.
