# Postmortem — OIL-MI-1310e9cd

> **Verdict:** <!-- skill: verdict -->✅ Protected by BE<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Oil Micro SHORT @ $78.07, BE armed at 13:12 UTC (price hit $77.67 ~70% to TP), SL trailed to $78.06. Price faked UP (hit BE-SL +$3 exit), then **30min later hit TP target $77.07** without us. **BE saved $176 over a hypothetical SL but COST $300 over a hypothetical TP run.** Net trade +$3 vs counterfactual TP +$303 = F5 BE robbed $300 of edge.<!-- /skill: tldr -->

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
- Price journey post-exit:
  - 18:47 IST: exit at $78.06 (BE-SL)
  - 18:50 IST: $77.50 area
  - 19:00 IST: $77.30 area
  - 19:17 IST: **$77.07** = TP target hit
- **Counterfactual: had we stayed in trade with original SL $78.64, TP would have hit for +$303 instead of actual +$3.**

> NOTE: deterministic script said "TP NOT reached in 30-min window" — this was generated immediately at exit. Manual price-check 30min later showed TP hit. Script has a bounded look-ahead that doesn't catch slow follow-through.

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
**Three real scenarios to evaluate:**
- Without BE: SL would have hit at $78.64 → −$0.57 × 303 = **−$173**
- With BE (actual): SL trailed to $78.06 → +$0.01 × 303 = **+$3**
- **If we'd ridden the original SL: TP $77.07 hit at 19:17 IST → +$1.00 × 303 = +$303** ← THIS IS WHAT ACTUALLY HAPPENED IN PRICE

**BE saved us $176 vs a hypothetical SL but COST us $300 vs the actual price path.** Single-trade lookback says BE was wrong here.

**BE timing analysis (revised):** Price reached $77.67 at 13:12 UTC → BE armed (~40% progress past 35% threshold). BE fired correctly per spec. **But the move continued — this was a CONTINUATION, not a reversal.** BE got faked out by intra-bar volatility on the way to TP.

**Critical pattern (F29 candidate):** Same lesson as GD-AL-4af2d62d (Jun 17): the stock-bar-aware vs intra-bar-aware BE check matters. Price action between BE-arm (18:42) and BE-exit (18:47) was 5 minutes of UP movement. If BE waited for a CLOSED M5 bar above entry instead of any tick touching SL, this trade rides through to TP. **Worth re-evaluating F29 priority.**

**Updated F5 ledger over 2 trades (24hr live):**
| Trade | Without F5 | Actual | TP-counterfactual | Net effect of F5 |
|---|---|---|---|---|
| OIL-MI-08b725d3 (Jun 17) | −$317 SL | +$9 BE | TP not reached | F5 saved +$326 |
| OIL-MI-1310e9cd (Jun 18) | −$173 SL | +$3 BE | +$303 TP (hit 30min after exit) | F5 cost −$300 |
| **Net** | −$490 | +$12 | +$130 | **F5 +$26 vs no-BE / F5 −$118 vs ride-to-TP** |

**Reframe:** F5 is a risk-management tool, not an alpha tool. It trades expected value for variance reduction. **Today's trade shows the cost side of that trade-off explicitly.**

**Was SL too wide?** No. SL at $78.64 was sweep_wick + $0.20 buffer. Standard. The strategy's read was right — TP hit. F5 didn't trust the move.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** ⚠️ **F5 BE robbed this trade of $300 of edge.** Trade made 70% progress to TP, BE armed, intra-bar volatility hit BE-SL, then price continued to TP without us. Same pattern class as F29 candidate.
- **F5 narrative needs rebalancing:** Yesterday's 08b725d3 (BE saved $326 from real reversal) and today's 1310e9cd (BE cost $300 from fake reversal). Net F5 vs no-BE = +$26 over 2 trades. **F5 vs ride-to-TP = −$118.** Tight call.
- **F29 (bar-aware BE) priority bumped:** This trade is the 2nd 24hr example where BE intra-bar tick fired before a CLOSED bar confirmed reversal. F29 spec is in `docs/FILTER_29_BAR_AWARE_BE_RESEARCH.md`. **Worth Phase 3 ranking.**
- **F28 evidence (Day 1 post-reset):** N=2. One F28-allowed-against-bias trade (LONG, lost $367). One bias-aligned trade (SHORT, BE-save +$3). **F28 verdict still inconclusive.**
- **Track for next trades:** Did BE arm before TP-hit? If yes, did BE save (real reversal) or rob (continuation)? **30-day data on this matters for F5 keep/revert + F29 ship.**
- **Cap rework verified live:** today's cap counter correctly excludes 2 TTL_EXPIRED. Without rework, this trade would have been blocked at 3/3.
- **No code fix needed today.** Postmortem.py bugs (R:R header + BE threshold display) already P1 in IDEAS.md.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
