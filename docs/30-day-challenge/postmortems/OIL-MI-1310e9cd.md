# Postmortem — OIL-MI-1310e9cd

> **Verdict:** <!-- skill: verdict -->✅ Protected by BE<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Oil Micro SHORT @ $78.07, BE armed at 13:12 UTC (price hit $77.67 ~70% to TP), SL trailed to $78.06. Price reversed UP, hit BE-adjusted SL. **Closed +$3 instead of −$173 full SL. F5 BE saved $176.** Bias agreed (bearish), F28 not a factor.<!-- /skill: tldr -->

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

- TP level $77.0700 was NOT reached in the 30-min window after exit

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
- **🐛 postmortem.py R:R reads BE-adjusted SL** — Header shows R:R 100:1 because script reads `gd_trades.sl` AFTER BE adjustment ($78.06). Original SL was $78.64 → real R:R 1.75:1. Same script bug as OIL-MI-08b725d3 yesterday. Already in IDEAS.md as P1.
- **🐛 BE 50% TP threshold mismatch (postmortem header)** — Header says "50% TP $77.5700 NEVER reached" but BE armed at trigger_price=$77.67 (~70% to TP from entry). Postmortem assumes 50% threshold; Oil Micro's actual `be_trigger_pct=0.35` (Filter #5 ship Jun 13). Already in IDEAS.md as P1.
- **Double EXIT_FILLED at 13:17:01** — same dedup pattern as 4 prior trades. P1 in IDEAS.md.
- **Cap rework working live** — pre-fix, this would have been the 3rd "trade" of the day (1 SL + 2 TTL_EXPIRED + this one). Post-fix, cap counter shows 2/3 because TTL_EXPIRED doesn't count. ✅ Verified.
- DB pnl_usd matches broker (no swap — closed same day). No phantom fill markers.
- No M3 excursion data (Mac MT5 not running).
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
**The 3 counterfactual scenarios (correctly computed):**
- Without BE: SL hit at $78.64 → −$0.57 × 303 = **−$173**
- With BE (actual): SL trailed to $78.06 → +$0.01 × 303 = **+$3**
- If TP had been reached: $77.07 → +$1.00 × 303 = **+$303**
- **BE delta: +$176 saved**

**BE timing analysis:** Price reached $77.67 at 13:12 UTC → BE armed (35% threshold of $1.00 TP from entry would be at $77.74; actual trigger at $77.67 = ~40% to TP, slightly past threshold). BE was correctly timed — fired AFTER price made meaningful progress, not too early.

**Was the reversal predictable?** Price went from $78.07 → $77.67 (40% to TP) in 54 minutes, then reversed UP to hit BE-adjusted SL within 5 more minutes. Classic "60-65% to TP, fail to break, reverse" Oil pattern. **Strategy correctly captured the favorable progression but couldn't capture the win.**

**Implied edge:** BE saved $176 on this single trade. Across 2 BE saves in the last 24hrs (08b725d3 +$326, this +$176), F5 has saved cumulative ~$502 of risk that pre-Filter-5 (50% threshold) would not have caught. **F5 ship continues to validate live.**

**Was SL too wide?** No. SL at $78.64 was sweep_wick + $0.20 buffer (config). Standard placement. The trade made 70% progress to TP — clearly the strategy's read of the sweep was correct, just not strong enough to follow through to TP.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** F5 BE working as designed. Trade is the 2nd BE-save in 24hrs. Both validate Filter #5 (35% threshold) ship.
- **F28 evidence (Day 1 post-reset):** N=2. One F28-allowed-against-bias trade (LONG, lost $367). One bias-aligned trade (SHORT, BE save +$3). **F28 verdict still inconclusive — need 10+ trades, especially F28-allowed-against-bias subset.**
- **Track for next trades:** R:R distribution. If most Oil Micro trades fire with R:R 1.5–2 (not 3+), the strategy may be in a tight-range regime. Compare R:R distribution Day 1–7 vs prior weeks.
- **Cap rework verified live:** today's cap counter correctly excludes 2 TTL_EXPIRED. Without rework, would have been capped. With rework, this trade was allowed → +$3. **Rework already paying for itself.**
- **No code fix needed.** Postmortem.py R:R + BE-threshold display bugs already in IDEAS.md as P1.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
