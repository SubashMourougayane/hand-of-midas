# Daily Entry Template

> Copy this section into `DAILY_LOG.md` every morning. Replace placeholders with real values.
> Times in IST. Wallet in account currency (USD).
> **Day 0 baseline:** $10,000.00 — every "Δ vs $10K" is computed from this anchor.

---

```markdown
## 2026-MM-DD (Day NN of 30, Phase X — <PHASE_NAME>)

### Morning (target: 5 min)
- **JM wallet (yesterday close):** $X,XXX.XX
- **Yesterday delta:** ±$XX.XX
- **Cumulative Δ vs $10K baseline:** ±$XX.XX
- **Today's plan:** observe only / postmortem trades / write weekly report / ship task XYZ
- **Open trades inherited from yesterday:** GD-XX-xxxx (if any)
- **Marathon risk flag:** ⚠️ if I'm tempted to work >3hrs today (note WHY)

### Trades fired today
| trade_ref | system | side | entry | exit | P&L (DB) | P&L (JM web) | tag |
|---|---|---|---|---|---|---|---|
| (none yet) | | | | | | | |

Tag legend: `clean-strat` / `bug` / `drift` / `outlier`

### Postmortems written
- [ ] GD-XX-xxxx — postmortem committed (link to file)

### Missed limit orders (LIMIT_TTL_EXPIRED) — counterfactual ledger
| trade_ref | system | direction | limit | TP | SL | placed → expired | counterfactual: TP/SL/neither, est P&L |
|---|---|---|---|---|---|---|---|
| (none yet) | | | | | | | |

> Fill counterfactual at evening close from price feed (NOT BT). 30-day aggregate = F27 cost/value calibration.

### Surprises / observations (P1/P2/P3)
- 🟠 P1: <bug found, not bleeding, parked in AUDIT>
- 🟡 P2: <idea, parked in ideas/IDEAS.md>
- 🟢 P3: <itch, ignored>

### P0 events (rare)
- 🔴 None / <description + link to hotfix commit>

### Evening close (target: 10 min)
- **JM wallet (today close):** $X,XXX.XX
- **Today delta:** ±$XX.XX
- **Cumulative Δ vs $10K:** ±$XX.XX
- **DB pnl sum (today) vs wallet Δ:** $X / $X — ✅ match / ⚠️ mismatch (mismatch = bug-smell)
- **Trades count:** N (W/L)
- **Postmortem coverage:** N/N (target 100%)
- **Daily ritual completed:** ✅ / ❌ (if ❌, why)
- **Hours spent on Hand of Midas:** Xh (cap 3h)
- **Laptop closed at:** HH:MM IST

### One-line verdict for the day
> <single sentence — no caveats. e.g. "Quiet day, no trades, F28 still neutral, no surprises.">
```

---

## Filling rules

1. **Morning section gets written FIRST**, before any work. If you skip morning, the day doesn't count.
2. **Trade table updated as trades close.** Don't batch — note each one as it happens.
3. **Postmortem checkbox** is unchecked until the file is committed in `postmortems/`.
4. **P0 events** demand the protocol from `DISCIPLINE_PLAN_30DAY.md` — do not just log it.
5. **Evening close is mandatory.** Even if no trades fired. Even on weekends. Even when traveling.
6. **One-line verdict** — no hedging. "Sideways day" is a valid verdict. "Bug found, parked, freeze held" is too.

## Anti-patterns

- ❌ Writing 4 days of entries Sunday night to "catch up"
- ❌ Leaving evening close blank "I'll fill it tomorrow"
- ❌ Logging only winning trades' postmortems
- ❌ Hiding the P0 hotfix commit because "it was small"
- ❌ Marking ritual ✅ when you actually skipped morning section

## Success habit

If you complete this template **30 days in a row** with zero skips, you've built the measurement habit. That's the win. P&L is byproduct.
