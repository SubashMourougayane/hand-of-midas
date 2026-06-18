# Postmortem — OIL-MI-6fbb7040

> **Verdict:** <!-- skill: verdict -->✅ Clean loss — strategy as designed<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Oil Micro SHORT via F27 limit ($79.23), filled in 29s, hit SL 5min later for −$306.60. R:R=3.55, BE never reached. 3rd Oil Micro SL in a row.<!-- /skill: tldr -->

---

## Trade card

- **System:** Oil Micro
- **Instrument:** BCO_USD
- **Strategy:** micro_alpha_sweep_oil
- **Side:** SHORT 726 units
- **Entry:** $79.2300 · **SL:** $79.6500 · **TP:** $77.7400
- **Exit:** $79.6500 · **Exit reason:** SL · **P&L (DB):** $-306.60
- **Duration:** 0:05:24.842248

## Risk Math

- Risk: $0.4200/unit × 726 = $304.92 max loss
- Reward: $1.4900/unit × 726 = $1081.74 max gain
- R:R: 3.55:1
- 50% to TP level (BE trigger): $78.4850

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-17 12:12:02 | 2026-06-17 17:42:02 | 2026-06-17 15:12:02 |
| EXIT | 2026-06-17 12:17:27 | 2026-06-17 17:47:27 | 2026-06-17 15:17:27 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$78.4850** was NEVER reached during trade

## What happened AFTER exit?

- TP level $77.7400 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.4200 | $-304.92 |
| If hit TP | $1.4900 | $+1081.74 |
| **ACTUAL (DB)** | — | **$-306.60** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 6 closed trades for Oil Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| OIL-MI-ac215cc6 | LONG | $78.4700 | $78.1700 | SL | $-360.00 |
| OIL-MI-ea9d591d | SHORT | $79.0900 | $79.4400 | SL | $-318.50 |
| OIL-MI-08b725d3 | SHORT | $79.0300 | $79.0200 | SL | $+9.10 |
| OIL-MI-207a8552 | LONG | $82.4400 | $81.8200 | SL | $-663.40 |
| OIL-MI-aba3b668 | SHORT | $87.5200 | $86.2800 | EXPERT | $+458.80 |
| OIL-MI-c1f44df4 | SHORT | $91.2600 | $92.4500 | SL | $-426.02 |

Recent W/L: 2/4
Recent net P&L (excluding this trade): $-1300.02

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-17 12:12:01 | LIMIT_DRY_RUN_INTENT | 79.2326 | dry_run=False, instrument=BCO_USD, offset_pct=-0.1, actual_path=limit_order_pending, entry_price=79.1862, ttl_seconds=900 |
| 2026-06-17 12:12:02 | LIMIT_PLACED | 79.2326 | sl=79.65, tp=77.74, units=726, ticket=2058844373, expiration=2026.06.17 15:27:01, instrument=BCO_USD |
| 2026-06-17 12:12:31 | LIMIT_FILLED | 79.2300 | ticket=2058844373, instrument=BCO_USD, actual_fill=79.23, intended_limit=79.2326, broker_open_time=2026.06.17 15:12:10 |
| 2026-06-17 12:18:00 | EXIT_FILLED | 79.6500 | reason=SL, pnl_usd=-306.6, oanda_id=2058844373 |
| 2026-06-17 12:18:01 | EXIT_FILLED | 79.6500 | reason=SL, pnl_gbp=-306.6, pnl_usd=-306.6, oanda_id=2058844373, instrument=BCO_USD |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
SHORT entry via F27 limit @ $79.2326, filled @ $79.2300 (broker beat by 0.3 pip). R:R 3.55:1 — high end of normal for Oil Micro (typical 2.5–4). SL distance $0.42/unit (typical). F27 worked: limit placed, filled in 29s. **Couldn't pull F28 bias context** (journal API capped at 200 events, doesn't reach Jun 17). Need to validate F28 effect via Phase 2 BT comparison or instrumentation upgrade. Entry signal mechanics look clean.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
- **Double EXIT_FILLED at 12:18:00 / 12:18:01** — same pattern as OIL-MI-ac215cc6. Same dedup bug class (June 15 audit). Already in IDEAS.md.
- **Journal API caps at 200** — postmortem.py cannot pull F28 context for trades >1 day old. Already in IDEAS.md.
- No M3 bar excursion data (Mac MT5 not running for this overnight Wed trade).
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
**Streak context dominates.** This is the 3rd Oil Micro SL in a row (08b725d3 +9, ea9d591d −318, then THIS −306). All 3 SHORTs on Jun 17. Combined with subsequent OIL-MI-ac215cc6 LONG (−360), Oil Micro lost on 4 consecutive setups (with 1 nominal +9 win). **Recent 6 trades 2W/4L, net −$1,300.**

**IMPORTANT: this trade is PRE-RESET (Jun 17), pre-baseline for the 30-day challenge.** Account was reset to $10K on Jun 18 morning. This trade is NOT F28-candidate evidence — it's pattern context only. Whether F28 caused the streak vs regime mismatch CANNOT be answered from pre-reset data. F28 verdict relies on POST-RESET trades only.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
Binary outcome: SL or TP. **Price never reached BE level $78.4850** so trailing/BE logic never invoked. SL fired at $79.65 — exactly intended level, no slippage. Trade lasted 5min24s — fastest of the streak. MAE = SL = full risk used. No "trade-off" — straight stop-out. SL distance $0.42 looks normal for Oil Micro; SL fired AT level not before. **Implied edge for this trade: zero. Implied edge for the streak (4 losses in 4 setups): negative.** Single trade noise, but cluster trends matter.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** Single trade NORMAL. Streak CONCERNING. Not a bug.
- **Track:** Oil Micro 4 consecutive losing setups across Jun 17–18. P&L impact ≈ −$1,000 in 24hr.
- **Phase 2 Decide question:** N/A — this trade is pre-baseline. Use ONLY post-reset trades (Jun 18+) for F28 verdict. Pre-baseline streak is regime context, not F28 evidence.
- **No code fix.** Discipline holds.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
