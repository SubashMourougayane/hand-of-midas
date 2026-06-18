# Daily Log — 30-Day Challenge

> **Append-only.** Newest entries at the top. Use `DAILY_TEMPLATE.md` for each day.
> **Started:** Thursday, June 18, 2026
> **Phase 0 — FREEZE** (Days 1–7) · Jun 18 – Jun 24
>
> **Starting capital (Day 0 baseline):** **$10,000.00 USD** (JM MT5 wallet, post top-up Jun 18 morning)
> All "wallet delta" entries below are computed vs this $10,000 anchor.

---

## 2026-06-18 (Day 1 of 30, Phase 0 — FREEZE)

### Morning (target: 5 min)
- **JM wallet (Day 0 baseline, post top-up):** **$10,000.00**
- **Yesterday delta:** n/a (Day 1 — baseline established today)
- **Today's plan:** Bootstrap challenge folder, write the bible. After today: observe only.
- **Open trades inherited from yesterday:** _<fill — check JM web Jun 18 morning>_
- **Marathon risk flag:** ⚠️ today is high-risk — eager to set up framework, must NOT chain into "let me also fix one bug"

### Trades fired today
| trade_ref | system | side | entry | exit | P&L (DB) | P&L (JM web) | tag |
|---|---|---|---|---|---|---|---|
| OIL-MI-ac215cc6 | Oil Micro | LONG | $78.47 | $78.17 (SL) | −$360.00 | −$367.20 (incl −$7.20 swap) | clean-strat / **F28-allowed-against-bias** |
| OIL-MI-1310e9cd | Oil Micro | SHORT | $78.07 | $78.06 (BE-SL) | **+$3.00** | — | 🐛 TWO BUGS: phantom BE arm (trigger=$77.67 vs real M1 LOW $78.00) + wrong-side SHORT BE-SL math. Lucky drift → +$3. Without bugs: ride to TP +$303. Bug cost: $300. |

### Postmortems written
- [x] OIL-MI-ac215cc6 — `postmortems/OIL-MI-ac215cc6.md` — verdict: ✅ Clean loss — strategy as designed (Day 1 trade)
- [x] OIL-MI-1310e9cd — `postmortems/OIL-MI-1310e9cd.md` — verdict: 🐛 TWO P0-candidate bugs detected (phantom BE arm + wrong-side SHORT SL math) — see IDEAS.md
- [x] OIL-MI-6fbb7040 — Jun 17 backfill — ✅ Clean loss — 3rd Oil Micro SL in streak
- [x] OIL-MI-ea9d591d — Jun 17 backfill — ✅ Clean loss — 2nd Oil Micro SL in streak
- [x] OIL-MI-08b725d3 — Jun 17 backfill — ✅ Protected by BE — F5 saved $326 of risk
- [x] GD-MI-2b152d33 — Jun 17 backfill — 🔍 Outlier — R:R 1.17 below structural break-even
- [x] GD-AL-4af2d62d — Jun 17 (already postmortem'd pre-challenge, copied to folder)
- [ ] OIL-AS-a251ada3 / b32439ae / e5705d4e — Oil Macro skipped (postmortem.py auth bug, parked P1)

### Backfill key findings (CONTEXT: Jun 17 trades are PRE-RESET — NOT F28 candidates)

**IMPORTANT:** Account was reset to $10,000 on Jun 18 morning, AFTER F28 was flipped Jun 17 evening. The only F28-candidate trade in the 30-day challenge so far is **OIL-MI-ac215cc6** (post-reset Day 1 BRENT). The 5 backfilled postmortems (Jun 17) are PRE-BASELINE — useful for pattern context only, NOT for F28 verdict.

- **Pre-baseline pattern observation:** Oil Micro 4-trade losing streak Jun 17–18 (−$976 net). All 3 SHORTs in $79–80 zone — likely fighting up-trending Oil. **Not F28 evidence.** Could be regime-mismatch unrelated to F28.
- **F5 (BE 35%) confirmed working** on OIL-MI-08b725d3 (pre-baseline) — BE armed at ~36% to TP, saved $326.
- **GD-MI-2b152d33 fired with R:R 1.17** (pre-baseline) — borderline-spec entry. Phase 1 watch: track every Gold Micro R:R.
- **3 new P1s parked:** R:R-uses-BE-adjusted-SL, BE-50%-threshold-mismatch, GD-MI-permissive-R:R-gate.
- **Discipline test #5:** wanted to pull OANDA CSV + run BT for "validation" — pushed back hard, held line.

### F28 evidence ledger (post-reset only — REAL data)

| trade | bias_mode | computed_bias | direction | F28 effect | P&L |
|---|---|---|---|---|---|
| OIL-MI-ac215cc6 | neutral | bearish | LONG (against bias) | F28-ALLOWED | −$367.20 |
| OIL-MI-1310e9cd | neutral | bearish | SHORT (with bias) | bias-aligned (no F28 effect) | +$3.00 |

**N=2 closed. F28-allowed: 1 (lost). Bias-aligned: 1 (BE save). Insufficient for verdict.**

### Pending limit orders → BOTH EXPIRED (LIMIT_TTL_EXPIRED at 07:15 UTC)

| trade_ref | system | side | limit | SL | TP | R:R | placed | result |
|---|---|---|---|---|---|---|---|---|
| GD-MI-f2a2f90b | Gold Micro | LONG | $4300.32 | $4294.34 | $4327.89 | 4.61 | 07:00 UTC | TTL_EXPIRED 07:15 |
| OIL-MI-de5d0d17 | Oil Micro | LONG | $77.16 | $76.74 | $78.91 | 4.17 | 07:00 UTC | TTL_EXPIRED 07:15 |

**Outcome:** No fills. No P&L. Price never pulled back into limit levels within 15min TTL.

**Filter #27 win:** if these had been market orders, they would have filled at the trigger price (likely worse on a fast LONG). Limit said "buy only on pullback" — pullback didn't come, no trade. Slippage saved.

**F28 evidence note:** TTL_EXPIRED ≠ F28 trade (no fill, no risk). These don't enter the F28 ledger.

### Missed-limit ledger (counterfactual — would this trade have won/lost if F27 hadn't pulled it back?)

> Track post-expiry: did price reach TP, SL, or just sit between? Records F27 cost-of-discipline.
> Source: query journal/state for price extremes from limit_placed → next 4hr (Micro) / next bar close (Macro).
> **DO NOT run BT to compute this — use live tick/bar data only.**

| trade_ref | system | direction | limit | TP | SL | placed → expired | post-expiry: did TP hit? did SL hit? counterfactual P&L |
|---|---|---|---|---|---|---|---|
| GD-MI-f2a2f90b | Gold Micro | LONG | $4300.32 | $4327.89 | $4294.34 | 07:00→07:15 UTC | TBD — fill in evening close from price feed |
| OIL-MI-de5d0d17 | Oil Micro | LONG | $77.16 | $78.91 | $76.74 | 07:00→07:15 UTC | TBD — fill in evening close from price feed |

**Interpretation rule:**
- If TP would have hit → F27 cost us the win (bad for F27)
- If SL would have hit → F27 saved us (good for F27)
- If neither (sideways) → F27 neutral

**End-of-30-day aggregate:** sum counterfactual P&L from missed limits. Compare to actual P&L from filled limits. Tells us if F27's TTL is too tight (too many TP-hits missed) or correctly calibrated.

### Surprises / observations (P1/P2/P3)
- 🟠 P1: `is_latest` race condition in `gd_backtest_runs` → `/backtest/latest` returns `{result:null}` wrapper when no row has `is_latest=TRUE`. Frontend now guarded (commit b014083). Backend fix deferred to Phase 3 ranking.
- 🟠 P1: API drift between Macro and Micro `/backtest/latest` shape — Macro wraps in `{result: ...}`, Micro returns flat object. Logged for Phase 2 review.
- 🟠 P1: **F28 NOT wired into BT routes (all 4 systems).** User ran Gold Micro BT from UI — got pre-F28 numbers. Verified: all 4 BT routes call `run_backtest()` without `bias_mode` kwarg → engine defaults to `"production"`. Live scheduler IS correctly reading `BIAS_MODE` (live unaffected). BT dashboard shows production regardless of env var. This is M1 from `docs/FILTER_28_AUDIT_BACKLOG.md` — known audit item, NOT a new bug. Parked in `ideas/IDEAS.md`. **Discipline test: passed — did NOT fix on Day 1 even though "30min" and "I already know how."**
- 🟠 P1: **DB pnl_usd excludes swap (overnight financing).** OIL-MI-ac215cc6: DB shows −$360, JM web shows −$367.20 (−$7.20 swap). Daily reconcile (DB-sum vs wallet-Δ) will drift on overnight trades by swap amount. Phase 3 candidate.
- 🟠 P1: **Double EXIT_FILLED journal events** for OIL-MI-ac215cc6 — likely OnTradeTransaction + scanner-detected exit firing duplicate. Check if `gd_trades` row was double-inserted. Same bug class as June 15 dedup audit.
- 🟡 P2: **Oil Micro losing streak — 2W/5L net −$1,606 over last 7 trades.** Includes today's trade. Could be regime mismatch, Filter #27 fill distribution change, or F28 letting through trades V1+V2 would have filtered. Track all Oil Micro trades closely in Phase 1.

### Discipline tests passed today
1. **F28 not wired in BT** — known audit M1, "30min fix, I know how" — parked, not fixed
2. **Swap reconcile gap** — small ergonomic fix — parked, not fixed
3. **Double EXIT_FILLED journal** — bug-class — parked, not fixed
4. **F30 parallel research temptation** — "different branch, no ship" rationalization — pushed back by AI, user held the line. Bible Trap #2 caught and resisted.

### 🚨 Discipline VIOLATION — Day 1 freeze broken
**Time:** ~16:00 IST 2026-06-18
**Trigger:** Oil Micro capped 3/3 with 1 fill + 2 TTL_EXPIRED. User reframed cap-block as "money bleeding."
**Override:** User explicitly chose "override fully" after AI declined twice and offered Option 1 (track and observe) and Option 2 (Oil Micro only).
**Action:** Modify cap counter logic across all 4 systems so LIMIT_TTL_EXPIRED does NOT count toward `max_trades_per_day`.
**Bible status per DISCIPLINE_PLAN_30DAY.md:**
> "If any of these happen, **don't quit the challenge — restart that phase**."

**Decision:** Reset Phase 0 to Day 0. The freeze experiment is invalidated. Re-baseline tomorrow as Day 1 (Jun 19).
**Evidence trail:** see commit history + this entry.
**Pattern noted:** This is the second multi-stage opt-in override in 24hrs (F28 all-4 was the first). [[feedback-user-explicit-opt-in]] memory documents the trend.
- 🟡 P2: F30 (SMC PDH/PDL bias) and F31 (DXY anti-correlation Gold-only) research docs already exist. Resist temptation to start BT sweep before Phase 3.
- 🟡 P2: F29 (bar-aware BE check) — needs live BE_PROGRESS journal events. Could begin Phase 1 instrumentation if it adds zero strategy logic. **Decision: park, instrumentation can wait until Phase 3 ship slot.**

### P0 events (rare)
- 🔴 None.

### Evening close (target: 10 min)
- **JM wallet (today close):** _<fill at end of day>_
- **Today delta:** _<fill>_
- **Trades count:** _<N (W/L)>_
- **Postmortem coverage:** _<N/N — target 100%>_
- **Daily ritual completed:** _<✅ / ❌>_
- **Hours spent on Hand of Midas:** _<Xh — cap 3h>_
- **Laptop closed at:** _<HH:MM IST>_

### One-line verdict for the day
> _<fill at end of day>_

---

_(Subsequent days append here, newest at top)_
