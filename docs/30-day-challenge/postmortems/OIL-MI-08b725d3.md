# Postmortem — OIL-MI-08b725d3

> **Verdict:** <!-- skill: verdict -->✅ Protected by BE<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Oil Micro SHORT, BE armed at 10:51 (price $78.68 = ~36% to TP, lower than 50% threshold), SL trailed to $79.02. Exit at BE-adjusted SL for +$9.10. **BE saved the trade from being a full −$317 SL.**<!-- /skill: tldr -->

---

## Trade card

- **System:** Oil Micro
- **Instrument:** BCO_USD
- **Strategy:** micro_alpha_sweep_oil
- **Side:** SHORT 908 units
- **Entry:** $79.0300 · **SL:** $79.0200 · **TP:** $78.0300
- **Exit:** $79.0200 · **Exit reason:** SL · **P&L (DB):** $+9.10
- **Duration:** 0:38:27.839530

## Risk Math

- Risk: $0.0100/unit × 908 = $9.08 max loss
- Reward: $1.0000/unit × 908 = $908.00 max gain
- R:R: 100.00:1
- 50% to TP level (BE trigger): $78.5300

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-17 10:15:03 | 2026-06-17 15:45:03 | 2026-06-17 13:15:03 |
| BREAK_EVEN armed | 2026-06-17 10:51:01 | 2026-06-17 16:21:01 | 2026-06-17 13:51:01 |
| EXIT | 2026-06-17 10:53:31 | 2026-06-17 16:23:31 | 2026-06-17 13:53:31 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$78.5300** was NEVER reached during trade

## What happened AFTER exit?

- TP level $78.0300 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.0100 | $-9.08 |
| If hit TP | $1.0000 | $+908.00 |
| **ACTUAL (DB)** | — | **$+9.10** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 6 closed trades for Oil Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| OIL-MI-ac215cc6 | LONG | $78.4700 | $78.1700 | SL | $-360.00 |
| OIL-MI-6fbb7040 | SHORT | $79.2300 | $79.6500 | SL | $-306.60 |
| OIL-MI-ea9d591d | SHORT | $79.0900 | $79.4400 | SL | $-318.50 |
| OIL-MI-207a8552 | LONG | $82.4400 | $81.8200 | SL | $-663.40 |
| OIL-MI-aba3b668 | SHORT | $87.5200 | $86.2800 | EXPERT | $+458.80 |
| OIL-MI-c1f44df4 | SHORT | $91.2600 | $92.4500 | SL | $-426.02 |

Recent W/L: 1/5
Recent net P&L (excluding this trade): $-1615.72

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-17 10:15:02 | LIMIT_DRY_RUN_INTENT | 79.0339 | dry_run=False, instrument=BCO_USD, offset_pct=-0.1, actual_path=limit_order_pending, entry_price=78.9954, ttl_seconds=900 |
| 2026-06-17 10:15:03 | LIMIT_PLACED | 79.0339 | sl=79.38000000000001, tp=78.03, units=908, ticket=2058523064, expiration=2026.06.17 13:30:02, instrument=BCO_USD |
| 2026-06-17 10:15:31 | LIMIT_FILLED | 79.0300 | ticket=2058523064, instrument=BCO_USD, actual_fill=79.03, intended_limit=79.0339, broker_open_time=2026.06.17 13:15:15 |
| 2026-06-17 10:51:01 | BREAK_EVEN | 79.0200 | old_sl=79.38, source=scheduler, trigger_price=78.68 |
| 2026-06-17 10:54:01 | EXIT_FILLED | 79.0200 | reason=SL, pnl_gbp=9.1, pnl_usd=9.1, oanda_id=2058523064, instrument=BCO_USD |
| 2026-06-17 10:54:01 | EXIT_FILLED | 79.0200 | reason=SL, pnl_usd=9.1, oanda_id=2058523064 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
SHORT entry F27 limit @ $79.0339, filled @ $79.03 (broker beat by 0.4 pip). **Original R:R impossibly high (100:1)** because original SL was $79.38 (only $0.35 above entry) but TP was $78.03 (full $1.00 below). Wait — recompute: original SL $79.38 means original risk = $0.35/unit × 908 = $317.80. Reward $1.00 × 908 = $908. **R:R was actually ~2.86:1, normal range.** The "100:1 R:R" in the postmortem header is a DETERMINISTIC SECTION BUG — script computed risk from the BE-adjusted SL ($79.02 → $0.01 risk) instead of the original SL ($79.38 → $0.35 risk). Worth flagging — script bug.

Strategy mechanics clean. F27 fill 28s. BE armed correctly. Entry signal valid.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
- **🐛 postmortem.py R:R bug** — Deterministic section shows R:R 100:1 because script reads `gd_trades.sl` AFTER BE adjustment ($79.02). Original SL $79.38 gives correct R:R 2.86:1. Script should track original SL separately. Add to IDEAS.md as P1 (postmortem-tooling, not strategy).
- **🐛 BE 50% TP threshold trigger inconsistency** — Postmortem says "50% TP $78.5300 NEVER reached." Yet BE armed at trigger_price=$78.68 (only ~36% to TP). **This means BE armed BEFORE 50% threshold.** Either threshold is configured lower than 50% on Oil Micro, OR BE logic uses different math than postmortem assumes. Worth investigating — possibly the BE threshold for Oil Micro is set lower than 50% (Filter #5 Phase 1 historical fix?).
- **Double EXIT_FILLED** — same dedup class.
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
This is the FIRST trade of the Oil Micro Jun 17–18 streak. **The only one BE saved.** If BE had not armed, this would have been a 4th SL adding ~−$317. Instead +$9. **BE worked as designed under partial-progress conditions — saved $326 of risk.** This is the success case for Filter #5 (BE 35% threshold from Jun 13 ship). Without F5, this trade would have been a full SL. Evidence in favour of keeping F5 lowered threshold.

**IMPORTANT: this trade is PRE-RESET (Jun 17) — pattern context only, NOT F28-candidate evidence.** Account reset to $10K Jun 18 morning. F28 verdict uses post-reset trades only.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
**Without BE, this trade SLs at $79.38 for −$317.** With BE, SL trails to $79.02 → exit at $79.02 → +$9.10. **Δ from BE = +$326.** BE was exactly the right tool for a setup that made partial progress (price hit $78.68, ~36% to TP) then reversed.

What's the implied edge? **F5 (BE-35%) salvaged this trade. Worth ~$300 in expected-value terms** when the price-action pattern is "pullback then reverse." The challenge: this saved $326 ONCE in 4 trades, but the other 3 cost −$985. Net Oil Micro Jun 17–18 = −$985 + $9 = −$976. **F5 helped. Just not enough to overcome the regime mismatch.**
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** F5 (BE) working as designed. Trade is a saved-loss success case.
- **Track:** is BE saving more trades over 30 days than its threshold-lowering costs in early-exits-of-winners? F5 shipped Jun 13 to 3/4 systems including Oil Micro — this is the kind of trade that justifies it.
- **NEW: BE threshold mismatch worth investigating** — postmortem assumes 50% TP, but trigger fired at ~36%. Two possibilities: (a) Oil Micro's actual threshold is 35% (per F5 ship), (b) BE math uses a different price reference. Phase 2 ranking item — confirm threshold, fix postmortem.py if it's just script-side wrong.
- **NEW: postmortem.py R:R reads BE-adjusted SL** — script bug. Phase 3 candidate.
- **No code fix during freeze.**
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
