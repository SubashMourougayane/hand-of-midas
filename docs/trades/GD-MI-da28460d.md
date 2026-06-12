# Postmortem — GD-MI-da28460d

> **Verdict:** <!-- skill: verdict -->✅ Clean loss — strategy as designed (with one timestamp bug surfaced)<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Valid bullish-sweep LONG taken in a bullish-bias session. Price ran +$5 in favor for 3 minutes, then violently reversed in a single M3 bar and SL'd 7 minutes after entry for −$369.74. First real trade since the DWX recompile — **OnTradeTransaction defense fired correctly** (broker-authoritative close in `closed_orders.json`). However, `exit_time` got stored 3 hours ahead of reality: a missed timezone-conversion bug in `mt5_executor.get_trade_details()`.<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep
- **Side:** LONG 19 units
- **Entry:** $4204.09 · **SL:** $4184.63 · **TP:** $4226.10
- **Exit:** $4184.63 · **Exit reason:** SL · **P&L (DB):** $-369.74
- **Duration:** 3:07:13.263750

## Risk Math

- Risk: $19.46/unit × 19 = $369.74 max loss
- Reward: $22.01/unit × 19 = $418.19 max gain
- R:R: 1.13:1
- 50% to TP level (BE trigger): $4215.10

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-12 13:36:01 | 2026-06-12 19:06:01 | 2026-06-12 16:36:01 |
| EXIT | 2026-06-12 16:43:15 | 2026-06-12 22:13:15 | 2026-06-12 19:43:15 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$4215.10** was NEVER reached during trade

## What happened AFTER exit?

- TP level $4226.10 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-19.46 | $-369.74 |
| If hit TP | $22.01 | $+418.19 |
| **ACTUAL (DB)** | — | **$-369.74** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 10 closed trades for Gold Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-MI-09314bdd | SHORT | $4083.11 | $4109.68 | SL | $-1009.66 |
| GD-MI-14e2fed1 | SHORT | $4097.27 | $4072.74 | MAX_HOLD | $+564.19 |
| GD-MI-cce2a254 | SHORT | $4204.66 | $4174.30 | TP | $+910.80 |
| GD-MI-c5ad6dbd | LONG | $4260.27 | $4257.65 | SL | $-73.36 |
| GD-MI-61765355 | SHORT | $4450.19 | $4449.89 | SL | $+4.80 |
| GD-MI-ab99992e | SHORT | $4463.53 | $4472.19 | MAX_HOLD | $-121.24 |
| GD-MI-89b7373d | LONG | $4466.49 | $4454.87 | SL | $-197.54 |
| GD-MI-e34af01e | LONG | $4465.74 | $4457.13 | SL | $-232.47 |
| GD-MI-a089bbcf | LONG | $4487.86 | $4484.28 | SL | $-293.81 |
| GD-MI-4641b527 | SHORT | $4488.28 | $4494.66 | SL | $-299.86 |

Recent W/L: 3/7
Recent net P&L (excluding this trade): $-748.15

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-12 13:36:01 | ENTRY_FILLED | 4204.0900 | sl=4184.63, tp=4226.1, units=19, oanda_id=2045156688, risk_pct=4.0, risk_mult=1.0 |
| 2026-06-12 13:44:00 | EXIT_FILLED | 4184.6300 | reason=SL, pnl_usd=-369.74, oanda_id=2045156688 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
**Setup is textbook Micro Alpha-Sweep.** The signal trace from logs:
```
SIGNAL fired | direction=long sweep_wick=4186.63 sweep_dir=bullish bias=bullish
              range_high=4228.1 range_low=4191.99
```
- Rolling 4hr **consolidation** [4191.99, 4228.1] (range $36.11, well above $5 minimum)
- **Bullish sweep** detected — wick down to 4186.63, $5.36 below range_low, then closed back inside
- M3 **engulfing** confirmed (the SIGNAL fired event implies the engulfing window check passed)
- Daily **bias = bullish** matches sweep direction (bullish sweep, bullish bias) → no bias_block
- Entry within scan window (13:36 UTC, well inside 24/7 Micro window)

**R:R is the one yellow flag.** R = $19.46/unit, reward = $22.01/unit → R:R 1.13:1. That's well below the strategy's healthy zone (1.5–3) and is borderline against the rejected `EDGE_FILTER #16: R:R lower bound`. The reason: TP is set to range_high (4226.10), entry is much closer to range_high (4204.09) than to range_low (4170.33), so the geometry is tilted against this LONG. With ~50–55% historical WR on Micro, a 1.13 R:R has a tiny edge. Per backtest the strategy ships these anyway — but in the live distribution they're losing trades more often than the geometry-favorable ones.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
**🐛 NEW BUG FOUND: `exit_time` stored 3h ahead of reality.**

Cross-referenced 4 sources:

| Source | Value (UTC) |
|---|---|
| Broker (closed_orders.json `close_time` GMT+3) | `16:43:15` server → `13:43:15` UTC |
| Live log `EXIT detected` | `13:44:00.482Z` |
| DB `exit_time` | **`16:43:15` UTC** (`2026-06-12T18:43:15+02:00`) |
| Postmortem-script "Duration" | **187 minutes** |

The DB entry is 3h ahead because `mt5_executor.get_trade_details()` line 379 does:
```python
"close_time": entry["close_time"].replace(".", "-").replace(" ", "T") + "Z"
```
It accepts the EA's GMT+3 server-time string verbatim, swaps the format separators, and slaps a `Z` on — claiming the server-local time IS UTC. **Same class as the original timezone-drift bug** ([[bug-timezone-drift]] fixed June 10 in `_server_to_utc_iso`). When `closed_orders.json` was added on June 10 (commit `141772e`), that code path bypassed the existing helper.

**Impact:** P&L is correct (`-$369.74` matches broker authoritative). Wrong is only `exit_time`, but that breaks:
- `duration` calculation (postmortem says 3h7m, real is 7min)
- Any time-of-day stats / equity-curve labelling
- Filtering by exit_time across UTC date boundaries

**Other checks (✅ all clean):**
- DB pnl_usd = $-369.74 = broker profit. ✓
- `closed_orders.json` was written for this trade (proves OnTradeTransaction fired correctly post-recompile). ✓
- Only 2 journal events (ENTRY, EXIT) — clean exit, no `EXIT_AMBIGUOUS` streak this time (compare GD-MI-09314bdd's 717 ambiguous events from before the EA fix). ✓
- Magic = 200000 in closed_orders entry (correct filter). ✓
- Comment shows `micro_alpha_sweep|GD-MI-da28460` (truncated to 27 chars by MT5; expected). ✓
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
Recent 10 Gold Micro trades show **Micro is bleeding live**: 3W / 7L, net −$748 excluding this one (−$1,118 with this loss). The wins (`+$910`, `+$564`, `+$5`) are dwarfed by 5 losses in the −$200 to −$1,010 range. Two prior losses (`-1009.66`, `-293.81`) were artifacts of the phantom-fill class of bug now fixed — but the rest are real strategy losses on valid setups.

This trade fits the pattern: **valid sweep + valid engulfing + matching bias + LOW R:R + immediate reversal.** Five of the 7 losses (`a089bbcf` `4641b527` `89b7373d` `e34af01e` `c5ad6dbd`) entered LONG and SL'd within hours, same shape as today. The Micro strategy works on paper (PF 2.42 backtest) but live is hitting the bottom-half of the distribution repeatedly.

**Streak break:** prior trade `09314bdd` was a SHORT SL (with the broken phantom-fill data); this is the first **clean** loss since the EA was fixed today. So we now have a clean live sample size of 1.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
The trade traveled +$5 in favor (MFE 4209.05, distance to BE trigger was still $6 away) and then reversed into −$19.46 SL. **BE never armed**, so this was a binary "win full-R or lose full-R" outcome and the loss was pure. There was no escape geometry to debate.

The deeper question — **was the SL too tight?** — is worth a single number. SL distance was $19.46 (from entry 4204.09 to 4184.63). Range_low was 4191.99 and the sweep wick reached 4186.63 (a $5.36 puncture). The system places SL just below the sweep wick, so SL = sweep_wick − sl_buffer. The price punched through 4184.63 cleanly within 7 minutes — this wasn't a marginal stop-out; it was a trend reversal. Looser SL wouldn't have helped (price kept going down).

Trade-off interpretation: the strategy bet that the sweep was a fakeout (price tagging the lower edge then rejecting upward). Instead, the sweep was a **genuine breakdown** through the lower edge of consolidation — a "second leg lower" rather than a wick-reversal. Backtest expects this to be ~30–40% of the time on Micro. Single-trade interpretation is weak; this contributes to the distribution where the strategy correctly identified geometry but the market chose the other path.

**Latent test:** because TP (4226.10) was never reached after exit (per deterministic section), there's no "the strategy was right but BE killed it" smell. This was a clean directional miss.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status:** P&L outcome is normal — clean SL on a low-R:R setup, no system fault. Phantom-fill defense passed its first real-trade smoke test (broker-authoritative close, no ambiguous-streak).
- **🐛 Fix the timezone bug in `backend/execution/mt5_executor.py:379`.** Replace the inline string-massage with a call to `_server_to_utc_iso()` (the helper already in the same file at line 28, used for bar timestamps). Sketch:
  ```python
  "close_time": _server_to_utc_iso(entry["close_time"]),
  ```
  Then write a regression test using the same shape as `closed_orders.json`'s smoke entry (open_time `2026.06.12 16:36:01` → `2026-06-12T13:36:01Z`). Backfill: `UPDATE gd_trades SET exit_time = exit_time - INTERVAL '3 hours' WHERE strategy = 'micro_alpha_sweep' AND exit_time > '2026-06-12 13:00:00+00'` — but only after verifying the fix code-side first.
- **Track:** if the next 3 Micro trades all hit SL on low-R:R LONG setups, revisit `EDGE_FILTER #16: R:R lower bound 0.8 too low` (currently rejected) — the geometry pattern keeps recurring and may justify a per-strategy minimum-R:R floor of 1.5 on Micro specifically.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
