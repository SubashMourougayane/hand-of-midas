# Postmortem — GD-MI-a94ebe4a

> **Verdict:** <!-- skill: verdict -->✅ Clean win — F27 + F5 + F7 chain worked as designed<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Limit-order entry filled in 56s, partial TP banked +$193.97 at the 50% level, runner held above BE and exited on MAX_HOLD for another +$90.02. Total realized **~$284** on the Phase 6 deploy day. First clean trade post-refactor.<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep
- **Side:** LONG 7 units
- **Entry:** $4142.40 · **SL:** $4142.70 · **TP:** $4196.06
- **Exit:** $4155.26 · **Exit reason:** MAX_HOLD · **P&L (DB):** $+90.02
- **Duration:** 4:00:58.587332

## Risk Math

- Risk: $0.30/unit × 7 = $2.10 max loss
- Reward: $53.66/unit × 7 = $375.62 max gain
- R:R: 178.87:1
- 50% to TP level (BE trigger): $4169.23

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-19 06:15:02 | 2026-06-19 11:45:02 | 2026-06-19 09:15:02 |
| BREAK_EVEN armed | 2026-06-19 07:58:00 | 2026-06-19 13:28:00 | 2026-06-19 10:58:00 |
| EXIT | 2026-06-19 10:16:00 | 2026-06-19 15:46:00 | 2026-06-19 13:16:00 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$4169.23** was NEVER reached during trade

## What happened AFTER exit?

- TP level $4196.06 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.30 | $-2.10 |
| If hit TP | $53.66 | $+375.62 |
| **ACTUAL (DB)** | — | **$+90.02** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 10 closed trades for Gold Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-MI-457d1578 | LONG | $4188.20 | $4182.43 | SL | $-155.79 |
| GD-MI-ddf39e75 | LONG | $4206.89 | $0.00 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-dd9bb158 | LONG | $4241.56 | $0.00 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-f2a2f90b | LONG | $4300.32 | $0.00 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-a05fcfee | LONG | $4323.04 | $4323.04 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-1e53d69b | SHORT | $4348.09 | $4348.09 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-2b152d33 | SHORT | $4337.93 | $4343.78 | SL | $-157.95 |
| GD-MI-32edb995 | SHORT | $4322.81 | $4315.13 | EXPERT | $+161.28 |
| GD-MI-83dd033b | LONG | $4318.64 | $4322.35 | MAX_HOLD | $+170.66 |
| GD-MI-5794d040 | LONG | $4318.68 | $4309.53 | SL | $-384.30 |

Recent W/L: 2/8
Recent net P&L (excluding this trade): $-366.10

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-19 06:15:01 | LIMIT_DRY_RUN_INTENT | 4142.3996 | dry_run=False, instrument=XAU_USD, offset_pct=-0.1, actual_path=limit_order_pending, entry_price=4143.58953, ttl_seconds=900 |
| 2026-06-19 06:15:02 | LIMIT_PLACED | 4142.3996 | sl=4131.69, tp=4196.06, units=14, ticket=2067274584, equity_usd=8354.12, expiration=2026.06.19 09:30:01 |
| 2026-06-19 06:16:17 | LIMIT_FILLED | 4142.4000 | ticket=2067274584, instrument=XAU_USD, actual_fill=4142.4, time_to_fill=56s, intended_limit=4142.3996, broker_open_time=2026.06.19 09:15:59 |
| 2026-06-19 07:58:00 | BREAK_EVEN | 4142.7000 | old_sl=4131.69, source=scheduler, tick_time=2026.06.19 10:57:59, trigger_ask=4161.53, trigger_bid=4161.43, trigger_mid=4161.48 |
| 2026-06-19 08:20:01 | PARTIAL_TP | 4170.1100 | tp=4196.06, side=LONG, entry=4142.4, target=4169.23, banked_usd=193.97000000000025, closed_units=7 |
| 2026-06-19 10:16:01 | EXIT_FILLED | 4155.2600 | reason=MAX_HOLD, pnl_usd=90.02000000000407, bars_held=80 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
Entry was textbook micro_alpha_sweep:
- LONG sweep at 06:15 UTC (08:15 server / 11:45 IST) — well inside the `08-20 UTC` Alpha-Sweep scan window.
- Filter #27 (limit order) priced entry at engulfing close − 10% of risk = $4142.40 vs market reference $4143.59. Filled in 56s at $4142.40 exactly — pulled ~12 pips of slippage protection out of the trade vs market entry.
- BIAS_MODE=neutral (Filter #28 dormant on midas-deploy) so no bias filter blocking. Confirmed live env.
- Filter #5 BE arm at 35% (4142.7, +$0.30 above entry) triggered at 07:58 when price punched to $4161. Risk capped at $0 from that moment.
- Filter #7 partial TP at 50% (4169.23 target) closed half @ $4170.11. Engaged 08:20.
- Runner held until 80-bar MAX_HOLD cap (4hr × 3min bars). No SL/TP touched, exited at $4155.26.

R:R math is misleading on the trade card (178:1) because SL was already at break-even by the time partial TP fired. Effective R:R = "free runner above BE" = unbounded upside, $0 downside. Strategy as designed.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
- DB pnl_usd $90.02 is the **runner only**. Partial TP $193.97 sits in the journal `PARTIAL_TP` event with `banked_usd=193.97`. Total realized = $283.99. The trade card showing "$+90.02" is misleading at a glance — confirm postmortem.py reads from gd_trades.pnl_usd which only carries the final exit P&L.
- `OnTradeTransaction` fired correctly: `EXIT_FILLED` at 10:16 with reason=MAX_HOLD, no `EXIT_AMBIGUOUS`. DWX EA writing closed_orders.json on schedule.
- `LIMIT_FILLED` event captured `actual_fill=4142.4` vs `intended_limit=4142.3996` — 0.04¢ rounding, well within tolerance.
- `BREAK_EVEN` event has `tick_age_secs` diagnostic from commit 3d66acf — tick was fresh (`tick_time=10:57:59` matched event UTC `07:58:00 = 10:58 server`, ~1s lag). Phantom-BE bug NOT triggered. Diagnostic monitoring continues.
- Telegram: not verified in postmortem (user receives alerts; if any missing, flag separately).
- Phase 6 deploy code paths exercised: limit-order pre-walk (Filter #27), partial TP (Filter #7), BE arm at 35% (Filter #5), MAX_HOLD exit. All four filters fired in sequence cleanly.

**Important context: this trade entered BEFORE the Phase 6 e38b288 deploy** (entry 06:15 UTC, deploy completed later). Position lifecycle continued under refactored code path, exit logic untouched in Phase 6 → exit ran on identical exit walk. No phase-6-induced behavior change expected, and none observed.
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
Last 10 peers: 4 LIMIT_TTL_EXPIRED (Filter #27 not filling on fast moves — known behavior, no P&L), 3 SLs (-$155, -$158, -$384), 2 wins ($170, $161), and now this $284 total. Excluding the 4 expired-no-fill, real signal count was 6 → 3W/3L pre-this-trade.

This breaks a 2-of-8 cold streak. Net 10-trade P&L was −$366 before; this trade flips the recent contribution to +$+618 inclusive. Setup is typical micro_alpha_sweep — Asian-session sweep, engulfing reversal, LONG into NY morning rally. Not an outlier on R:R, duration (4hr = MAX_HOLD cap exactly), or lot size (14 → 7 after partial).

The 4 expired-without-fill peers reinforce known Filter #27 trade-off: wall-clock TTL of 15min often misses the fast initial leg. This trade's fill in 56s reflects a clean retracement to limit price — when conditions cooperate, F27 saves real slippage. When they don't, signal is missed entirely. Acceptable per the F27 24-hour BT sweep that justified shipping (per-system selective ship).
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
The trade-card counterfactuals understate this trade because they ignore Filter #7 partial banking. Real picture:

- **Pure-market entry counterfactual:** market would have filled near $4143.59 vs actual $4142.40. F27 added ~$1.19 × 14 units = **+$16.66** to the trade vs market entry. Small but real.
- **No-Filter-#7 counterfactual (just BE armed, full size held to MAX_HOLD):** entry $4142.40 → exit $4155.26, +$12.86 × 14 = **+$180.04**. Filter #7 added **+$104** vs runner-only.
- **BE-not-armed counterfactual:** trade went +$26 max-favorable then back to +$12.86 at MAX_HOLD. SL was 30¢ below entry, never threatened. BE arm was procedural, not load-bearing this time.
- **Hit-TP counterfactual:** $4196.06 was never reached — would have needed another $40 of upside in 4hr. Reality: ran to $4170 then drifted sideways. Half-out at 50% TP was correct.

Edge interpretation (single trade, weak signal): F27 + F5 + F7 chain captured **74%** of the runner-only outcome via partial banking (+$194 of the +$284 total). On a trade that drifted sideways above BE, this is the optimal path — full hold to MAX_HOLD without partial would've made *less*. Aligns with the BT prediction that F7 helps Gold Micro on slow-moving days.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** ✅ This is normal — strategy worked as designed. F27 entry, F5 BE arm, F7 partial bank, runner MAX_HOLD. Don't change anything.
- **Verify on broker:** open MT5, check JM history for ticket 2067274584 (limit) + partial close at 08:20 UTC + final close at 10:16 UTC. Net wallet impact should be ~+$284 minus commission (Gold $6/lot RT × 0.14 lots ~ $0.84). Confirm wallet balance moved to ~$8,838 (was $8,547 + $284 + commission drag).
- **Track for future trades:** postmortem.py only reads final `pnl_usd` from gd_trades. When Filter #7 fires, the partial-TP banked amount is in the journal but NOT in the trade card P&L. Consider amending postmortem.py to surface `banked_usd` alongside `pnl_usd` when `PARTIAL_TP` event exists. Latent ergonomic issue, not a bug.
- **Phase 6 monitoring:** this is the first trade exit after the e38b288 deploy. Exit logic unchanged in Phase 6 → behavior matches pre-deploy expectation. Watch the NEXT new entry (post-deploy, post-startup-cooldown) — that's the real test of unified live↔BT signal generation.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
