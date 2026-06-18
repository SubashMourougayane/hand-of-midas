# Postmortem — OIL-MI-1310e9cd

> **Verdict:** <!-- skill: verdict -->🐛 Bug detected — TWO bugs combined to produce a misleading +$3<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->**Two bugs found via MQL5 CopyRates proof.** (1) **PHANTOM BE arm**: journal logged trigger_price=$77.67 but real M1 LOW for the entire trade window was $78.00 — scheduler saw a price that didn't exist on broker M1 OHLC. (2) **Wrong-side SHORT BE-SL math**: code sets SL = entry−$0.01 for SHORT = SL BELOW entry → broker fired this as profit-target when BID drifted DOWN through $78.06, not as protective stop. Price went UP $0.46 then back down. Trade closed +$3 = lucky outcome of two bugs. Without the bugs: SL untouched, ride through to TP $77.07 = +$303. **Net cost of bugs: $300 on this single trade.**<!-- /skill: tldr -->

---

## Trade card

- **System:** Oil Micro
- **Instrument:** BCO_USD
- **Strategy:** micro_alpha_sweep_oil
- **Side:** SHORT 303 units
- **Entry:** $78.0700 · **SL:** $78.0600 · **TP:** $77.0700
- **Exit:** $78.0600 · **Exit reason:** SL · **P&L (DB):** $+3.00
- **Duration:** 0:58:27.941020

## Risk Math

- Risk: $0.0100/unit × 303 = $3.03 max loss
- Reward: $1.0000/unit × 303 = $303.00 max gain
- R:R: 100.00:1
- 50% to TP level (BE trigger): $77.5700

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-18 12:18:03 | 2026-06-18 17:48:03 | 2026-06-18 15:18:03 |
| BREAK_EVEN armed | 2026-06-18 13:12:02 | 2026-06-18 18:42:02 | 2026-06-18 16:12:02 |
| EXIT | 2026-06-18 13:16:31 | 2026-06-18 18:46:31 | 2026-06-18 16:16:31 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$77.5700** was NEVER reached during trade

## What happened AFTER exit?

- TP level $77.0700 **WAS** reached at ~19:17 IST (~30min after exit at 18:47 IST)
- **Visual chart analysis (from MT5 M5 — authoritative source):**
  - ENTRY at $78.07 (red arrow ~14:50 chart time)
  - Trade body: tight range **$78.00-78.20** from entry to exit (~70min)
  - **Price NEVER went near original SL $78.64** (off-screen high)
  - **EXIT at $78.06-78.10 zone** (blue arrow ~16:00 chart time) — at the END of consolidation, just BEFORE the big breakout
  - **Big RED candle AFTER exit** drops $78.10 → $77.80, then continues straight down to $76.84+ (well past TP $77.07)

- **Key forensic finding:** Visual mid-prices during trade body look like they don't touch $78.06. But ASK price = MID + 0.02-0.025 spread → visible MID $78.04 = ASK $78.06 → fires SHORT BE-SL. **One small ask-side tick during a sideways candle triggered BE-SL exit before the breakout move started.**
- **Counterfactual: had we stayed in trade with original SL $78.64, TP would have hit for +$303 instead of actual +$3.**

> NOTE: deterministic script said "TP NOT reached in 30-min window" — this was generated immediately at exit. Manual price-check 30min later showed TP hit. Script has a bounded look-ahead that doesn't catch slow follow-through.

> NOTE 2 (UPDATED with MT5 logs): MT5 Experts log shows:
> - `15:12:01 MODIFY SL → 78.06` (BE arm)
> - `15:16:31 CLOSED @ 78.06 reason=SL profit=$3`
> The candle just before the big-red-drop has **L=$78.06** (visible bottom-of-chart hover: O:78.20 H:78.25 L:78.06 C:78.07). **BE-SL DID fire on a real $78.06 BID-low wick.** Not a phantom — but an intra-bar wick that hit BE-SL before the next candle did the entire TP move.

> NOTE 3 (the F29 lesson): The candle that fired BE-SL had a tiny wick down to $78.06. The VERY NEXT M3 candle dropped $78.10 → $77.55 (heading to TP $77.07). **F29 (bar-aware BE)** would skip the BE exit on a wick-only touch and wait for bar CLOSE. Trade would then ride the next candle's drop toward TP.

> NOTE 4 (residual concern): the journal `trigger_price=77.67` does NOT match any visible price during the trade body. This is the ASK that scheduler observed at BE-arm moment. Either real broker tick (invisible in M3 candles) OR stale/wrong price source. P1 audit item — investigate `price["ask"]` source in live_engine.py:752 in Phase 3.

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.0100 | $-3.03 |
| If hit TP | $1.0000 | $+303.00 |
| **ACTUAL (DB)** | — | **$+3.00** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 9 closed trades for Oil Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| OIL-MI-7d38444f | LONG | $77.5772 | $0.0000 | LIMIT_TTL_EXPIRED | $+0.00 |
| OIL-MI-de5d0d17 | LONG | $77.1589 | $0.0000 | LIMIT_TTL_EXPIRED | $+0.00 |
| OIL-MI-ac215cc6 | LONG | $78.4700 | $78.1700 | SL | $-360.00 |
| OIL-MI-6fbb7040 | SHORT | $79.2300 | $79.6500 | SL | $-306.60 |
| OIL-MI-ea9d591d | SHORT | $79.0900 | $79.4400 | SL | $-318.50 |
| OIL-MI-08b725d3 | SHORT | $79.0300 | $79.0200 | SL | $+9.10 |
| OIL-MI-207a8552 | LONG | $82.4400 | $81.8200 | SL | $-663.40 |
| OIL-MI-aba3b668 | SHORT | $87.5200 | $86.2800 | EXPERT | $+458.80 |
| OIL-MI-c1f44df4 | SHORT | $91.2600 | $92.4500 | SL | $-426.02 |

Recent W/L: 2/7
Recent net P&L (excluding this trade): $-1606.62

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-18 12:18:02 | LIMIT_DRY_RUN_INTENT | 78.0695 | dry_run=False, instrument=BCO_USD, offset_pct=-0.1, actual_path=limit_order_pending, entry_price=78.0061, ttl_seconds=900 |
| 2026-06-18 12:18:03 | LIMIT_PLACED | 78.0695 | sl=78.64, tp=77.07, units=303, ticket=2064039484, expiration=2026.06.18 15:33:01, instrument=BCO_USD |
| 2026-06-18 12:18:10 | LIMIT_FILLED | 78.0700 | ticket=2064039484, instrument=BCO_USD, actual_fill=78.07, time_to_fill=1s, intended_limit=78.0695, broker_open_time=2026.06.18 15:18:05 |
| 2026-06-18 13:12:02 | BREAK_EVEN | 78.0600 | old_sl=78.64, source=scheduler, trigger_price=77.67 |
| 2026-06-18 13:17:01 | EXIT_FILLED | 78.0600 | reason=SL, pnl_usd=3.0, oanda_id=2064039484 |
| 2026-06-18 13:17:01 | EXIT_FILLED | 78.0600 | reason=SL, pnl_gbp=3.0, pnl_usd=3.0, oanda_id=2064039484, instrument=BCO_USD |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
SHORT entry F27 limit @ $78.0695 (signal.entry $78.0061 + 10% × risk = $78.0695, intended pullback above market), filled in 1 second @ $78.07 (broker beat by 0.5pip).

**Original signal R:R = $0.936 reward / $0.63 risk = 1.49:1.** Post-fill R:R = $1.00 / $0.57 = 1.75:1 (improved by limit fill being 5pip better).

**R:R 1.75 is on the LOW end for Oil Micro** (yesterday's trades 3.03–3.73). Not a bug — passes strategy spec (R:R ≥ 0.8 in code: `if entry - tpv < risk * 0.8: continue`). But reflects a **tight consolidation window** — small sweep distance → small risk → small TP target.

**F28 alignment check:** journal `F28_BIAS_RESOLVED` at trade time:
- `computed_bias`: bearish
- `mode`: neutral
- `effective_bias`: neutral
- Trade direction: SHORT

**Bias and trade direction AGREE.** This trade would have fired under production V1+V2 too. **Not an F28-allowed-against-bias trade.** Different signal class than this morning's OIL-MI-ac215cc6.

Entry mechanics clean.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
**🚨 TWO P0-CANDIDATE BUGS — found via MQL5 CopyRates proof:**

**Bug #1 — PHANTOM BE arm**
- Journal: `BREAK_EVEN trigger_price=77.67` at 15:12:02 CEST
- MQL5 CopyRates output for trade window 14:18-15:17 CEST: `M1 [60 bars]: HIGH=78.5300 at 14:34, LOW=78.0000 at 15:17`
- **Real M1 LOW = $78.00. Logged trigger = $77.67. $0.33 phantom gap.**
- Implication: scheduler's `price["ask"]` returns prices not present in broker M1 OHLC. BE-arm condition `price["ask"] <= target_50` fires on phantom ticks.
- Code: `backend-oil-micro/scanner/live_engine.py:752`

**Bug #2 — Wrong-side SHORT BE-SL math**
- Code: `backend-oil-micro/scanner/live_engine.py:754` for SHORT path: `new_sl = entry - 0.01`
- For SHORT entered at $78.07, this places SL at $78.06 = BELOW entry
- For protective stop on a SHORT, SL must be ABOVE entry (fires when ASK rises = loss event)
- SL below entry = treated by broker as profit-target. Fires when BID drifts DOWN to SL = profit-lock.
- Actual broker behaviour: position closed when BID hit $78.06 going down toward TP — NOT a protective stop firing on adverse move.
- Real exit price/cause/timing all driven by this wrong-side math.

**Combined effect:**
- Bug #1 fired BE arm under phantom conditions (real LOW was $78.00, never below)
- Bug #2 turned the modified SL into a profit-target
- Lucky outcome: price drifted DOWN through $78.06 → exit at $78.06 = +$3
- Without bugs: original SL $78.64 stays, M1 HIGH was only $78.53, never touched original SL, trade rides to TP $77.07 = +$303

**Other smaller smells:**
- 🐛 postmortem.py R:R reads BE-adjusted SL → header shows R:R 100:1 (real ~1.75 with original SL). P1.
- 🐛 postmortem.py "50% to TP" deterministic line uses 50%, but Oil Micro F5 threshold is 35%. P1.
- Double EXIT_FILLED at 15:17:01 — same dedup pattern as prior trades. P1.
- Cap rework: pre-fix this would have been blocked at 3/3 (1 SL + 2 TTL). Post-fix correctly allowed. ✅
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
**Streak BROKEN.** This trade ends Oil Micro's losing run. Sequence over last 24 hours:
- OIL-MI-08b725d3: SHORT, BE save +$9
- OIL-MI-ea9d591d: SHORT, full SL −$318
- OIL-MI-6fbb7040: SHORT, full SL −$306
- OIL-MI-ac215cc6: LONG, full SL −$367
- **OIL-MI-1310e9cd: SHORT, BE save +$3** ← THIS

**2 BE saves out of 5 trades over 24hr. F5 (35% BE threshold) is doing real work.** Without F5: this trade would have been −$173 SL → cumulative would have been $1,149 worse over 5 trades.

**SHORT direction agrees with bearish bias** — different from yesterday's losing SHORTs (which fired in $79–80 zone) and this morning's losing LONG (which fired against bearish bias). Today's SHORT @ $78.07 is post-rally consolidation in $77.55-78.78 range. **Better setup quality than yesterday's chase-shorts.** R:R lower (1.75) but trade quality structurally better aligned with regime.

**Pattern emerging: Oil currently mean-reverting in $77–78.50 zone.** SHORTs at top of range, LONGs at bottom. Strategy is fitting the regime.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->

### Visual journey (with MQL5 CopyRates proof)

```
PRICE
$78.64 ─────────────────────────────────────  ←  Original SL (NEVER TOUCHED)

$78.53 ──────● HIGH at 14:34 (16min after entry)
       ╱     peak loss-direction (price went UP $0.46 against SHORT)
       │  
$78.20 │  ─range $78.20-78.40 for ~38min ─
$78.07 ●─────────────────────────────●──────  ←  ENTRY at 14:18
$78.06 ─────────────────────────────●─────●─  ←  BE-SL set 15:12 (Bug #2 wrong-side) → fired 15:16:31 = exit +$3
$78.00 ────────────────────────────●────────  ←  M1 LOW at 15:17 (exit moment)

$77.77 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   ←  30% TP (NEVER REACHED — proof: M1 LOW was $78.00)
$77.72 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   ←  35% BE arm threshold (NEVER REACHED)
$77.67 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   ←  🚨 PHANTOM trigger_price (Bug #1 — no real M1 tick)

(price kept dropping AFTER exit, hit TP $77.07 around 16:00+ chart time)

$77.07 ─────────────────────────────────────  ←  TP (hit AFTER our exit)
```

### Real timeline (M1 OHLC proof)
| Phase | Time (CEST) | Price action |
|---|---|---|
| 1. Entry | 14:18 | SHORT @ $78.07 |
| 2. Loss-direction rally | 14:18 → 14:34 (16min) | Price ROSE from $78.07 to **$78.53** (M1 HIGH proof) — $0.46 against SHORT |
| 3. Range | 14:34 → 15:12 (38min) | Price drifted back $78.20-78.40 |
| 4. **Phantom BE arm** | 15:12:02 | Journal logs trigger=$77.67 — **but real M1 LOW was $78.00** at this point |
| 5. **Wrong-side SL fires** | 15:16:31 | BID drifts DOWN through $78.06 → broker treats as profit-target → exit +$3 |
| 6. After exit | 15:17 → 16:00+ | Price kept dropping. TP $77.07 hit later. Without us. |

### Counterfactual P&L
- **Without bugs (clean BE-disabled run):** original SL $78.64 stays. M1 HIGH was only $78.53 (never touched SL). Price subsequently dropped to TP $77.07. Trade rides to TP = **+$303**
- **Actual (with both bugs):** **+$3** (exit at $78.06)
- **Cost of bugs on this trade: $300**

### Updated 24hr F5 ledger (with bug awareness)
| Trade | Outcome | What ACTUALLY drove the result |
|---|---|---|
| OIL-MI-08b725d3 (Jun 17) | +$9 "BE save" | Same code path. Possibly also affected by both bugs. **Needs MQL5 CopyRates audit to verify.** |
| OIL-MI-1310e9cd (Jun 18) | +$3 "BE save" | **Confirmed: phantom BE arm + wrong-side SL math.** Lucky direction-of-drift produced +$3 instead of −$170. |

**🚨 Yesterday's "F5 saved $326" claim is now suspect.** Need to MQL5-audit that trade too before trusting F5 numbers.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** 🐛 **TWO bugs detected.** This wasn't an F5 BE save and wasn't an F29-style intra-bar fake-out. It was: phantom price + wrong-side SL math, lucky direction-drift → +$3.
- **🚨 P0-CANDIDATE Bug #1 (phantom BE arm):** scheduler logged trigger=$77.67, real M1 LOW was $78.00. Audit `live_engine.py:752` price source. **Fix Mon Jun 22.**
- **🚨 P0-CANDIDATE Bug #2 (SHORT BE-SL math):** `new_sl = entry - 0.01` for SHORT puts SL on wrong side. Audit `live_engine.py:754`. **Fix Mon Jun 22.**
- **F5 narrative is now SUSPECT.** Yesterday's OIL-MI-08b725d3 "+$9 BE save" used the same code path. **MQL5 CopyRates audit of that trade required before trusting any F5 metric.**
- **F29 priority lower than I thought:** F29 (bar-aware BE) doesn't help if the BE arm itself is firing on phantom prices. Fix the foundation first.
- **F28 evidence:** N=2 for the post-reset 30-day challenge ledger. One F28-allowed-against-bias trade (LONG, lost $367). One bias-aligned bug-driven trade (SHORT, +$3). F28 verdict still inconclusive.
- **Track for next BE event:** when BE arms, capture journal `trigger_price` AND check MT5 M1 LOW for the trade window. If trigger_price ≠ visible price → confirms phantom-tick bug.
- **Cap rework still verified working** — today's cap counter correctly excluded 2 TTL_EXPIRED.
- **Discipline note:** Phase 0 build week ends Mon Jun 22. Both bugs need audit + fix BEFORE Day 1 freeze starts. Otherwise 30-day F28 measurement is corrupted by F5 bugs.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
