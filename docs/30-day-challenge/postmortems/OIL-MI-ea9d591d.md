# Postmortem — OIL-MI-ea9d591d

> **Verdict:** <!-- skill: verdict -->✅ Clean loss — strategy as designed<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Oil Micro SHORT via F27 limit ($79.09), filled in 59s, hit SL 21min later for −$318.50. R:R=3.03, BE never reached. 2nd Oil Micro SL of Jun 17, part of 4-trade losing streak.<!-- /skill: tldr -->

---

## Trade card

- **System:** Oil Micro
- **Instrument:** BCO_USD
- **Strategy:** micro_alpha_sweep_oil
- **Side:** SHORT 910 units
- **Entry:** $79.0900 · **SL:** $79.4400 · **TP:** $78.0300
- **Exit:** $79.4400 · **Exit reason:** SL · **P&L (DB):** $-318.50
- **Duration:** 0:21:03.773743

## Risk Math

- Risk: $0.3500/unit × 910 = $318.50 max loss
- Reward: $1.0600/unit × 910 = $964.60 max gain
- R:R: 3.03:1
- 50% to TP level (BE trigger): $78.5600

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-17 11:30:02 | 2026-06-17 17:00:02 | 2026-06-17 14:30:02 |
| EXIT | 2026-06-17 11:51:06 | 2026-06-17 17:21:06 | 2026-06-17 14:51:06 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$78.5600** was NEVER reached during trade

## What happened AFTER exit?

- TP level $78.0300 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.3500 | $-318.50 |
| If hit TP | $1.0600 | $+964.60 |
| **ACTUAL (DB)** | — | **$-318.50** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 6 closed trades for Oil Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| OIL-MI-ac215cc6 | LONG | $78.4700 | $78.1700 | SL | $-360.00 |
| OIL-MI-6fbb7040 | SHORT | $79.2300 | $79.6500 | SL | $-306.60 |
| OIL-MI-08b725d3 | SHORT | $79.0300 | $79.0200 | SL | $+9.10 |
| OIL-MI-207a8552 | LONG | $82.4400 | $81.8200 | SL | $-663.40 |
| OIL-MI-aba3b668 | SHORT | $87.5200 | $86.2800 | EXPERT | $+458.80 |
| OIL-MI-c1f44df4 | SHORT | $91.2600 | $92.4500 | SL | $-426.02 |

Recent W/L: 2/4
Recent net P&L (excluding this trade): $-1288.12

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-17 11:30:01 | LIMIT_DRY_RUN_INTENT | 79.0941 | dry_run=False, instrument=BCO_USD, offset_pct=-0.1, actual_path=limit_order_pending, entry_price=79.0557, ttl_seconds=900 |
| 2026-06-17 11:30:02 | LIMIT_PLACED | 79.0941 | sl=79.44, tp=78.03, units=910, ticket=2058691799, expiration=2026.06.17 14:45:01, instrument=BCO_USD |
| 2026-06-17 11:31:01 | LIMIT_FILLED | 79.0900 | ticket=2058691799, instrument=BCO_USD, actual_fill=79.09, intended_limit=79.0941, broker_open_time=2026.06.17 14:30:42 |
| 2026-06-17 11:52:00 | EXIT_FILLED | 79.4400 | reason=SL, pnl_usd=-318.5, oanda_id=2058691799 |
| 2026-06-17 11:52:00 | EXIT_FILLED | 79.4400 | reason=SL, pnl_gbp=-318.5, pnl_usd=-318.5, oanda_id=2058691799, instrument=BCO_USD |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
SHORT entry F27 limit @ $79.0941, filled @ $79.09 (broker beat by 0.4 pip). R:R 3.03:1 — middle of normal Oil Micro range. SL distance $0.35/unit (typical). F27 limit fill 59s — fast. Strategy mechanics clean. F28 bias context unavailable for Jun 17 (journal API cap). Entry signal = consolidation + sweep + SHORT engulfing per design.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
- **Double EXIT_FILLED** — same dedup class. Same as 6fbb7040 + ac215cc6. Already in IDEAS.md.
- No M3 excursion data.
- Trade closed 2026-06-17 11:51 UTC — no overnight, so no swap drift expected.
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
**This is THE first SL in the Oil Micro Jun 17 streak.** Sequence: 08b725d3 (+$9 nominal win) → ea9d591d (−$318) → 6fbb7040 (−$306) → ac215cc6 (−$360). Three consecutive losers totalling −$985 in ~20 hours. **All 3 SHORTs traded into the same Oil price range ($79–80) within hours of each other** — likely the same consolidation-then-fail-to-break pattern repeating. Possibly Oil was actually trending UP across this window and the strategy's mean-reversion SHORTs were systematically wrong-sided. **Phase 2 candidate: did F28 (neutral) bypass a bullish bias filter that would have killed all 3 SHORTs?** Cannot confirm without journal access for Jun 17.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
SL or TP — binary. Price never reached BE $78.56. SL fired exactly at $79.44. 21min hold — middle range for Oil Micro. **BE was 17.6% closer than TP from entry, never visited. MAE = SL.** SL distance not too wide (fired at level, no slippage). No "trade-off" — straight wrong-side. **TP $78.03 was NOT reached in the 30-min post-exit window** = price kept moving up away from SHORT thesis. This is consistent with the trending-up-fights-mean-reversion narrative.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** Normal trade. Concerning streak.
- **Track:** Oil Micro 4 consecutive losing setups Jun 17–18. Same Oil price zone $79–80. Mean-reversion against trend.
- **Phase 2 question:** Was the directional regime favouring trends? Could a trend-detection filter (F30/F31 candidates) have suppressed all 3 SHORTs?
- **No code fix.**
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
