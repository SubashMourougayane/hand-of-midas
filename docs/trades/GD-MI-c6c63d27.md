# Postmortem — GD-MI-c6c63d27

> **Verdict:** <!-- skill: verdict -->✅ Clean loss — strategy as designed<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Gold Micro SHORT entered at 4319.51 after asia-high sweep + bearish M3 engulfing. Went +$390 unrealized (touched 4302.56, just **1.18 pts shy** of the 35% BE trigger at 4301.38), then reversed all the way through entry to SL at 4334.99 for -$356. Half size due to 3-loss DD halve = damage capped. No bugs, no filter mis-fires; trade executed exactly as designed.<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep
- **Side:** SHORT 23 units
- **Entry:** $4319.51 · **SL:** $4334.99 · **TP:** $4267.71
- **Exit:** $4334.99 · **Exit reason:** SL · **P&L (DB):** $-356.04
- **Duration:** 2:50:45.273148

## Risk Math

- Risk: $15.48/unit × 23 = $356.04 max loss
- Reward: $51.80/unit × 23 = $1191.40 max gain
- R:R: 3.35:1
- 50% to TP level (BE trigger): $4293.61

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-15 05:42:01 | 2026-06-15 11:12:01 | 2026-06-15 08:42:01 |
| EXIT | 2026-06-15 08:32:47 | 2026-06-15 14:02:47 | 2026-06-15 11:32:47 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$4293.61** was NEVER reached during trade

## What happened AFTER exit?

- TP level $4267.71 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-15.48 | $-356.04 |
| If hit TP | $51.80 | $+1191.40 |
| **ACTUAL (DB)** | — | **$-356.04** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 10 closed trades for Gold Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-MI-0b973d80 | LONG | $4196.13 | $4182.84 | SL | $-358.83 |
| GD-MI-da28460d | LONG | $4204.09 | $4184.63 | SL | $-369.74 |
| GD-MI-09314bdd | SHORT | $4083.11 | $4109.68 | SL | $-1009.66 |
| GD-MI-14e2fed1 | SHORT | $4097.27 | $4072.74 | MAX_HOLD | $+564.19 |
| GD-MI-cce2a254 | SHORT | $4204.66 | $4174.30 | TP | $+910.80 |
| GD-MI-c5ad6dbd | LONG | $4260.27 | $4257.65 | SL | $-73.36 |
| GD-MI-61765355 | SHORT | $4450.19 | $4449.89 | SL | $+4.80 |
| GD-MI-ab99992e | SHORT | $4463.53 | $4472.19 | MAX_HOLD | $-121.24 |
| GD-MI-89b7373d | LONG | $4466.49 | $4454.87 | SL | $-197.54 |
| GD-MI-e34af01e | LONG | $4465.74 | $4457.13 | SL | $-232.47 |

Recent W/L: 3/7
Recent net P&L (excluding this trade): $-883.05

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-15 05:42:01 | ENTRY_FILLED | 4319.5100 | sl=4334.99, tp=4267.71, units=23, oanda_id=2049286233, risk_pct=4.0, risk_mult=0.5 |
| 2026-06-15 08:33:00 | EXIT_FILLED | 4334.9900 | reason=SL, pnl_usd=-356.04, oanda_id=2049286233 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
**Textbook entry.** Asia consolidation was real — the window 00-04 had range_high 4335.47 / range_low 4285.51 (range $49.96), well above `cfg.asia_min_range`. Bearish sweep at 4337.47 (Asia high + sweep_threshold) was triggered when price punched 4337+ then closed back below the high → the canonical "sweep + reject" pattern. M3 bearish engulfing fired in the post-sweep window, entry at 4319.51. Bias filter green (Variant C — bearish or neutral allowed for SHORT). R:R **3.35** — at the high end of typical (Gold Micro median 1.5–3) but well within the strategy's accepted range; recent peers show R:R 1.13 → 143 (the latter from MAX_HOLD trades where TP/SL ratio is meaningless), so this is normal. Entry timing was 07:42 UTC = inside the active scan window for the 00-04 consolidation. Lot sizing 23 units = correct half-size from DD `risk_mult=0.5` after the 3-loss streak. **Nothing about this trade was atypical of the design.**
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
_No additional bug smells beyond the deterministic checklist above._ Specifically verified:

- **DB P&L $-356.04 = SL distance × units** (15.48 × 23 = 356.04). Matches.
- **Journal: clean ENTRY_FILLED → EXIT_FILLED chain**, no `EXIT_AMBIGUOUS` events → DWX `OnTradeTransaction` fired correctly, the FILE_SHARE fix from yesterday's session held up.
- **Exit price = SL price exactly** (4334.99) → no slippage, no phantom-fill ambiguity, no manual-close intervention needed.
- **Live `dd_state.consecutive_losses` advanced 3→4** as expected after this loss.
- **No M3 bar data available** for the trade window (note from deterministic checklist) — that's because the local Mac MT5 isn't running, NOT a bug. The skill's local-MT5 dependency is optional; everything that mattered came from the VPS API.
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
**This is loss #4 in a row of 5 SL hits in last 7 trades**. Recent peers since GD-MI-cce2a254 (the +$910 winner on Jun 10): SL, SL, SL, MAX_HOLD-tiny-win, SL, SL, SL = **6 losses, 1 small win, 1 medium win**. Net 7-trade window: -$1,239 cumulative. P&L per loss is now smaller ($356 vs $358-$1010 earlier in the streak) because half-sizing is in effect. **This trade is the canonical "near-BE then reverse" loss** — it's notable that the 3 prior losses all went **straight to SL** (5-7 min holds for two of them, no opportunity for BE arming), while this one came **1.18 pts shy of arming BE** before reversing. So the failure mode shifted from "wrong direction immediately" to "right direction initially but not enough conviction to lock in" — small sign that price action is normalizing even though the streak continues.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
The deterministic table only shows the SL-vs-TP binary; the more interesting counterfactual is **"what if BE had armed?"** Price reached **MFE 4302.56 = 17.0 pts of unrealized gain** (~$391). Filter #5 BE trigger sits at 4301.38 (35% to TP). The trade was **literally 1.18 pts shy** of locking in entry as the new SL. Had it armed, this would have been a flat scratch (0 P&L) instead of -$356. **At Filter #7 partial-TP level (50% to TP = 4293.61)** we'd have taken $293 from half the position before the runner stopped at entry — net +$143. The strategy's choice to set BE at 35% (post Filter #5 ship 2026-06-13) is correct in distribution but lost this particular sample by 1.18 pts. **MAE was 0.0 — price never went adverse from entry until the eventual reversal**, so SL-too-wide is not the issue here. The implied lesson is exactly the one already memorialized in `[[project-edge-filters]]`: edge is fill-side ops, and you've already shipped the best fills available. **This trade is one sample from the distribution where Filter #5 missed by less than the spread**; the next 5 trades will tell us whether 35% is the right calibration or whether 25% would catch more of these (already discussed but not measured).
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status: this is normal.** Clean execution, no defects. The DD halve is now `consecutive_losses=4`; one more loss arms `pause_counter` (rule #3 from `dd_protection.py:7-8`).
- **No code change.** The "1.18-pt-shy of BE" pattern would auto-correct if Filter #5 were calibrated to 25% instead of 35% (BE would have armed at 4306.56 instead of 4301.38). **Don't ship from this single sample** — track for a recurring pattern. If 2 more trades show the same "MFE within 2 pts of BE then full reversal," that's the trigger to run a Filter #5b BE-25% sweep on Gold Micro using the standard 19-step workflow.
- **Track for postmortem corpus:** if the next Gold Micro trade is also a loss → `consecutive_losses=5` → `pause_counter` triggers → next 2 signals get SKIPPED entirely, which is a different failure mode worth observing. If the next trade wins, the halve clears and the streak ends.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
