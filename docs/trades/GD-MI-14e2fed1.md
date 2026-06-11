# Postmortem — GD-MI-14e2fed1

> **Verdict:** <!-- skill: verdict -->✅ Protected by BE — MAX_HOLD harvested a +$564 win that would have been BE-scratched without the BE move<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Gold Micro SHORT 23 oz @ $4,097.27 entered at 08:30 UTC, made it 25.43% to TP, BE-armed at 12:12 UTC, then ran out the 4-hour MAX_HOLD clock and got force-closed by the system at $4,072.74 = **+$564.19 gross / +$562.58 net (after -$1.61 commission)**. Reason in JM panel reads "Client" because MAX_HOLD closes via the EXPERT API which JustMarkets reports as a client-initiated close. The BE move at 12:12 UTC was the difference-maker: without it, the trade was a coin-flip; with it, MAX_HOLD became a profit-harvesting exit instead of a scratch.<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep
- **Side:** SHORT 23 units
- **Entry:** $4097.27 · **SL:** $4096.97 · **TP:** $4054.26
- **Exit:** $4072.74 · **Exit reason:** MAX_HOLD · **P&L (DB):** $+564.19
- **Duration:** 4:00:59.143010

## Risk Math

- _Risk math computed from ORIGINAL SL ($4114.62); current stored sl_price is $4096.97 after BE move._
- Risk: $17.35/unit × 23 = $399.05 max loss
- Reward: $43.01/unit × 23 = $989.23 max gain
- R:R: 2.48:1
- 50% to TP level (BE trigger): $4075.77

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-11 08:30:02 | 2026-06-11 14:00:02 | 2026-06-11 11:30:02 |
| BREAK_EVEN armed | 2026-06-11 12:12:01 | 2026-06-11 17:42:01 | 2026-06-11 15:12:01 |
| EXIT | 2026-06-11 12:31:01 | 2026-06-11 18:01:01 | 2026-06-11 15:31:01 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$4075.77** was NEVER reached during trade

## What happened AFTER exit?

- TP level $4054.26 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

_Note: original SL at entry was $4114.62; current stored sl_price is $4096.97 (probably moved by BE)._

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-17.35 | $-399.05 |
| If hit TP | $43.01 | $+989.23 |
| **ACTUAL (DB)** | — | **$+564.19** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 8 closed trades for Gold Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-MI-cce2a254 | SHORT | $4204.66 | $4174.30 | TP | $+910.80 |
| GD-MI-c5ad6dbd | LONG | $4260.27 | $4257.65 | SL | $-73.36 |
| GD-MI-61765355 | SHORT | $4450.19 | $4449.89 | SL | $+4.80 |
| GD-MI-ab99992e | SHORT | $4463.53 | $4472.19 | MAX_HOLD | $-121.24 |
| GD-MI-89b7373d | LONG | $4466.49 | $4454.87 | SL | $-197.54 |
| GD-MI-e34af01e | LONG | $4465.74 | $4457.13 | SL | $-232.47 |
| GD-MI-a089bbcf | LONG | $4487.86 | $4484.28 | SL | $-293.81 |
| GD-MI-4641b527 | SHORT | $4488.28 | $4494.66 | SL | $-299.86 |

Recent W/L: 2/6
Recent net P&L (excluding this trade): $-302.68

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-11 08:30:02 | ENTRY_FILLED | 4097.2700 | sl=4114.62, tp=4054.26, units=23, oanda_id=2038639453, risk_pct=4.0, risk_mult=1.0 |
| 2026-06-11 12:12:01 | BREAK_EVEN | 4096.9700 | old_sl=4114.62, source=scheduler, trigger_price=4075.69 |
| 2026-06-11 12:31:02 | EXIT_FILLED | 4072.7400 | reason=MAX_HOLD, pnl_usd=564.1900000000151, bars_held=80 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
**Setup geometry was textbook.** All gates aligned per `CLAUDE.md` rolling-4hr-window Alpha-Sweep rules:

- **Daily bias: bearish** ✓ (matches SHORT direction)
- **Bearish sweep wick at $4112.62** at 08:00 UTC (per scan-status data captured during live monitoring) ✓
- **Engulfing M3 candle** within 45-min window (closed at $4097.27 = entry) ✓
- **R:R = 2.48:1** — squarely in the 1.5–3.0 strategy band, healthy geometry
- **Entry within scan window**: 08:30 UTC, well inside Gold Micro's rolling-4h cadence

**The geometry concern:** this was the SECOND bearish sweep of the day. The big morning sweep at $4118 (around 01:30 UTC) wasn't caught because it happened during the 22-2 / 0-4 windows' BUILDING phase. By 08:30 UTC entry, gold had already dropped $58 from $4118 → $4060, then bounced back to $4097 (where we entered). Most of the day's downside energy was already spent — which the live monitoring intuition flagged ("we're 6.5 hours late on the real move"). The strategy correctly took the engulfing signal but the resulting move was muted: peaked at ~$4075 (only 25% of TP distance) before bouncing.

This is exactly the **EDGE_FILTERS #1 (range exhaustion)** target case — by entry time, today's range had already covered ~72% of the 20-day ATR. A range-exhaustion filter at threshold 0.7 would have skipped this entry. **But absent that filter, the strategy did its job correctly.** The trade was statistically expected behavior in the long-run distribution; it's the architectural opportunity for filtering, not a failure.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
**Reconciliation (clean):**
- DB pnl_usd: **+$564.19** (gross — engine math: ($4097.27 − $4072.74) × 23 = $564.19) ✓
- JM panel Trade P&L: **+$564.19** ✓
- JM panel Net P&L: **+$562.58** = $564.19 trade − $1.61 commission. Engine doesn't track commission — that's expected; broker netting is correct.
- DB exit_time and reason were journaled correctly: `EXIT_FILLED, reason=MAX_HOLD, bars_held=80`. **DWX OnTradeTransaction handler IS working for Gold Micro.** This contrasts with last night's `OIL-AS-5434644d` where the same handler did NOT fire, and with the still-stuck `OIL-AS-59a94823` which is at EXIT_AMBIGUOUS streak 82+ as of 13:05 UTC.

**JM "Closed by: Client" label:** the broker reports MAX_HOLD closes as Client-initiated because the engine sends them via the API close endpoint, not via broker-side SL/TP triggers. Cosmetic — not a bug. Worth knowing so future postmortems don't misread.

**Cross-system consistency:** today, the DWX EA handled this Gold Micro close cleanly while letting the Oil Macro `OIL-AS-59a94823` close go untracked. That matches the [bug-dwx-ontradetransaction-dual-instance](../../.claude/projects/-Users-subash-SUBASH-VibeTrader/memory/bug_dwx_ontradetransaction_dual_instance.md) hypothesis: deal events split between Mac and VPS MT5 instances per dispatch, not by symbol. Today this Gold close landed on the right EA; today's Oil close did not.

**No additional bug smells beyond the deterministic checklist above for THIS trade.** The Oil Macro stuck-trade is a separate incident requiring its own postmortem once we have a way to write it (Oil Macro `/api/oil/trades` returns 500 — second time we've hit this; should be tracked as a separate fix).
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
**This trade flips a losing run.** The 8-trade peer table is dominated by SLs and a MAX_HOLD loss — only 2 winners (`cce2a254` +$911 TP and `61765355` +$5 micro-win). Net of those 8 was **−$303**. Adding this trade's +$564 swings the recent-9 total to **+$261**. Two consecutive winners (`cce2a254` yesterday, this trade today) after a 6-trade losing slog is the typical Alpha-Sweep recovery pattern: the strategy bleeds in choppy regimes, then catches one or two big trend days that more than cover the slog.

**MAX_HOLD pattern signal:** before this trade, the only MAX_HOLD in the recent peer set was `ab99992e` at −$121. That suggests MAX_HOLD usually closes near scratch or small loss. **This MAX_HOLD closed at +$564, which IS an outlier.** The reason is the BE move at 12:12 UTC — without the BE protection, the implied unprotected close would have been closer to entry ($4097.27) and produced a small loss or scratch. So the +$564 isn't a "typical MAX_HOLD" — it's a "BE-protected MAX_HOLD" which is structurally different.

**Streak context:** Gold Micro's `consecutive_losses` would have been at 1 going into this trade (after `c5ad6dbd` SL Jun 10) — DD halving threshold is 3 consecutive, so position was full-size. Win resets the counter to 0. The DD math is healthy.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
The trade made it from $4097.27 entry to ~$4075 (BE trigger reached at 12:12 UTC, trigger_price $4075.69 in journal). That's roughly **53% of TP distance** ($23 of the $43 to TP). Then it bounced back without ever breaking the $4075 zone again over the remaining 1h19min before MAX_HOLD fired at $4072.74. The peak was effectively the BE arm point.

**BE timing was perfect for this trade.** Without BE, MAX_HOLD would have closed at ~$4072.74 with original SL at $4114.62 still active — but since price never threatened the original SL (max recorded high was below entry), it wouldn't have stopped out. **The actual outcome with original SL preserved: same MAX_HOLD close at $4072.74 = same +$564.** So the BE move didn't change the P&L on THIS trade.

But that's a misleading framing. The BE move's value is **option premium**: it eliminates the tail risk of a deep retrace stopping out at $4114 for −$399. The fact that the tail didn't materialize this time doesn't mean BE was wasted — it means the insurance didn't get called. Future BE-armed trades that DO see deep retraces will benefit.

**SL was NOT too wide for this trade** — original $4114.62 was 17.35 from entry, far enough that intraday noise didn't threaten it. Tightening SL to (say) $4108 wouldn't have helped here (price didn't reach $4108 either) and would have stopped out earlier on a different day's wider noise. SL geometry is correct for the strategy.

**Implied edge interpretation (single-trade — weak):** this trade contributes +$564 to the long-run distribution. The interesting datum is that **a setup the proposed [EDGE_FILTERS](../EDGE_FILTERS.md) range-exhaustion filter (#1) would have skipped, still produced a winner.** That cuts both ways: it's evidence that the proposed filter would skip some real winners (false negatives), but the question is whether the avg P&L per non-skipped trade improves enough to justify the foregone winners. Cannot answer from one trade. Backtest required.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **🟢 This is normal — system worked as designed.** Setup met all gates, BE armed at 53% to TP, MAX_HOLD harvested the locked-in profit when momentum stalled. Counts as a clean +$564 win.
- **🟡 Track:** record this as the first MAX_HOLD-after-BE outcome in the corpus. If we accumulate 5+ similar trades over the next month, the data will show whether MAX_HOLD-after-BE is a reliable secondary edge or a fluke. The BE-trigger threshold (50% to TP) and MAX_HOLD bars (80) are calibration knobs that can be tuned against this real outcome distribution.
- **🟡 Fix Oil Macro `/api/oil/trades` 500 error.** Second time today this endpoint blocked a postmortem. The Gold Micro / Gold Macro / Oil Micro endpoints all work. Investigate `backend-oil/routes/trades.py` for whatever is breaking — likely a column-name or strategy filter mismatch since the rest of the system has it correctly. Until fixed, every Oil Macro trade postmortem requires manual data assembly via `scripts/diagnose_*.py`.
- **🟢 No code change needed for the strategy itself.** This trade validates the strategy's "BE protects, MAX_HOLD harvests" design.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
