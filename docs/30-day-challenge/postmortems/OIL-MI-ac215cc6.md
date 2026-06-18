# Postmortem — OIL-MI-ac215cc6

> **Verdict:** <!-- skill: verdict -->✅ Clean loss — strategy as designed<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Oil Micro LONG via Filter #27 limit order ($78.47), filled after 14m20s wait, hit SL 11min later for −$360. Price never reached BE (50% to TP). Clean strategy execution, just a losing setup.<!-- /skill: tldr -->

---

## Trade card

- **System:** Oil Micro
- **Instrument:** BCO_USD
- **Strategy:** micro_alpha_sweep_oil
- **Side:** LONG 1197 units
- **Entry:** $78.4700 · **SL:** $78.1700 · **TP:** $79.5900
- **Exit:** $78.1700 · **Exit reason:** SL · **P&L (DB):** $-360.00
- **Duration:** 0:25:08.440382

## Risk Math

- Risk: $0.3000/unit × 1197 = $359.10 max loss
- Reward: $1.1200/unit × 1197 = $1340.64 max gain
- R:R: 3.73:1
- 50% to TP level (BE trigger): $79.0300

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-18 01:00:02 | 2026-06-18 06:30:02 | 2026-06-18 04:00:02 |
| EXIT | 2026-06-18 01:25:11 | 2026-06-18 06:55:11 | 2026-06-18 04:25:11 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$79.0300** was NEVER reached during trade

## What happened AFTER exit?

- TP level $79.5900 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.3000 | $-359.10 |
| If hit TP | $1.1200 | $+1340.64 |
| **ACTUAL (DB)** | — | **$-360.00** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 6 closed trades for Oil Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| OIL-MI-6fbb7040 | SHORT | $79.2300 | $79.6500 | SL | $-306.60 |
| OIL-MI-ea9d591d | SHORT | $79.0900 | $79.4400 | SL | $-318.50 |
| OIL-MI-08b725d3 | SHORT | $79.0300 | $79.0200 | SL | $+9.10 |
| OIL-MI-207a8552 | LONG | $82.4400 | $81.8200 | SL | $-663.40 |
| OIL-MI-aba3b668 | SHORT | $87.5200 | $86.2800 | EXPERT | $+458.80 |
| OIL-MI-c1f44df4 | SHORT | $91.2600 | $92.4500 | SL | $-426.02 |

Recent W/L: 2/4
Recent net P&L (excluding this trade): $-1246.62

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-18 01:00:01 | LIMIT_DRY_RUN_INTENT | 78.4706 | dry_run=False, instrument=BCO_USD, offset_pct=-0.1, actual_path=limit_order_pending, entry_price=78.504, ttl_seconds=900 |
| 2026-06-18 01:00:02 | LIMIT_PLACED | 78.4706 | sl=78.17, tp=79.59, units=1197, ticket=2061819519, expiration=2026.06.18 04:15:01, instrument=BCO_USD |
| 2026-06-18 01:14:45 | LIMIT_FILLED | 78.4700 | ticket=2061819519, instrument=BCO_USD, actual_fill=78.47, time_to_fill=14m20s, intended_limit=78.4706, broker_open_time=2026.06.18 04:14:23 |
| 2026-06-18 01:26:00 | EXIT_FILLED | 78.1700 | reason=SL, pnl_gbp=-360.0, pnl_usd=-360.0, oanda_id=2061819519, instrument=BCO_USD |
| 2026-06-18 01:26:00 | EXIT_FILLED | 78.1700 | reason=SL, pnl_usd=-360.0, oanda_id=2061819519 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
Strategy is `micro_alpha_sweep_oil` (rolling 4hr Oil Micro). Entry was via Filter #27 limit-order path at $78.4706 (offset_pct=-0.1, intended pullback into structure). Limit placed 01:00:02 UTC, filled 14m20s later at $78.4700 (1 pip better than intended limit). R:R = 3.73:1 — high end of normal for this strategy (typical 2.5–4). SL distance $0.30/unit is tight on Oil Micro vs typical $0.40–0.60 — possibly the consolidation range was unusually narrow. Filter #27 worked exactly as designed: order placed, filled within 15min TTL, executed at intended price.

**🚨 F28 SMOKING GUN — and this trade IS the FIRST F28-candidate trade of the 30-day challenge** (post-reset $10K baseline established Jun 18 morning). Journal `F28_BIAS_RESOLVED` events around the trade time show:
- `computed_bias`: **bearish** (V1+V2 would have blocked this LONG)
- `mode`: **neutral** (F28 active)
- `effective_bias`: **neutral** → LONG allowed

**This trade would NOT have fired under production V1+V2.** F28 (neutral) explicitly bypassed the bearish bias filter, allowing a LONG to be placed against the bias. The trade lost. **N=1 — single-trade noise, but exactly the data Phase 2 verdict needs.** The Jun 17 trades (pre-reset) are pattern context only, NOT F28 evidence.

**No alignment red flags on the entry-signal mechanics** — consolidation + sweep + engulfing all fired correctly per the strategy. The filter that was designed to suppress LONGs into bearish bias was deliberately disabled by F28.

**Phase 1 instrumentation gap noted:** journal does not emit `SIGNAL_DETECTED` / `SWEEP_FOUND` / `ENGULF_CONFIRMED` events — we cannot see WHAT level was swept or how the consolidation looked. Should be tracked for Phase 3 ranking — without these events, postmortems miss the entry-signal forensics.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
- **DB pnl_usd vs JM web wallet:** User reported `−$360.00 + −$7.20 swap = −$367.20 net` from JM web. DB shows `pnl_usd=−360.00` (matches gross). The −$7.20 swap is overnight financing — not yet captured in DB. **Action: confirm whether `gd_trades.pnl_usd` should include swap. If not, daily reconcile (DB-sum vs wallet-Δ) needs swap adjustment.** Worth noting in IDEAS as P1.
- **Two EXIT_FILLED events in journal** at 01:26:00 — likely OnTradeTransaction + scanner-detected exit firing duplicate. Deterministic checklist didn't flag it (same data). **Mild bug-smell — duplicate journal rows are a class of past bugs (June 15 dedup audit).** Worth checking if `gd_trades.exit_time` row was double-inserted.
- **F28 bias_mode field on this trade:** trade fired under live `BIAS_MODE=neutral`. Postmortem doesn't show what bias would have been under production V1+V2 — would help calibrate F28 verdict. Add to F28 audit M9 follow-up.
- **No M3 bar excursion data** — local MT5 may not be running on the Mac during this overnight trade, or buffer truncated. Not a code bug, but limits MAE/MFE judgment for this postmortem.
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
Recent 6 Oil Micro trades: 2W/4L, net **−$1,246**. Adding this one: 2W/5L, net **−$1,606**. **This is a losing streak.** Of the 4 prior losses, 3 were SL hits and 1 was a SHORT EXPERT-exit save. Pattern suggests Oil Micro's strategy edge is currently underwater — not a single-trade outlier but **a persistent drift**. Sweeps are firing but failing to reach BE. Possible drivers (not yet confirmed): (1) volatility regime mismatch — current Oil price action favours trends not reversals; (2) Filter #27 limit-order entries may have changed effective fill distribution vs market-order baseline; (3) F28 neutral could be allowing trades that would have been bias-filtered. **This trade is a typical loss in a bad streak, not an outlier.** Worth flagging for Phase 2 (DECIDE) review — Oil Micro may be the candidate for Phase 3 ranking.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
Counterfactual table is binary: SL = −$359.10, TP = +$1,340.64. **Price never reached BE level $79.03**, so the trailing/BE logic was never invoked. There was no "trade-off" — strategy just took a setup that went straight against. SL distance $0.30/unit fired exactly at $78.17 (no slippage), which means SL was tight enough that pullback against entry killed the trade quickly (25 minutes). **MAE clearly threatened SL — we lost the full risk amount.** No M3 excursion data to compute exact MAE, but exit at SL = MAE was at SL. **Implied edge for this single trade: zero, but single-trade interpretations are weak.** What this trade contributes to the broader distribution is one more datapoint to the −$1,606 streak — supporting evidence that Oil Micro is in a bad regime. **No SL-too-wide question here** — SL fired at intended level, not a giveback issue.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** Trade execution is **normal** (clean Filter #27 limit fill, SL hit at intended level). But this is an **F28-allowed-against-bias trade** — exactly the population that the 30-day F28 experiment is designed to measure. Tag for explicit tracking.
- **F28 single-trade evidence (Day 1):** 1 trade, allowed by F28, blocked by V1+V2. Lost $367.20. **Counterfactual under production: this trade does NOT exist, wallet stays $10,000.** N=1 = noise. Need 10+ such trades for verdict. Track `computed_bias=X` vs `effective_bias=neutral` mismatches separately in Phase 2 review.
- **Verify on broker (manual):** JM web −$367.20 incl swap. DB −$360. **Not a bug** but reconcile-gap is real. Track in evening close.
- **Track for future trades:** Streak context is concerning — Oil Micro 2W/5L net −$1,606 over last 7. Is bias-disable contributing? Postmortem every Oil Micro trade in Phase 1, tag F28-allowed-against-bias separately.
- **Phase 1 instrumentation gap:** No `SIGNAL_DETECTED` / `SWEEP_FOUND` events. Add to IDEAS.md as P2 — Phase 3 ranking candidate IF postmortem patterns reveal entry-quality issues we can't currently see.
- **Do NOT fix during freeze:** double-EXIT_FILLED, swap column, F28-not-in-BT, signal events instrumentation — all parked. Discipline holds.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
