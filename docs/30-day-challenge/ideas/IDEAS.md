# Ideas Parking Lot — 30-Day Challenge

> P2 thoughts. Park here. **DO NOT ACT during freeze (Phase 0–2).**
> Re-read at Phase 2 (Decide, Day 15–21) for ranking.

---

## Format

```markdown
### YYYY-MM-DD — <one-line idea title>
- **Phase noticed:** Phase X, Day N
- **Source:** postmortem / observation / chat / external read
- **Cost to investigate:** <1hr / 1d / 1wk>
- **Why it matters:** <1-2 sentences>
- **Why I'm not acting now:** <freeze rule / not enough data / unclear edge>
```

---

## Inherited from pre-challenge (carried over)

### 2026-06-17 — F30: SMC PDH/PDL bias replacement
- **Phase noticed:** Pre-challenge
- **Source:** F28 research raised "what's a smarter bias signal?" — SMC liquidity-sweep concept
- **Cost to investigate:** ~5hr BT sweep + research write-up
- **Why it matters:** F28 disable was net-positive. SMC bias may beat both V1+V2 and neutral.
- **Why I'm not acting now:** Phase 0 freeze. Research doc exists at `docs/FILTER_30_SMC_BIAS_RESEARCH.md`.

### 2026-06-17 — F31: DXY anti-correlation confirmation (Gold-only)
- **Phase noticed:** Pre-challenge
- **Source:** External read on Gold's USD-denominated math
- **Cost to investigate:** ~3hr BT sweep
- **Why it matters:** If DXY moves up ≥ X bps in N minutes, suppress Gold LONG entries.
- **Why I'm not acting now:** Phase 0 freeze. Parked behind F30. Doc at `docs/FILTER_31_DXY_CONFIRMATION_RESEARCH.md`.

### 2026-06-17 — F29: Bar-aware BE check
- **Phase noticed:** Pre-challenge (GD-AL-4af2d62d postmortem)
- **Source:** Trade reached 60.8% to TP but BE never armed
- **Cost to investigate:** Phase 1 instrumentation (~1hr) + BT sweep (~2hr) after data collected
- **Why it matters:** If BE-arm logic is missing fast moves, every winning trade loses optionality.
- **Why I'm not acting now:** Need live BE_PROGRESS journal events first. Defer to Phase 3 ship slot if data warrants.

### 2026-06-17 — Backend `is_latest` race + `/backtest/latest` API drift
- **Phase noticed:** Day 1 (Jun 18 night) frontend crash investigation
- **Source:** Concurrent BT runs from UI raced UPDATE statement → 0 rows with is_latest=TRUE
- **Cost to investigate:** ~30min — single-row enforcement via tx + unify wrap shape across 4 services
- **Why it matters:** Frontend crashed. Workaround shipped (commit b014083). Real fix deferred.
- **Why I'm not acting now:** P1, not bleeding. Phase 3 ranking candidate.

### 2026-06-17 — F28 audit Phase 2 items (H4/M1/M2/M3/M5)
- **Phase noticed:** Pre-challenge
- **Source:** Sherlock audit of F28 ship
- **Cost to investigate:** ~90min total
- **Why it matters:** H4 (BIAS_MODE re-read at scan time) enables hot-flip without restart. M5 (single-seed disclaimer) is honesty about validation strength.
- **Why I'm not acting now:** Phase 0 freeze. None are bleeding. Phase 3 ranking candidate.

---

## Phase 0 ideas (Days 1–7)

_(append below as ideas arise — DO NOT ACT)_

### 2026-06-18 — 🟡 P2: should LIMIT_TTL_EXPIRED count toward max_trades_per_day?
- **Phase noticed:** Phase 0, Day 1
- **Source:** Oil Micro hit 3/3 cap today via 1 SL + 2 TTL_EXPIRED. Locked out for the day even though only 1 actual trade was taken.
- **Cost to investigate:** Phase 2 review of cap counter logic in scheduler. Possibly per-system tunable.
- **Why it matters:** TTL_EXPIRED = no risk taken. Treating them as "trades" against the cap penalizes F27 (limit-order discipline) — a market-order strategy taking 3 SL hits would have used the same cap but ate $1k+ in losses. Limits saved that risk and STILL got capped.
- **Counter-argument:** if we don't count TTL_EXPIRED, signal-spammy days could blow through the intended attempt budget. Need to think about WHAT the cap protects.
- **Why I'm not acting now:** Phase 0 freeze. Phase 3 ranking candidate. Track over 30 days how often TTL_EXPIRED contributes to lockout.

### 2026-06-18 — 🚨 P0-CANDIDATE: PHANTOM BE arm — `trigger_price=$77.67` recorded when real M1 LOW was $78.00
- **Phase noticed:** Phase 0 build week, Day 1 (OIL-MI-1310e9cd postmortem)
- **Source:** Journal `BREAK_EVEN trigger_price=77.67` at 15:12:02 CEST. User ran MQL5 `CopyRates` on BRENT.ecn M1 for the trade window (14:18-15:17 CEST):
  - `M1 [60 bars]: HIGH=78.5300 at 14:34, LOW=78.0000 at 15:17`
  - **Lowest tick during entire trade window = $78.00.** Never reached $77.77 (30% to TP), never reached $77.72 (35% BE threshold), never reached $77.67 (logged trigger).
- **What this means:** scheduler's `price["ask"]` returned $77.67 when actual broker ASK was $78.02+. **The BE-arm check fired on a phantom price.** SL was modified to $78.06 (entry−$0.01) under conditions that should NOT have triggered BE arm.
- **Smoking-gun evidence:** journal shows trigger_price 33 cents below ACTUAL minimum recorded by broker M1 OHLC.
- **Why this is P0-candidate (not P0):** Money didn't bleed today (trade closed +$3 by accident — see below). But ANY F5 BE save in 24hr is potentially built on this same phantom-tick mechanism. Statistical foundation of F5 metrics is shaky.
- **Cost to investigate:** Audit `price["ask"]` source in `backend-oil-micro/scanner/live_engine.py:752`. Is it MT5 live tick (DWX live_prices) or stale OANDA cache or REST poll lagging?
- **Cost to fix:** ~30min once root cause known. Likely: replace OANDA stream tick with DWX live tick file.
- **Why I'm not acting today:** Phase 0 build week, marathon-fatigue risk. Investigate Mon Jun 22 BEFORE freeze starts.
- **Track:** every BE event for next 7 days, log scheduler-recorded ask vs MT5 M1 LOW for the trade window. If pattern repeats → root cause confirmed.

### 2026-06-18 — 🚨 P0-CANDIDATE: SHORT BE-SL math creates wrong-side SL — fires as profit-target not stop-loss
- **Phase noticed:** Phase 0 build week, Day 1 (OIL-MI-1310e9cd postmortem after MQL CopyRates proof)
- **Source:** `backend-oil-micro/scanner/live_engine.py:754` for SHORT path: `new_sl = entry - 0.01`
  - For SHORT entered at $78.07, this places SL at $78.06 — **BELOW entry**.
  - For a SHORT position, broker SL fires when ASK rises to SL level. SL below entry is on the WRONG side — broker either rejects OR interprets as a profit-target.
  - Actual behaviour observed: JM accepted the SL=78.06 modification, then closed the position when BID drifted DOWN through $78.06 (price went toward TP, hit BE level, exit).
- **MQL5 proof of the actual price path:**
  - HIGH $78.53 at 14:34 (16min after entry — price went UP $0.46 against SHORT)
  - LOW $78.00 at 15:17 (exit moment — price drifted DOWN to entry zone)
  - Trade NEVER got to 30% TP, NEVER tested original SL $78.64
- **Effect:** the "BE save" that recorded +$3 was actually broker firing a profit-target, not a real BE protective stop. Same code on a LONG trade would correctly place SL below entry as protective stop. **The SHORT branch math is symmetric-but-wrong.**
- **Counterfactual cost:** without the buggy BE modify, original SL $78.64 stays — never tested (M1 HIGH only reached $78.53). Trade rides through to TP $77.07 (hit at chart-time ~16:00+). **+$303 instead of +$3 = $300 cost from this bug on this single trade.**
- **Cost to fix:** ~10min — confirm intent (profit-lock at entry-pip, OR protective stop slightly above entry?) and adjust `new_sl` formula for SHORT branch.
- **Cost to verify:** rerun BT with corrected formula, compare to F5 baseline. Some win-trades become bigger wins, some loss-trades become bigger losses.
- **Why P0-candidate not P0:** today the bug accidentally produced +$3 instead of −$170 (full SL). Bug + price-direction-luck = small profit. Could go either way next time.
- **Why I'm not acting today:** Phase 0 build week. Need careful diff + BT verification — no rushed fix. Investigate Mon Jun 22.

### 2026-06-18 — 🟠 P1: F29 (bar-aware BE) — BUMPED to highest priority Phase 3 candidate
- **Phase noticed:** Phase 0 build week, Day 1 (OIL-MI-1310e9cd evidence)
- **Source:** This trade + GD-AL-4af2d62d (Jun 17) = 2 examples in 24hr where intra-bar tick fires BE before bar close confirms direction.
- **Distinct from the 2 P0-candidates above:** F29 is about WHEN to arm BE (wait for bar close), not WHAT price triggers it (phantom tick) or HOW SL is set (wrong-side math).
- **Cost to investigate:** F29 research doc at `docs/FILTER_29_BAR_AWARE_BE_RESEARCH.md`. BT sweep + variant comparison ~3hr.
- **Why I'm not acting now:** Phase 0 freeze. Bigger leverage — fix the BE phantom + math bugs FIRST before sweeping F29 variants. Otherwise BT and live diverge.

### 2026-06-18 — 🟠 P1: postmortem.py R:R uses BE-adjusted SL
- **Phase noticed:** Phase 0, Day 1 (postmortem OIL-MI-08b725d3)
- **Source:** Trade with BE-armed shows R:R 100:1 because script reads `gd_trades.sl` AFTER BE adjustment ($79.02). Original SL was $79.38 → real R:R 2.86:1.
- **Cost to fix:** ~30min — track original SL separately in gd_trades or read from journal LIMIT_PLACED event.
- **Why it matters:** Postmortem header math is wrong for any BE-armed trade. Misleading R:R reading.
- **Why I'm not acting now:** Phase 0 freeze. Workaround: when verdict shows R:R >10, re-derive from journal LIMIT_PLACED.

### 2026-06-18 — 🟠 P1: BE 50% TP threshold mismatch
- **Phase noticed:** Phase 0, Day 1 (postmortem OIL-MI-08b725d3)
- **Source:** BE armed at trigger_price=$78.68 (~36% to TP) but postmortem says "50% TP $78.5300 NEVER reached." Either BE threshold is configured below 50% (likely Filter #5 lowered it to 35%) OR BE math uses different price reference.
- **Cost to fix:** ~30min — confirm threshold via Oil Micro config + fix postmortem.py if it just reads wrong threshold.
- **Why it matters:** Postmortem header confidently states "BE NEVER reached" while logs show BE armed. Confusing forensics.
- **Why I'm not acting now:** Phase 0 freeze. Confirm in Phase 1 by reading Oil Micro `MICRO_ALPHA_SWEEP_OIL` config block.

### 2026-06-18 — 🟠 P1: GD-MI-2b152d33 fired with R:R 1.17 — entry gate too permissive?
- **Phase noticed:** Phase 0, Day 1 (postmortem GD-MI-2b152d33)
- **Source:** Gold Micro SHORT entered with R:R 1.17. At Gold Micro's recent ~30% WR, R:R 1.17 is structurally unprofitable. Strategy spec says R:R should be 2.5+.
- **Cost to investigate:** ~1hr — read scheduler entry path, check for min-R:R gate, audit historical trades for similar low-R:R fires.
- **Why it matters:** If strategy is firing low-R:R setups regularly, that's silently eroding edge. Could be the explanation for some Gold Micro losses.
- **Why I'm not acting now:** Phase 0 freeze. Track R:R for every Gold Micro trade Phase 1. If pattern holds → Phase 3 ranking candidate as "min R:R gate" filter.

### 2026-06-18 — 🟠 P1: postmortem.py http_get missing auth header
- **Phase noticed:** Phase 0, Day 1 (backfilling yesterday's postmortems)
- **Source:** Oil Macro trades return HTTP 404 from script. Manual curl WITH auth header returns 200. `scripts/postmortem.py:66 http_get()` does NOT add `Authorization: Bearer` token.
- **Cost to fix:** ~2min — add `Authorization` header from env var
- **Why it matters:** Postmortem skill is the foundational measurement tool of the 30-day challenge. Half-blind to Oil Macro right now. Workaround = hand-write Oil Macro postmortems via curl.
- **Why I'm not acting now:** Phase 0 freeze. Script bug, not a strategy bug. Phase 3 ranking candidate or "just fix when it next breaks me."

### 2026-06-18 — 🟠 P1: DB pnl_usd excludes overnight swap
- **Phase noticed:** Phase 0, Day 1 (postmortem OIL-MI-ac215cc6)
- **Source:** JM web shows −$367.20, DB shows −$360.00. Diff = −$7.20 swap.
- **Cost to fix:** ~30min — add `swap_usd` column to `gd_trades`, populate from MT5 close event, include in `pnl_usd` OR keep separate.
- **Why it matters:** Daily reconcile (DB pnl-sum vs wallet Δ) drifts on overnight trades. Will create false bug-smell flags during 30-day challenge.
- **Why I'm not acting now:** Phase 0 freeze. Workaround: in DAILY_LOG, track BOTH numbers. Reconcile gap = swap, document in evening close.

### 2026-06-18 — 🟠 P1: Double EXIT_FILLED journal events
- **Phase noticed:** Phase 0, Day 1 (postmortem OIL-MI-ac215cc6)
- **Source:** Two `EXIT_FILLED` journal rows at 01:26:00 UTC for the same trade (different context strings — one with `pnl_gbp`, one without).
- **Cost to fix:** ~1hr — investigate scheduler vs OnTradeTransaction race.
- **Why it matters:** Same bug class as June 15 dedup audit. May or may not double-insert `gd_trades` row.
- **Why I'm not acting now:** Phase 0 freeze. Verify in Phase 1: query `SELECT COUNT(*) FROM gd_trades WHERE trade_ref=...` — if 1, journal-only duplicate (annoying not bleeding). If 2, real bug.

### 2026-06-18 — 🟡 P2: Oil Micro losing streak — investigate in Phase 2
- **Phase noticed:** Phase 0, Day 1 (postmortem peers table)
- **Source:** OIL-MI-ac215cc6 + 6 prior = 2W/5L net −$1,606 over last 7 Oil Micro trades.
- **Cost to investigate:** Phase 2 review. If still drifting, Phase 3 ranking candidate.
- **Why it matters:** Could be regime mismatch / F27 fill distribution shift / F28 letting through reverse-bias trades.
- **Why I'm not acting now:** N=7 too small for verdict. Continue postmortems through Phase 1.

### 2026-06-18 — 🟠 P1: F28 NOT wired into BT routes (all 4 systems)
- **Phase noticed:** Phase 0, Day 1
- **Source:** User ran Gold Micro BT from UI, saw same numbers as pre-F28 → suspected F28 inactive in BT
- **Verified:** All 4 BT routes (`backend/routes/backtest.py`, `backend-oil/routes/backtest.py`, `backend-micro/routes/backtest.py`, `backend-oil-micro/routes/backtest.py`) call `run_backtest()` WITHOUT `bias_mode` kwarg → engine resolves `None → "production"` (via `resolve_bias_mode` in `backend/backtest/neutral_bias.py`) → V1+V2 bias filter ON.
- **Live impact:** ZERO. Live scheduler reads `BIAS_MODE` from config correctly. Live trades still fire under neutral (F28 active live).
- **BT impact:** BT dashboard shows production numbers regardless of `BIAS_MODE` env var. UI badge would say neutral but BT result is production. Misleading.
- **Cost to investigate:** Already investigated. Cost to fix ≈ 30min (4 route files: read `BIAS_MODE` from config, pass to `run_backtest`).
- **Why it matters:** Phase 2 (DECIDE) F28 verdict relies on BT-as-baseline comparison. If BT can't run neutral, comparison is harder.
- **Why I'm not acting now:** This is M1 from `docs/FILTER_28_AUDIT_BACKLOG.md` — already known, already scoped, already documented. Discipline test: parked even though it's "small" and "I already know how." Phase 3 ranking candidate.
- **Workaround during freeze:** Live data is the source of truth for F28 verdict, not BT. The 5-seed multi-seed BT validation already done (Path B clean kwarg) covers the BT-side evidence. BT dashboard mismatch is annoying, not blocking.

---

## Phase 1 ideas (Days 8–14)

_(append below as postmortems reveal patterns)_

---

## Phase 2 ranking (Day 15–21)

_(when Phase 2 begins, rank items above by frequency / severity / fixability / confidence)_

---

## Anti-patterns to watch for

- 🚫 Adding 5 ideas a day — that's not parking, that's planning. Limit to 1-2 high-signal items per day.
- 🚫 Writing the idea AND researching it — research is acting. Park, don't research.
- 🚫 "Just a quick BT" — every 5hr sweep is "quick" until it's done. Sweep cost = time + biases the data.
- 🚫 Bundling ideas — keep entries atomic. One idea per entry even if related.
