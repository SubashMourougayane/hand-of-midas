# UI / Data Mismatch Audit — 2026-06-19

> **Trigger:** User reported "UI and data mismatch a lot — for example I can
> see same data in both backtest". This audit walks every page, captures
> screenshots, cross-checks rendered values against the actual DB + API
> responses.
>
> Done BEFORE proposed full DB wipe so no information is lost.

**Method:**
1. Playwright headless Chromium, logged-in session
2. Walked 16 pages, captured full-page screenshots → `docs/audit_2026-06-19_ui/*.png`
3. Captured rendered text → `docs/audit_2026-06-19_ui/rendered_text.txt`
4. Pulled live DB ground-truth via `/api/oil-micro/debug/exec/python`
5. Cross-referenced rendered values against API responses + DB rows

---

## DB ground-truth (current state, post-Macro-retirement)

### `gd_trades` — 74 total

| Prefix | System | Trades | Closed | Open | Total P&L | Wins | Losses | F27 unfilled |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `GD-AL-` | Gold Macro (retired) | 16 | 16 | 0 | -$71 | 4 | 5 | 0 |
| `GD-MI-` | Gold Micro | 28 | 28 | 0 | **-$2,079** | 7 | 14 | 5 |
| `OIL-AS` | Oil Macro (retired) | 16 | 16 | 0 | -$2,236 | 5 | 11 | 0 |
| `OIL-MI` | Oil Micro | 14 | 14 | 0 | -$1,912 | 3 | 6 | 5 |

### `gd_signals` — 82 total

| Strategy | N | Taken | Skipped |
|---|---:|---:|---:|
| `micro_alpha_sweep` | 33 | 21 | 12 |
| `alpha_sweep_oil` (Oil Macro retired) | 17 | 14 | 3 |
| `micro_alpha_sweep_oil` | 16 | 11 | 5 |
| `alpha_sweep` (Gold Macro retired) | 16 | 13 | 3 |

### `gd_journal` — **224,714 rows**

| Strategy | N |
|---|---:|
| `alpha_sweep_oil` (Oil Macro) | **208,541** ⚠️ |
| `alpha_sweep` (Gold Macro) | 12,480 |
| `micro_alpha_sweep` (Gold Micro) | 2,796 |
| `micro_alpha_sweep_oil` (Oil Micro) | 885 |
| `system` | 18 |

### `gd_backtest_runs` — 46 runs, **104,689 BT trades**

### `gd_traded_sweeps` — 96 entries (sweep dedup keys)

### `gd_dd_state` — 4 rows (one per system, IDs 1-4)

---

## Mismatch findings (severity-ordered)

---

### 🔴 M1 — `/trades` page renders IDENTICAL data on Gold Micro vs Oil Micro

**Evidence:**

| | `trades_micro.png` | `trades_oilmi.png` |
|---|---|---|
| Row count visible | 1,541 (paginated) | 1,541 |
| First row date | "20 May 2020" | "20 May 2020" |
| First row entry | $1547.6 | $1547.6 |
| Strategy column | All "alpha" | All "alpha" |
| Visual diff | Pixel-identical | Pixel-identical |

**Yet API responses are correctly system-distinct:**

```bash
$ curl /api/micro/trades?limit=5
27 returned, first trade_ref: GD-MI-a94ebe4a

$ curl /api/oil-micro/trades?limit=5
14 returned, first trade_ref: OIL-MI-16c2231b
```

**Root cause hypothesis:** the `/trades` page defaults to the BACKTEST tab
(see UI: "Backtest" toggle highlighted). Backtest data is shared across
systems in `gd_backtest_trades` table (104k rows from 46 runs). The
backtest endpoint may not be filtering by `?sys=`.

The "Live" toggle on the page should narrow to live trades — but the
default view (and what got screenshotted) shows BT trades from May 2020+
which is a single shared backtest dataset.

**Impact:** User can't tell which system's actual trades they're looking at.
Postmortem analysis becomes ambiguous. Same screenshot for both → data
overlap claim is real.

**Reference:** Screenshots at:
- `docs/audit_2026-06-19_ui/trades_micro.png`
- `docs/audit_2026-06-19_ui/trades_oilmi.png`

---

### 🔴 M2 — `/backtest` page renders IDENTICAL data on both Micros

**Evidence:**

| Field | `backtest_micro` | `backtest_oilmi` |
|---|---|---|
| Total P&L | **$343,196** | **$343,196** |
| Win Rate | 62.4% | 62.4% |
| Profit Factor | 5.42 | 5.42 |
| Max DD | -7.16 | -7.16 |
| N Trades | 1,191 | 1,191 |
| Yearly slice 2020 | identical | identical |
| Per-trade entry prices | $1645, $1632, etc. | $1645, $1632, etc. |

**The Oil tab shows GOLD prices.** $1645 is XAU territory; Oil should be
$40-90/barrel.

**Root cause hypothesis:** `latestBacktest()` endpoint
(`/api/${svc}/backtest/latest`) may be falling back to a shared cached run
when `?sys=oil-micro` is requested. OR the frontend is keying its render
state on a stale local var that doesn't refresh when the toggle changes.

**Reference:**
- `docs/audit_2026-06-19_ui/backtest_micro.png`
- `docs/audit_2026-06-19_ui/backtest_oilmi.png`

---

### 🔴 M3 — `/journal` page shows "No events yet" despite 224k DB rows

**Evidence:** Both `/journal?sys=micro` and `/journal?sys=oil-micro`
render "0 of last 100 — No events yet — System will log at next scheduled
scan (22:00 UTC or 08:00–10:30 UTC)."

**DB has:** 2,796 rows for Gold Micro + 885 rows for Oil Micro.

**API endpoint test:**

```
GET /api/micro/journal/events     → 200 OK   (Gold Micro has it)
GET /api/oil-micro/journal/events → 404      ❌ MISSING
GET /api/oil-micro/journal        → 200 OK   (this one works)
```

**Root cause:** `frontend/lib/client.ts:147` calls `journal/events`:
```typescript
journal<T>(params) {
  return authFetch<T>(buildUrl(`${this.base()}/journal/events`, params));
}
```

But `backend-oil-micro/main.py` mounts only `/journal`, not `/journal/events`.
Gold Micro's `backend-micro/routes/journal.py` happens to expose both paths;
Oil Micro has only the bare `/journal`.

**Impact:** Oil Micro journal page is permanently empty. Gold Micro may also
be affected depending on filter behavior.

**Fix:** add `/journal/events` route in `backend-oil-micro/routes/journal.py`,
OR update `client.ts` to use `/journal` (matching what both Micros expose).
Latter is one-line.

---

### 🟠 M4 — `/settings` page shows retired strategies + wrong broker

**Evidence (`settings_micro.png`):**
- Header: **"GoldDigger — Strategy parameters"** (system-name hardcoded; should be "Gold Micro")
- Risk Allocation table lists 3 strategies:
  - Alpha-Sweep · 4% · 100 oz
  - **Mean-Rev · 3% · 100 oz** ← retired Macro-era strategy
  - **Cross-Market · 2% · 100 oz** ← retired Macro-era strategy
- Mean-Rev panel shows full config (Condition 1/2 thresholds, SL multiplier, max hold 5 days, "Long only")
- Cross-Market panel shows full config (Consensus, return threshold, weights "EUR:2 US10Y:3 SPX:1 Ag:2 Oil:1 US2Y:2")
- **OANDA CONNECTION panel** with Account `101-004-39331014-001`, Type `Practice (Demo)`, Backend port `5053`
  - 5053 is **Gold Macro retired**
  - Live broker is **JustMarkets via DWX/MT5**, NOT OANDA

**Root cause:** Settings page is hardcoded with fields from the original
Gold Macro era. Never updated for:
- Phase 6 retirement of mean_rev + cross_market
- Migration to MT5/DWX/JustMarkets
- Per-system config (Oil Micro should show different values — Oil's 0.33 min range, etc.)

**Reference:** `docs/audit_2026-06-19_ui/settings_micro.png` and
`settings_oilmi.png` (also 100% Gold-coded).

---

### 🟠 M5 — Home page hero shows pre-retirement aggregate numbers

**Evidence (`home.png`):**
- Hero: "**$4.74M** 21-yr backtest P&L"
- Sub: "**$4.74M** total · — profit factor · 71.6% win rate · 10,479 trades"

**Should be (post-retirement, per /deck after our fix earlier today):**
- $3.50M / 6,557 trades / 76.4% WR (Micros only)

**Profit Factor field shows "—" (em-dash)** — backtest.json missing aggregate
PF for the new "Micros only" subset. Before retirement it was 4.6x.

**Root cause:** `frontend/lib/data/backtest.json` was last computed with all
4 systems. Today's commit `00beed3` updated `/deck` page numbers manually
but NOT the underlying `backtest.json` aggregate row. Home page reads
from `backtest.json` directly.

**Reference:** `docs/audit_2026-06-19_ui/home.png`

---

### 🟠 M6 — DD-state row 2 has wrong system mapping

**Evidence from DB:**
```
id=1 equity=$8,821 (peak $8,927)  updated 2026-06-17  ← what system?
id=2 equity=$5,466 (peak $8,345)  updated 2026-06-19 07:08
id=3 equity=$8,345 (peak $8,345)  updated 2026-06-19 12:16
id=4 equity=$8,345 (peak $8,345)  updated 2026-06-19 07:08
```

**Issue:** No clear mapping between `gd_dd_state.id` and which system owns
which row. The schema doesn't carry a `system` column on this table. Live
NAV per-system query joins by id positionally (id=1 → ?, id=2 → Gold Micro?
id=3 → Oil Micro?). The id=2 row showing equity $5,466 vs peak $8,345 is
out-of-line with reality (live NAV is $8,637 per state API).

**Impact:** The "Equity MA halving" gate (Phase 6 #6 fix) reads from this
table. If any system reads the wrong id, the gate fires incorrectly.

**Status:** This needs a separate investigation — not necessarily a UI bug,
but a data-model concern. Don't ship a DB wipe before resolving.

---

### 🟡 M7 — Live page (Gold Micro) shows pre-Phase-6 stats banner

**Evidence (`live_micro.png`):**
- "**$4,150.54** Booked $0" badge
- "**ACCOUNT NAV $8,637**"  ✅ matches /api/micro/state
- "**0 OPEN POSITIONS**" ✅ matches DB
- "**DD PROTECTION: Clear**" ✅ matches gd_dd_state
- "Recent Closed Trades" table with 9 entries — all show "alpha" badge
- "Recent Signals" table — 9 entries

✅ **Mostly matches the DB.** No major mismatch beyond minor labeling.

---

### 🟡 M8 — Live (Oil Micro) shows wrong "DD Protection: 1 losses"

**Evidence (`live_oilmi.png`):**
- "DD PROTECTION: **1 losses** Streak 1, Equity $8,637"

But DB has 4 dd_state rows; the one tied to Oil Micro likely shows
`consecutive_losses=1`. Check is OK if mapping correct, but combined
with M6 (no system column) the displayed number's accuracy is uncertain.

---

### 🟡 M9 — Heavy gd_journal bloat — 208k rows for retired Oil Macro

**Evidence:**
- `alpha_sweep_oil` (Oil Macro, RETIRED today) has **208,541 journal rows**
- Other 3 systems combined: 16,179 rows

**Why so many:** Oil Macro started 2026-05-22. Macro scheduler logged 1
SCAN_TICK event every 3 min × 24/7 × 28 days = ~13,440 scan events. Plus
sweep-tracking, signal-skip reasons, etc. The 208k figure suggests way
more event types (likely also DEBUG-level scan-status writes).

**Impact:** None today (event_type index is fine). But:
- Future schema changes have to migrate 208k rows
- Debug queries on `gd_journal` slow down without filters
- Dashboard "events" pages may be slow if no LIMIT

**This is a candidate for the proposed wipe.**

---

## Summary of mismatches

| # | Severity | Page/Area | Issue | Cause |
|---|---|---|---|---|
| M1 | 🔴 | `/trades` | Identical data both Micros (same BT) | Backtest tab default; sys filter not applied |
| M2 | 🔴 | `/backtest` | Identical data, Oil shows Gold prices | `latestBacktest()` returns shared cache |
| M3 | 🔴 | `/journal` | "No events yet" despite 224k rows | Oil Micro missing `/journal/events` route → 404 |
| M4 | 🟠 | `/settings` | Mean-Rev + Cross-Market shown; OANDA panel | Page hardcoded for original Gold Macro era |
| M5 | 🟠 | `/` (home) | Hero shows $4.74M / 4-systems numbers | `backtest.json` not regenerated for Micros-only |
| M6 | 🟠 | DD state | No `system` column → ID-positional mapping | Schema design oversight |
| M7 | 🟡 | `/live?sys=micro` | Mostly OK, minor labels | — |
| M8 | 🟡 | `/live?sys=oil-micro` | DD streak — uncertain mapping | M6 manifestation |
| M9 | 🟡 | gd_journal | 208k retired-Macro rows | Macro logging never bounded |

---

## Recommendation re: proposed DB wipe

You asked: "delete all signals, trades so far happened from db even backtest trades — before doing so check if all PNL, trades page, journal page and all is wired up with proper data".

**Answer: NO, not yet.** Wiping now will mask 4 real frontend bugs that
need fixing first:

| Mismatch | Wipe helps? | Why |
|---|---|---|
| M1 (trades same on both Micros) | ❌ No | Backtest filter still broken; would still show same data after wipe |
| M2 (backtest same / Oil shows Gold prices) | ❌ No | Endpoint key bug, not data bug |
| M3 (journal empty) | ❌ No | 404 on Oil Micro `/journal/events` route — wipe doesn't fix |
| M4 (settings shows retired strategies) | ❌ No | Hardcoded UI; data-independent |
| M5 (home shows $4.74M) | ❌ No | `backtest.json` regen needed |
| M6 (DD state mapping) | Partial | Wipe + add `system` column would help |
| M9 (journal bloat) | ✅ Yes | Removing 208k Macro rows is the wipe's main win |

## Two-stage proposal

**Stage A (1-2 hours, BEFORE wipe):** fix M1, M2, M3, M4, M5

1. **M3 fix (5 min):** add `/journal/events` route in
   `backend-oil-micro/routes/journal.py`, mirror Gold Micro's. OR change
   `client.ts:147` to use `/journal` (one-liner, simpler).
2. **M1 + M2 fix (~30 min):** debug why `?sys=` query param isn't
   propagating to API calls on `/trades` and `/backtest` pages. Likely
   InstrumentProvider state issue when reading from URL.
3. **M4 fix (~30 min):** `frontend/app/settings/page.tsx` rewrite —
   per-system config panels, MT5/DWX broker info instead of OANDA, drop
   Mean-Rev + Cross-Market.
4. **M5 fix (~10 min):** regenerate `frontend/lib/data/backtest.json`
   aggregate from latest BT runs (Micros only).

**Stage B (DB wipe, AFTER A is verified):**

```sql
TRUNCATE gd_signals;
TRUNCATE gd_traded_sweeps;
TRUNCATE gd_journal;
TRUNCATE gd_trades CASCADE;
TRUNCATE gd_backtest_trades;
TRUNCATE gd_backtest_equity;
TRUNCATE gd_backtest_runs CASCADE;
DELETE FROM gd_dd_state;  -- preserve schema
INSERT INTO gd_dd_state DEFAULT VALUES;  -- one fresh row per system
```

**Caveats for Stage B:**
- Open MT5 positions: confirm none open on broker before wiping
- Sequences: PostgreSQL auto-resets on TRUNCATE
- Audit trail loss: 224k journal rows, 74 trades, 46 BT runs — irreversible
- Sessions table: NOT wipe (would log everyone out, including admin)
- Users table: NOT wipe

---

## Files referenced

- Screenshots: `docs/audit_2026-06-19_ui/*.png` (16 pages)
- Rendered text: `docs/audit_2026-06-19_ui/rendered_text.txt`
- DB ground-truth: gathered via `/api/oil-micro/debug/exec/python` (snapshot inline above)

## Next step

User reviews this doc + screenshots. Sign off → I fix M1-M5 (Stage A),
re-verify with another Playwright walk, then we proceed to Stage B wipe
with full alignment.
