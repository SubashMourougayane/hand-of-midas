# Filter #27 — Limit-Order Entry Research

**Branch:** `filter/27-limit-order-sweep`
**Sweep commit:** `1049eda9` (BT engine + runner)
**Sweep ran:** 2026-06-16 09:58 → 14:17 UTC (4hr 19min, 124 BTs)
**Status:** BT complete, ship decision pending live-infra build
**Owner:** Subash

---

## 1. Why this exists

### The triggering incident (2026-06-16)

Three live LONG entries fired during morning Asia/London sessions on 2026-06-16. Two of them lost money; one made it. Looking at the slippage on each:

| Trade | Calc entry | Actual fill | Slip | Real R:R vs planned R:R |
|---|---:|---:|---:|---:|
| GD-MI-5794d040 (Gold Micro LONG) | $4318.47 | $4318.68 | +$0.21 | dropped from ~2.0 to ~1.0 |
| OIL-MI-207a8552 (Oil Micro LONG) | $82.18 | $82.44 | +$0.27 (27 pips) | dropped from 2.3 to 0.85 → SL hit |
| GD-AL-d0b6bbee (Gold Macro SHORT) | $4343.68 | $4335.72 | −$7.96 favorable | improved from 1.0 to 1.27 |

The Oil Micro trade is the headline case: the strategy expected a $0.62 risk on a $0.53 reward (R:R ~0.85 even before slippage), and slippage widened that to a real R:R that only needed > 54% WR to break even. With a fast adverse move post-fill, the trade SL'd in 15 minutes for −$663.

### The hypothesis

The strategy uses market orders. A market order accepts whatever price the broker offers at the moment of execution. On fast-moving M3 bars (which is exactly when our sweep+engulfing signals fire — by definition mid-momentum), the spread between calc-entry and actual fill widens by 5-10× the model's slippage assumption.

**Hypothesis:** Replace market orders with limit orders at favorable price levels. Accept that some signals will not fill. Measure pre/post on the real backtest engine across 21 years of data. If P&L improves more than the missed-fill cost, ship.

### Why this matters now

Filter #5 (BE 35%) + Filter #7 (partial TP 50%) + Filter #6 (Oil Macro trail) + Gold Micro market_close fix shipped through 2026-06-13. Cumulative effect: **+$1.547M / 21yr**. After those filters landed, the live↔BT P&L gap remained stubbornly larger than the calibration plan tolerance. The leading hypothesis for the gap was entry-side slippage, which the BT model under-prices. Filter #27 is the systematic test of that hypothesis.

### Constraint

User locked in: BT-only this round. Live limit-order infrastructure is a separate gated commit set after BT signs off.

---

## 2. Strategy primer (one paragraph)

Hand of Midas runs the "Alpha Sweep" strategy on four systems (Gold Macro, Gold Micro, Oil Macro, Oil Micro). Alpha Sweep is the ICT/SMC "Judas swing" pattern: identify an Asian / consolidation range, watch for a sweep beyond the range that closes back inside (the Judas reversal), wait for an M3 engulfing candle in the reversal direction, enter at the engulfing close. SL beyond the swept wick. TP at structure or 2× risk, whichever is closer. Filter #5 arms break-even at 35% to TP. Filter #7 banks half the position at 50% to TP. The fill model in `backend/execution/fill_model.py` (and a duplicate `_execute_trade` in `backend-oil-micro/backtest/engine.py`) walks M3 bars from the engulfing bar onwards looking for SL / TP / partial / BE / trail conditions.

---

## 3. Variant grid

The sweep tested **31 variants per system × 4 systems = 124 BTs**:

- **1 baseline:** market entry, current production behaviour (`entry_mode="market"`, slippage model unchanged).
- **30 limit-order variants** = 3 TTLs × 5 price levels × 2 fill modes.

### TTL (how long the limit order lives before cancellation)

| TTL | M3 bars |
|---|---|
| 3 min | 1 bar |
| 6 min | 2 bars |
| 15 min | 5 bars |

### Limit price level

| Code | Where the limit goes |
|---|---|
| `A` | `signal.entry` verbatim (the strategy's calc entry, which already includes a baseline slippage offset) |
| `B` | The engulfing M3 bar's `ask_close` (LONG) or `bid_close` (SHORT) — the engulfing close itself, no slippage offset baked in |
| `C10` | `signal.entry − 0.10 × signal.risk` (LONG). Pull back 10% of the risk distance into the engulfing structure. |
| `C20` | Same idea, 20% pullback |
| `C30` | Same idea, 30% pullback |

### Fill strictness

| Mode | Fill condition (LONG) | Fill condition (SHORT) |
|---|---|---|
| `loose` | `bid_low ≤ limit_price` | `ask_high ≥ limit_price` |
| `strict` | `bid_low ≤ limit_price` AND `bid_close ≤ limit_price` | `ask_high ≥ limit_price` AND `ask_close ≥ limit_price` |

`strict` mode is the pessimistic-fill defense against the M3 wick parity tax: a 1-second wick can touch a level the broker can't actually fill. Strict requires the bar to also close beyond the limit (sustained move).

---

## 4. Implementation

### Code changes (committed at `e15586b`, fix at `1049eda`, intermediate-save at `eeaabb3`)

| File | Change |
|---|---|
| `backend/execution/fill_model.py` | Extended `TradeResult` with `filled: bool` and `would_have_won: Optional[bool]`. Added `entry_mode`, `limit_price`, `limit_ttl_bars`, `limit_fill_strict` kwargs. Pre-walk fill loop runs ahead of the existing exit loop. On miss, runs the exit logic hypothetically with `entry=limit_price` to compute `would_have_won` (informational lookahead, never used in ship ranking). |
| `backend-oil/execution/fill_model.py` | Mirror change (Oil Macro has its own copy). |
| `backend-oil-micro/backtest/engine.py` | Local `_execute_trade()` (returns dict, not TradeResult) gets the same pre-walk and miss-return shape. |
| All 4 engines (`backend/`, `backend-micro/`, `backend-oil/`, `backend-oil-micro/`) | Propagate kwargs from `run_backtest()`. Compute `limit_price` per variant inside the engine (strategies untouched). On miss: increment counters, do NOT advance `last_signal_time` cooldown or `position_exit_time` (no trade was taken). Added `missed_signals`, `would_have_won_count`, `total_signals`, `filled_signals` to `BacktestResult`. |
| `tests/test_fill_model_limit.py` | 8 unit tests: touch-fills, miss + would_have_won winner / loser, strict reject / accept, baseline equivalence, pessimistic ⊆ optimistic. All pass. |
| `scripts/run_filter_27_limit_orders.py` | Sweep runner. Module-clear pattern between systems. Atomic JSON saves after each system. Per-cell append-only JSONL for crash recovery. Run metadata header (git branch / commit / host / timestamps / per-system elapsed). Telegram digest on completion. |

### Baseline equivalence (ran before sweep)

For each system, ran `run_backtest()` with no kwargs vs explicit `entry_mode="market"`. Numbers must be byte-identical, otherwise the refactor changed behaviour:

| System | Baseline N | Baseline P&L (default) | Baseline P&L (`entry_mode="market"`) | Identical? |
|---|---:|---:|---:|---:|
| Gold Macro | 2242 | $427,597.90 | $427,597.90 | yes |
| Gold Micro | 1963 | $361,659.82 | $361,659.82 | yes |
| Oil Macro | 1683 | $825,878.58 | $825,878.58 | yes |
| Oil Micro | 4644 | $3,177,780.31 | $3,177,780.31 | yes |

All four matched to the cent. Refactor preserved current behaviour.

### What `would_have_won` is (and what it is NOT)

When a limit order misses (TTL expires without a touch), the runner runs a *hypothetical* exit walk with `entry = limit_price` starting at the bar after TTL expiry. If that simulated trade would have ended in profit, `would_have_won = True`. This is **informational lookahead** — it uses bars that the strategy would not have observed at decision time. It is reported in the JSON and the console with `(info)` tag, and **MUST NOT** be used to rank variants in ship decisions. Its only legitimate use is post-hoc analysis: "of the trades we missed, how many would have won?" — answers questions about whether the limit price was too aggressive without affecting which variant we choose.

---

## 5. Sweep mechanics

### Cost tracking

| | |
|---|---|
| Variants per system | 31 |
| Systems | 4 |
| Total BTs | 124 |
| Wall-clock | 4hr 19min (15,537 sec) |
| Per-system elapsed | Gold Macro 43min · Gold Micro 95min · Oil Macro 37min · Oil Micro 83min |
| Outputs | `scripts/output/filter_27_results.json` (full grid), `scripts/output/filter_27_results.jsonl` (per-cell append-only), `/tmp/filter_27_run.log` (full console) |

### Iteration history

The sweep was started, killed, and restarted three times during this session because of mid-flight bugs found by reviewing the live console output:

1. **First start:** ran without intermediate JSON saves. After 90min realised that a process crash would lose all progress. Killed.
2. **Second start (after `eeaabb3`):** added atomic JSON saves after each system + per-cell JSONL. 46 cells in, noticed `fill_rate = 120%` on the baseline Gold Micro row. The bug: `total_signals` counted alpha_sweep signals only, but `n` (the trades list) included `mean_rev` + `cross_market` trades. fill_rate denominator was wrong. Killed.
3. **Third start (after `1049eda`):** added a `filled_signals` counter scoped strictly to alpha_sweep. fill_rate is now `filled_signals / total_signals`, both alpha_sweep-scoped. Sweep ran clean to completion.

The bug only affected the displayed `fill_rate`. PF, P&L, missed, would_have_won were all alpha_sweep-scoped already and unaffected.

---

## 6. Results

### Top variant per system

| System | Best variant | Baseline | New | ΔP&L | ΔPF | fill% | miss | wwl (info) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Gold Macro | `ttl15_C10_loose` | $427,598 (PF 3.53) | $445,598 (PF 3.85) | **+$18,000** (+4.2%) | +0.32 | 89% | 168 | 140 |
| Gold Micro | `ttl15_C10_loose` | $361,660 (PF 4.52) | $390,097 (PF 5.35) | **+$28,438** (+7.9%) | +0.83 | 86% | 244 | 218 |
| Oil Macro | `ttl15_B_loose` | $825,879 (PF 4.70) | $1,006,057 (PF 5.43) | **+$180,178** (+21.8%) | +0.73 | 98% | 38 | 27 |
| Oil Micro | `ttl15_C10_loose` | $3,177,780 (PF 5.76) | $3,711,942 (PF 7.56) | **+$534,162** (+16.8%) | +1.80 | 94% | 286 | 244 |

**Cumulative if all four ship:** **+$760,778 / 21yr**, on top of the previously-shipped $1.547M from filters #5 / #6 / #7 / Gold Micro market-close.

### Top 5 per system (full table)

#### Gold Macro (baseline N=2242, WR=65.5%, PF=3.53, P&L=$427,598)

| Rank | Variant | N | fill% | WR% | PF | ΔP&L | ΔPF | miss |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `ttl15_C10_loose` | 2080 | 89.0% | 66.1% | 3.85 | +$18,000 | +0.32 | 168 |
| 2 | `ttl3_B_loose` | 2249 | 99.9% | 65.8% | 3.57 | +$9,778 | +0.04 | 1 |
| 3 | `ttl6_B_loose` | 2249 | 99.9% | 65.8% | 3.57 | +$9,778 | +0.04 | 1 |
| 4 | `ttl15_B_loose` | 2249 | 99.9% | 65.8% | 3.57 | +$9,778 | +0.04 | 1 |
| 5 | `ttl3_A_loose` | 2247 | 99.9% | 65.6% | 3.53 | +$3,290 | -0.00 | 1 |

#### Gold Micro (baseline N=1963, WR=74.9%, PF=4.52, P&L=$361,660)

| Rank | Variant | N | fill% | WR% | PF | ΔP&L | ΔPF | miss |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `ttl15_C10_loose` | 1784 | 85.6% | 77.1% | 5.35 | +$28,438 | +0.83 | 244 |
| 2 | `ttl6_C10_loose` | 1704 | 79.7% | 77.2% | 5.55 | +$14,482 | +1.02 | 350 |
| 3 | `ttl3_B_loose` | 1967 | 100% | 75.3% | 4.56 | +$4,915 | +0.03 | 0 |
| 4 | `ttl6_B_loose` | 1967 | 100% | 75.3% | 4.56 | +$4,915 | +0.03 | 0 |
| 5 | `ttl15_B_loose` | 1967 | 100% | 75.3% | 4.56 | +$4,915 | +0.03 | 0 |

#### Oil Macro (baseline N=1683, WR=61.1%, PF=4.70, P&L=$825,879)

| Rank | Variant | N | fill% | WR% | PF | ΔP&L | ΔPF | miss |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `ttl15_B_loose` | 1656 | 97.8% | 62.7% | 5.43 | +$180,178 | +0.73 | 38 |
| 2 | `ttl6_B_loose` | 1640 | 96.9% | 62.6% | 5.42 | +$144,739 | +0.72 | 53 |
| 3 | `ttl15_C20_loose` | 1503 | 87.2% | 63.2% | 6.21 | +$116,303 | +1.52 | 220 |
| 4 | `ttl3_B_loose` | 1624 | 95.9% | 62.6% | 5.37 | +$113,612 | +0.67 | 70 |
| 5 | `ttl6_C10_loose` | 1623 | 95.6% | 62.3% | 5.30 | +$90,159 | +0.61 | 74 |

#### Oil Micro (baseline N=4644, WR=77.3%, PF=5.76, P&L=$3,177,780)

| Rank | Variant | N | fill% | WR% | PF | ΔP&L | ΔPF | miss |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `ttl15_C10_loose` | 4504 | 94.0% | 79.9% | 7.56 | +$534,162 | +1.80 | 286 |
| 2 | `ttl6_C10_loose` | 4437 | 91.7% | 80.2% | 7.72 | +$495,501 | +1.96 | 399 |
| 3 | `ttl15_B_loose` | 4585 | 97.0% | 79.3% | 6.90 | +$419,026 | +1.14 | 140 |
| 4 | `ttl6_B_loose` | 4548 | 95.8% | 79.4% | 6.94 | +$406,835 | +1.18 | 201 |
| 5 | `ttl3_C10_loose` | 4333 | 88.9% | 80.2% | 7.79 | +$362,518 | +2.03 | 543 |

### Bottom-3 per system (the loser variants)

The bottom of every system's ranking is dominated by `strict` mode + deep `C` pullback. Examples:

| System | Worst variant | ΔP&L |
|---|---|---:|
| Gold Macro | `ttl3_C30_strict` | -$377,393 |
| Gold Micro | `ttl3_C30_strict` | -$335,279 |
| Oil Macro | `ttl3_C30_strict` | -$676,970 |
| Oil Micro | `ttl3_C30_strict` | -$3,061,287 |

Pattern: when you require a 30% pullback AND a sustained-close fill on a 3-min TTL, you miss 90%+ of signals. The few that fill have higher PF (lookahead trade: those are the truly mean-reverting setups), but the absolute P&L collapses. Strict mode + deep pullback is poison.

### Patterns across systems

1. **`ttl15_C10_loose` wins 3 of 4 systems.** The exception is Oil Macro, which prefers `ttl15_B_loose` (engulfing close, no pullback).
2. **All four winning variants use TTL=15min and `loose` fill mode.** No ambiguity.
3. **`A` (calc-entry verbatim) is statistical noise on Gold but actively LOSES on Oil Micro** (-$30k to -$47k). Oil Micro's signal-calc already includes a slippage offset; using that as a limit price means fills happen at the same effective price as a market order would have, but with the limit-order overhead of "broker confirms then fills" delay. Net: small drag from missed fills.
4. **Strict mode is poison everywhere.** The pessimistic-fill defense was warranted as a hypothesis but the BT clearly says: real broker fills happen on touch, and requiring a sustained close throws away too many winners.
5. **Oil Macro's pattern (B beats C) reflects its slowest pace.** 80 trades/yr, H1-paced, discrete signals. The baseline slippage model `_slippage(br) = $0.03 + br × 0.003 + uniform(0, 0.02)` is too generous for Oil Macro's small risk distances ($0.30-$0.60 per trade). Removing slippage via B (engulf-close limit) recovers most of the drag. Oil Macro doesn't have enough marginal-quality signals to benefit from a pullback-into-structure refinement.

---

## 7. Yearly slice — Oil Micro

To verify that the +$534k/21yr Oil Micro win is not driven by 1-2 outlier years, ran the same baseline-vs-`ttl15_C10_loose` comparison sliced by year.

| Year | Baseline N | Baseline WR% | Baseline P&L | Variant N | Variant WR% | Variant P&L | ΔP&L | Δ% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2006 | 137 | 77% | $+41,593 | 122 | 78% | $+36,563 | -$5,030 | -12% |
| 2007 | 165 | 78% | $+73,602 | 146 | 80% | $+79,069 | +$5,467 | +7% |
| 2008 | 294 | 73% | $+329,949 | 262 | 75% | $+335,905 | +$5,956 | +2% |
| 2009 | 253 | 84% | $+233,672 | 221 | 85% | $+220,136 | -$13,536 | -6% |
| 2010 | 247 | 83% | $+183,830 | 211 | 83% | $+163,589 | -$20,240 | -11% |
| 2011 | 289 | 75% | $+281,899 | 273 | 77% | $+304,183 | +$22,285 | +8% |
| 2012 | 275 | 80% | $+184,631 | 277 | 83% | $+237,647 | +$53,016 | +29% |
| 2013 | 214 | 75% | $+76,613 | 216 | 77% | $+101,967 | +$25,355 | +33% |
| 2014 | 183 | 73% | $+54,737 | 182 | 79% | $+94,093 | +$39,356 | +72% |
| 2015 | 229 | 77% | $+122,135 | 229 | 79% | $+144,052 | +$21,917 | +18% |
| 2016 | 177 | 72% | $+52,102 | 180 | 79% | $+80,899 | +$28,798 | +55% |
| 2017 | 97 | 77% | $+17,620 | 97 | 84% | $+25,066 | +$7,446 | +42% |
| 2018 | 198 | 79% | $+112,700 | 198 | 81% | $+151,848 | +$39,148 | +35% |
| 2019 | 199 | 82% | $+118,867 | 199 | 83% | $+142,052 | +$23,185 | +20% |
| 2020 | 228 | 76% | $+150,886 | 229 | 79% | $+190,730 | +$39,844 | +26% |
| 2021 | 267 | 78% | $+161,947 | 270 | 80% | $+201,854 | +$39,907 | +25% |
| 2022 | 352 | 73% | $+438,779 | 350 | 76% | $+526,700 | +$87,921 | +20% |
| 2023 | 294 | 79% | $+215,573 | 295 | 81% | $+275,267 | +$59,693 | +28% |
| 2024 | 241 | 79% | $+167,022 | 242 | 84% | $+201,369 | +$34,347 | +21% |
| 2025 | 185 | 81% | $+96,666 | 185 | 83% | $+119,722 | +$23,055 | +24% |
| 2026 | 120 | 68% | $+62,958 | 120 | 72% | $+79,230 | +$16,272 | +26% |

**Summary:**

| | |
|---|---|
| Up years | **18 / 21** |
| Down years | 3 / 21 (2006, 2009, 2010) |
| Sum-of-losses | -$38,806 |
| Sum-of-gains | +$572,968 |
| Net | +$534,162 |
| Loss-to-gain ratio | 6.8% |

**Read:**
- No catastrophic year. Worst is 2010 at -$20k (-11%), which is well within strategy variance.
- WR is up in every single year (variant ≥ baseline). The strategy is systematically getting better entries.
- Best gains track high-volatility / trending years (2018, 2020 COVID, 2022 Ukraine, 2023). Worst are the post-GFC mean-reverting years (2009, 2010), where the pullback level is more often just stop-hunting noise that fills then immediately reverses.
- The +$534k is broadly distributed across 18 years, not driven by 1-2 outliers.

**The remaining three systems' yearly slices are pending — see "Plan of action" below.**

---

## 8. Risks and parity-tax considerations

### What this BT result does NOT prove

1. **Live↔BT fill parity.** The BT walks M3 OHLC to detect fills; the live broker has finer-grained ticks. A real broker may not fill at the M3 wick even when the wick touched a level, because the wick can be a 1-second tick that no resting limit order observed. Live fill rate is likely **lower** than the BT's 86-98%. If live fill rate drops to 70-80%, the +$534k Oil Micro edge could be eaten.

2. **Live↔BT execution parity.** Once a limit order fills live, the next order is a market order to size into the remaining position, OR the broker fills the entire size at limit. The BT assumes the latter. JustMarkets MT5 + DWX EA will need verification (does `BUY_LIMIT` fill the full lot size atomically, or partially?).

3. **Slippage formula recalibration.** The BT model `_slippage(br) = $0.03 + br × 0.003 + uniform(0, 0.02)` is the same in baseline and limit-order variants. We're comparing two BT results that share the same slippage assumption. If the slippage model is wrong (today's live data suggests it underestimates by ~5×), then all four winning variants might be even better in real life, OR worse, depending on whether the slippage model's bias is symmetric.

4. **Limit-order TTL semantics in live differ from BT.** BT cancels at end-of-TTL bar; live broker cancels via cancel command at TTL-expiry timestamp. If broker is slow to ack the cancel, a partial fill can still happen during the cancel-in-flight window. Edge case but real.

5. **First-15-min volatility window.** Tactic #3 from the slippage-defense playbook says avoid first/last 15 min of session. Our scan window starts at 08:00 UTC = London open = the most volatile time. This wasn't tested in Filter #27. If we add a "skip 08:00-08:14 entries" gate as Filter #28, the limit-order Filter #27 numbers might shift.

### Why the BT result is still trustworthy

- 21yr backtest, 1500-4600 trades per system. Statistically robust.
- Yearly slice on Oil Micro shows 18/21 up years. No outlier-year bias.
- Same engine the dashboard uses, with full audit trail (real `run_backtest()`, no replay tool).
- Per [[feedback-replay-vs-real-backtest]]: real BT, not custom replay.
- Per [[feedback-filter-measurement-gate]]: every behaviour change measured pre/post on real BT, no exemption.
- Baseline equivalence on all 4 systems was confirmed before the sweep, so the refactor itself didn't change behaviour.

---

## 9. Caveats from the user-provided slippage research

User shared a 5-tactic slippage-defense reference (saved in [[project-slippage-defense-playbook]]):

1. **Limit > market.** Filter #27 directly tests this. ✅ in flight.
2. **Liquid assets.** XAU/USD + BCO_USD are top-tier on JustMarkets ECN. ✅ Done.
3. **Low latency.** Contabo VPS not co-located. London-open 08:00 UTC scan is exactly the high-volatility / high-latency window the reference says to avoid. ⚠️ Gap; possible Filter #28.
4. **Slicing / VWAP / TWAP.** Not relevant at our 0.13-1.07 lot sizes. ❌ N/A.
5. **Bake slippage into BT.** Today's live data showed 5× underestimate. ❌ Calibration deferred until ≥30 clean live trades — see [[project-calibration-plan]].

Filter #27 is doing tactic #1. The other tactics are queued or deferred.

---

## 10. Where we are now

| Item | State |
|---|---|
| BT engine refactor | Committed `e15586b`, baseline-equivalent on all 4 systems |
| Atomic save / metadata | Committed `eeaabb3` |
| `fill_rate` bug fix | Committed `1049eda` |
| Sweep complete | Committed nothing yet (sweep produces JSON outputs, no source change) |
| Per-system top variant identified | Yes, see §6 |
| Yearly slice (Oil Micro only) | Done, see §7 |
| Yearly slice (other 3 systems) | Pending |
| Live limit-order infrastructure | Not started |
| Slippage attribution logging (microsec + bid/ask snapshot) | Not started |
| Filter #28 (first-15-min gate) | Not started, research candidate |
| Branch state | `filter/27-limit-order-sweep` at `1049eda9`, NOT pushed (per [[feedback-no-auto-ship]]) |

---

## 11. Plan of action

The user has requested everything be done one-by-one tonight. Order:

### 11.1 — Yearly slices on remaining 3 systems

Same script as the Oil Micro slice (§7), pointed at Gold Macro, Gold Micro, Oil Macro with their respective winning kwargs. Each takes ~3-5 min wall-clock. Confirms no outlier-year drives the ΔP&L for that system.

Acceptance gate: each system needs ≥ 80% up-years (18/21 for the new period 2006-2026, or 17/21 acceptable). Net positive across all 21 years required.

### 11.2 — Microsecond + bid/ask snapshot logging

Adds quantification of the slippage attribution problem. Cheap (~1 hour code, no EA change). Touches `mt5_executor.py` only.

Changes:
- Bump log formatter from `%(asctime)s` (millisecond) to include microsecond.
- Capture `market_data.json` bid/ask at moment of `place_market_order` / `place_limit_order` and log it with the order_placing event.
- Capture broker's reply timestamp (already in `last_response.json`) and log alongside our local timestamp.

Outcome: for every live trade, we'll have:
- `T0`: signal fired (Python wall-clock, μs)
- `T1`: order_placing (Python μs) + bid/ask snapshot
- `T2`: command_sent to DWX (Python μs)
- `T3`: order_filled (Python μs) + bid/ask snapshot + broker fill time

This lets us decompose any slippage event into:
- Calc error: `(calc entry) - (bid/ask at T1)` → strategy issue
- Network / DWX file-poll latency: `T3 - T2` → infrastructure issue
- Broker queue / market move: `(bid/ask at T3) - (bid/ask at T1)` → market issue

### 11.3 — Ship BT defaults per system

For each system, update its `config.py` with the winning kwargs as new BT defaults so future BT runs use the limit-order entry by default:

- Gold Macro (`backend/config.py`): `ALPHA_SWEEP["entry_mode"] = "limit"`, `["limit_offset_pct"] = -0.10`, `["limit_ttl_bars"] = 5`, `["limit_fill_strict"] = False`
- Gold Micro (`backend-micro/config.py`): `MICRO_ALPHA_SWEEP` same kwargs
- Oil Macro (`backend-oil/config.py`): `ALPHA_SWEEP` same TTL + `loose`, but `limit_offset_pct = "engulf_close"`
- Oil Micro (`backend-oil-micro/config.py`): `MICRO_ALPHA_SWEEP` same as Gold

Each commit:
- One config update
- Re-run that system's BT to confirm the new default produces the same numbers as the explicit-kwarg sweep run
- Commit message includes the specific ΔP&L this system gains

### 11.4 — Live limit-order infrastructure (separate ship)

Sized as a separate ship per [[feedback-no-auto-ship]] and the original plan (§D in `~/.claude/plans/piped-hopping-biscuit.md`). Tonight's scope is limited to BT defaults; live wiring is the next session's work.

Pieces:

1. **`mt5_executor.place_limit_order()`** — new function alongside `place_market_order`. DWX command form:
   ```
   OPEN_PENDING|<symbol>|<BUY_LIMIT|SELL_LIMIT>|<lots>|<price>|<sl>|<tp>|<comment>
   ```

2. **DWX EA verification.** Read `mql5/DWX_Server.mq5` and confirm:
   - It handles `BUY_LIMIT` / `SELL_LIMIT` order types
   - It writes `last_response.json` on placement (with broker-assigned ticket)
   - It writes `closed_orders.json` on fill OR cancellation
   - If EA lacks limit support, scope expands to EA changes (mql5 edit + recompile)

3. **Scheduler integration** in each `backend-{system}/scanner/scheduler.py`:
   - Read `entry_mode` from config
   - Branch order placement: market path stays for systems not shipping #27, limit path for shipped systems
   - Compute `limit_price` per variant rule (mirror engine logic)

4. **TTL cancel timer.** A new APScheduler job per pending order that fires at `entry_time + TTL_seconds` and issues `CLOSE_PENDING|<ticket>` to DWX. If cancellation arrives after broker has filled, the OnTradeTransaction reconciler must adopt the trade (existing path).

5. **Journal events.** Three new event types:
   - `LIMIT_PLACED` (with limit_price, ttl_seconds)
   - `LIMIT_FILLED` (with fill_price, time-to-fill)
   - `LIMIT_TTL_EXPIRED` (with broker-cancelled flag)

6. **Telegram strings.** New messages for the above, parallel to existing `trade_filled` etc.

7. **Live regression / dry-run.** Before enabling on a real-money system, run for 24h in dry-run mode logging what *would* have been a limit; compare to actual market fills. Per the audit-then-ship pattern.

8. **Per-system staged rollout.** Per [[feedback-selective-ship-pattern]], enable one system at a time, watch for 5+ live trades each, then move to the next. Order: Oil Micro first (largest BT edge), then Oil Macro, then Gold Micro, then Gold Macro.

### 11.5 — Filter #28 research (later, post-#27 ship)

Research candidate: skip scan in 08:00-08:14 UTC window (London-open volatility spike per slippage-defense tactic #3). Standalone BT sweep per [[project-filter-sweep-workflow]]. Don't run until #27 is fully shipped and we have post-ship live data to compare baseline against.

---

## 12. Decision log

| Date / time | Decision | Rationale |
|---|---|---|
| 2026-06-16 ~08:00 UTC | Investigate slippage on today's losses | Three live trades showed 5-28 pip slip vs BT model expectations |
| 2026-06-16 ~09:00 UTC | Test Filter #27 (limit-order entry) | Most direct slippage defense per Google research |
| 2026-06-16 ~09:30 UTC | Sweep grid: 31 variants × 4 systems | TTL × price-level × strictness, full per-system tuning |
| 2026-06-16 ~09:45 UTC | Add intermediate JSON saves | First start ran without; user requested resilience |
| 2026-06-16 ~10:00 UTC | Fix `fill_rate > 100%` bug | Counter scope was wrong; rebuild scoped both num/denom to alpha_sweep |
| 2026-06-16 14:17 UTC | Sweep complete | 124 BTs, $760k cumulative across all 4 systems |
| 2026-06-16 ~14:30 UTC | Yearly slice on Oil Micro | 18/21 up years, $-39k drag vs $+573k benefit |
| 2026-06-16 ~14:40 UTC | User: do everything one-by-one tonight | Started yearly slices on remaining 3 systems |

---

## 13. Reference

### Branch and commits

- Branch: `filter/27-limit-order-sweep`
- `e15586b` — initial Filter #27 BT-only changes
- `eeaabb3` — intermediate JSON saves + run metadata
- `1049eda` — fill_rate >100% fix (alpha_sweep scope)

### Files

- `backend/execution/fill_model.py` — limit-order pre-walk + extended TradeResult
- `backend/backtest/engine.py` — kwarg propagation + per-variant limit_price compute
- `backend-micro/backtest/engine.py` — same
- `backend-oil/backtest/engine.py` — same
- `backend-oil-micro/backtest/engine.py` — same + duplicate `_execute_trade` change
- `backend-oil/execution/fill_model.py` — Oil Macro mirror of fill_model
- `scripts/run_filter_27_limit_orders.py` — sweep runner
- `tests/test_fill_model_limit.py` — 8 unit tests
- `scripts/output/filter_27_results.json` — full grid
- `scripts/output/filter_27_results.jsonl` — per-cell append-only
- `/tmp/filter_27_run.log` — full console log of the production sweep

### Related memories

- [[project-filter-sweep-workflow]] — branch / pre-post-BT / user-decides-ship
- [[feedback-selective-ship-pattern]] — per-system ship, not global
- [[feedback-no-auto-ship]] — user explicit sign-off required
- [[feedback-filter-measurement-gate]] — every change measured on real BT
- [[feedback-replay-vs-real-backtest]] — real `run_backtest()`, not custom replay
- [[project-slippage-defense-playbook]] — 5 tactics, where Filter #27 fits
- [[project-calibration-plan]] — slippage formula recalibration deferred
- [[project-live-backtest-parity-gap]] — architectural risk this filter helps close

### Related docs

- `docs/FILTER_SWEEP_RESULTS.md` — append Filter #27 entry after ship decision (today's TODO)
- `docs/CALIBRATION_PLAN.md` — slippage recalibration trigger
- `~/.claude/plans/piped-hopping-biscuit.md` — original plan for Filter #27

---

_Document generated 2026-06-16 by the Filter #27 work-stream. Will be updated as yearly slices for Gold Macro / Gold Micro / Oil Macro complete, and again when the live ship lands._
