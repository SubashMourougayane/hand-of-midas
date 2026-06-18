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
| (TBD as trades close) | | | | | | | |

### Postmortems written
- [ ] (none yet — fill as trades close)

### Surprises / observations (P1/P2/P3)
- 🟠 P1: `is_latest` race condition in `gd_backtest_runs` → `/backtest/latest` returns `{result:null}` wrapper when no row has `is_latest=TRUE`. Frontend now guarded (commit b014083). Backend fix deferred to Phase 3 ranking.
- 🟠 P1: API drift between Macro and Micro `/backtest/latest` shape — Macro wraps in `{result: ...}`, Micro returns flat object. Logged for Phase 2 review.
- 🟠 P1: **F28 NOT wired into BT routes (all 4 systems).** User ran Gold Micro BT from UI — got pre-F28 numbers. Verified: all 4 BT routes call `run_backtest()` without `bias_mode` kwarg → engine defaults to `"production"`. Live scheduler IS correctly reading `BIAS_MODE` (live unaffected). BT dashboard shows production regardless of env var. This is M1 from `docs/FILTER_28_AUDIT_BACKLOG.md` — known audit item, NOT a new bug. Parked in `ideas/IDEAS.md`. **Discipline test: passed — did NOT fix on Day 1 even though "30min" and "I already know how."**
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
