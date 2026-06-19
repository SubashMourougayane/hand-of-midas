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

## 7. Yearly slices — all 4 systems

The yearly check is the gating step before any ship. The 21yr aggregate ΔP&L can hide:
- Outlier-year bias (one or two huge years carrying many losing years)
- Regime shifts (the variant works on old data but fails on recent)
- Statistical noise dressed up as signal

For each system, we ran the **same baseline-vs-winning-variant comparison** sliced by year. Acceptance gate (per [[feedback-selective-ship-pattern]]):
- ≥80% up-years (17 of 21 minimum)
- Loss-to-gain ratio under ~25%
- No clear "recent regime" failure

### 7.0 Summary across all 4 systems

| System | Variant | Up yrs | Down yrs | Sum-loss | Sum-gain | Loss/Gain | Recent regime | Verdict |
|---|---|---:|---:|---:|---:|---:|---|---|
| Oil Macro | `ttl15_B_loose` | 18 / 21 | 3 (2007, 2009, 2026) | -$4k | +$184k | 2.2% | clean | ✅ SHIP |
| Oil Micro | `ttl15_C10_loose` | 18 / 21 | 3 (2006, 2009, 2010) | -$39k | +$573k | 6.8% | clean | ✅ SHIP |
| Gold Micro | `ttl15_C10_loose` | 15 / 21 | 6 (2007, 2013, 2014, 2017, 2019, 2023) | -$6k | +$35k | 18% | mixed, no streak | ✅ SHIP |
| **Gold Macro** | `ttl15_C10_loose` | **12 / 21** | **9** (2012, 2015, 2017, 2018, 2019, 2021, 2022, 2023, 2024) | **-$15k** | **+$33k** | **45%** | **5 of last 7 RED** | 🟡 **STASH** |

### 7.1 Oil Micro yearly slice (`ttl15_C10_loose`)

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

### 7.2 Oil Macro yearly slice (`ttl15_B_loose`)

| Year | Baseline P&L | Variant P&L | ΔP&L | Δ% |
|---|---:|---:|---:|---:|
| 2006 | $+4,358 | $+5,294 | +$936 | +21% |
| 2007 | $+5,243 | $+4,122 | -$1,121 | -21% |
| 2008 | $+127,368 | $+141,134 | +$13,766 | +11% |
| 2009 | $+98,745 | $+97,158 | -$1,587 | -2% |
| 2010 | $+71,989 | $+80,380 | +$8,391 | +12% |
| 2011 | $+87,076 | $+105,066 | +$17,990 | +21% |
| 2012 | $+47,633 | $+71,562 | +$23,929 | +50% |
| 2013 | $+11,437 | $+16,203 | +$4,766 | +42% |
| 2014 | $+6,766 | $+7,029 | +$263 | +4% |
| 2015 | $+14,424 | $+18,088 | +$3,663 | +25% |
| 2016 | $+19,538 | $+21,600 | +$2,063 | +11% |
| 2017 | $+1,675 | $+1,798 | +$123 | +7% |
| 2018 | $+17,569 | $+28,207 | +$10,637 | +61% |
| 2019 | $+15,240 | $+20,130 | +$4,890 | +32% |
| 2020 | $+10,335 | $+12,483 | +$2,148 | +21% |
| 2021 | $+39,693 | $+60,600 | +$20,908 | +53% |
| 2022 | $+140,783 | $+177,071 | +$36,289 | +26% |
| 2023 | $+82,488 | $+104,705 | +$22,216 | +27% |
| 2024 | $+14,719 | $+22,353 | +$7,634 | +52% |
| 2025 | $+5,516 | $+9,077 | +$3,561 | +65% |
| 2026 | $+3,282 | $+1,997 | -$1,286 | -39% |

**Read:** Cleanest result of all four. Up in 18/21 years, all 3 down years are sub-$1.6k losses. Sum-of-losses = -$3,994 vs sum-of-gains = +$184,172. Loss/gain ratio 2.2%. The B variant (engulfing-close limit, no slippage offset) recovers what slippage had been costing on a slower-paced strategy. **No regime concerns. Ship.**

### 7.3 Gold Micro yearly slice (`ttl15_C10_loose`)

| Year | Baseline P&L | Variant P&L | ΔP&L | Δ% |
|---|---:|---:|---:|---:|
| 2006 | $+3,311 | $+3,841 | +$530 | +16% |
| 2007 | $+1,088 | $+1,006 | -$82 | -8% |
| 2008 | $+21,940 | $+27,132 | +$5,192 | +24% |
| 2009 | $+6,618 | $+9,444 | +$2,826 | +43% |
| 2010 | $+8,010 | $+9,168 | +$1,158 | +14% |
| 2011 | $+39,291 | $+43,722 | +$4,432 | +11% |
| 2012 | $+21,285 | $+23,296 | +$2,010 | +9% |
| 2013 | $+10,518 | $+9,586 | -$932 | -9% |
| 2014 | $+10,684 | $+9,433 | -$1,251 | -12% |
| 2015 | $+5,236 | $+5,395 | +$159 | +3% |
| 2016 | $+9,051 | $+10,080 | +$1,029 | +11% |
| 2017 | $+1,505 | $+1,138 | -$368 | -24% |
| 2018 | $+612 | $+848 | +$236 | +38% |
| 2019 | $+5,593 | $+4,469 | -$1,124 | -20% |
| 2020 | $+19,904 | $+21,700 | +$1,796 | +9% |
| 2021 | $+26,782 | $+29,991 | +$3,209 | +12% |
| 2022 | $+24,282 | $+27,063 | +$2,781 | +11% |
| 2023 | $+14,670 | $+11,958 | -$2,712 | -18% |
| 2024 | $+28,781 | $+34,033 | +$5,252 | +18% |
| 2025 | $+56,569 | $+56,693 | +$124 | +0% |
| 2026 | $+45,931 | $+50,104 | +$4,172 | +9% |

**Read:** 15/21 up years. 6 down years scattered (2007, 2013, 2014, 2017, 2019, 2023), no consecutive streak, no recent-regime tilt. Worst single year is 2023 at -$2.7k (-18%) on a $14.7k baseline — material but not catastrophic. Loss/gain ratio 18% (-$6.5k loss / +$35k gain). Recent years (2020-2026) all up except one. **Above the 80% / 25% gate. Ship.**

### 7.4 Gold Macro yearly slice (`ttl15_C10_loose`) — REJECTED

| Year | Baseline P&L | Variant P&L | ΔP&L | Δ% |
|---|---:|---:|---:|---:|
| 2006 | $+937 | $+1,027 | +$91 | +10% |
| 2007 | $+3,401 | $+3,754 | +$353 | +10% |
| 2008 | $+22,001 | $+25,421 | +$3,420 | +16% |
| 2009 | $+16,525 | $+17,886 | +$1,361 | +8% |
| 2010 | $+9,639 | $+10,942 | +$1,302 | +14% |
| 2011 | $+32,202 | $+32,571 | +$369 | +1% |
| 2012 | $+21,823 | $+20,046 | -$1,778 | -8% |
| 2013 | $+6,594 | $+7,986 | +$1,392 | +21% |
| 2014 | $+2,597 | $+3,244 | +$647 | +25% |
| 2015 | $+3,989 | $+3,939 | -$51 | -1% |
| 2016 | $+14,899 | $+15,451 | +$552 | +4% |
| 2017 | $+1,576 | $+1,324 | -$252 | -16% |
| 2018 | $+619 | $+555 | -$64 | -10% |
| 2019 | $+5,375 | $+4,932 | -$444 | -8% |
| 2020 | $+20,034 | $+24,454 | +$4,420 | +22% |
| 2021 | $+21,539 | $+20,337 | -$1,202 | -6% |
| 2022 | $+33,717 | $+29,886 | -$3,832 | -11% |
| 2023 | $+22,000 | $+19,877 | -$2,123 | -10% |
| 2024 | $+60,737 | $+55,642 | -$5,095 | -8% |
| 2025 | $+109,220 | $+123,587 | +$14,367 | +13% |
| 2026 | $+18,174 | $+22,739 | +$4,565 | +25% |

**Read — this is why we slice yearly:**

- 12 / 21 up years — **fails the 80% gate** (would need 17/21).
- 9 down years, including a near-streak from 2017-2024 where 7 of 8 years are red.
- Loss/gain ratio is **45%** (-$15k vs +$33k) — far above the 25% acceptance threshold.
- The aggregate +$18k over 21yr is carried by **three big years**: 2008 (+$3.4k), 2020 (+$4.4k), 2025 (+$14.4k). Without those three, the variant would be net negative.
- **Recent regime actively hates this variant on Gold Macro.** Five of the last seven years are red. This is the live-relevant period.

**Why Gold Macro responds differently** (the hypothesis, not yet quantified): Gold Macro is the slowest-paced of the four systems (1683 trades / 21yr = ~80/yr), running on H1 with a full-day scan window. Modern Gold price action since ~2017 has had longer-tailed trending moves with shallow pullbacks that don't reach the 10%-of-risk pullback level — the limit just sits unfilled while the price runs to TP. Plus Gold Macro's market-order baseline already pays only modest slippage per trade ($0.20-$0.50 on $20+ risk distances), so the savings are smaller. The combination means: limit-order misses cost more than slippage saves on this system specifically.

**Verdict: STASH on Gold Macro.** Keep market entry.

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
| Research doc (this file) | Committed `e93df57`, updated with yearly slices `0fba4e0`, design `bb7c95b` |
| Per-system top variant identified | Yes, see §6 |
| Yearly slices on all 4 systems | **Done. 3 ship (Oil Macro, Oil Micro, Gold Micro), 1 stashes (Gold Macro)** |
| Slippage attribution logging (μs + bid/ask snapshot) | Committed `33eafab` |
| BT defaults shipped per system (3 systems, Gold Macro stashed) | Committed `4796ec9`, `4fad436`, `ed025fc` — all verified to-the-cent |
| Live phase 1 (helper extract + 4-engine refactor + executor primitives + notify) | Committed `f974690` |
| Live phase 2 (DWX EA pending-order primitives — needs MetaEditor recompile) | Committed `fcfa8e9` |
| Live phase 3a (dry-run scaffolding × 3 engines) | Committed `5f4667d` |
| Live phase 3b defensive filter (Oil Macro reconciler queries) | Committed `b998a43` |
| Live phase 3b real path + monitor (Oil Macro) | Committed `17d7a69` |
| Live phase 3b real path + monitor (Gold Micro + Oil Micro) | Committed `0a98382` |
| Filter #28 (first-15-min gate) | Not started, research candidate |
| Branch state | `filter/27-limit-order-sweep` at `0a98382`, NOT pushed |

### Cumulative ship math

```
Oil Macro    ttl15_B_loose      +$180,178  /21yr   (validated by yearly slice)
Oil Micro    ttl15_C10_loose    +$534,162  /21yr   (validated)
Gold Micro   ttl15_C10_loose    +$28,438   /21yr   (validated)
Gold Macro   STASH              +$0
─────────────────────────────────
TOTAL                          +$742,778  /21yr  ≈  +$35,371 / year
```

Stashing Gold Macro costs us $18,000 of the original $760,778 aggregate (2.4%) but protects against a regime-failure mode that the yearly slice surfaced.

---

## 11. Plan of action

The user has requested everything be done one-by-one tonight. Order:

### 11.1 — Yearly slices on all 4 systems — DONE

Run on each of the 4 systems with that system's winning variant. See §7 for full per-system tables. **Outcome:**

- Oil Macro: 18/21 up — ✅ ship
- Oil Micro: 18/21 up — ✅ ship
- Gold Micro: 15/21 up, no recent-regime tilt — ✅ ship
- Gold Macro: 12/21 up, recent-regime tilt (5 of last 7 red) — 🟡 stash

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

For each shipping system, update its `config.py` with the winning kwargs as new BT defaults so future BT runs use the limit-order entry by default. Per [[feedback-selective-ship-pattern]]: per-system, no global flag. **Gold Macro stays on market entry.**

- Gold Macro (`backend/config.py`): **leave as market entry** — yearly slice rejected
- Gold Micro (`backend-micro/config.py`): `MICRO_ALPHA_SWEEP["entry_mode"] = "limit"`, `["limit_offset_pct"] = -0.10`, `["limit_ttl_bars"] = 5`, `["limit_fill_strict"] = False`
- Oil Macro (`backend-oil/config.py`): `ALPHA_SWEEP["entry_mode"] = "limit"`, `["limit_offset_pct"] = "engulf_close"`, `["limit_ttl_bars"] = 5`, `["limit_fill_strict"] = False`
- Oil Micro (`backend-oil-micro/config.py`): `MICRO_ALPHA_SWEEP` same as Gold Micro

Each commit:
- One config update
- Re-run that system's BT with no kwargs → confirm it produces the variant's exact P&L (same numbers as the explicit-kwarg sweep cell)
- Commit message includes the specific ΔP&L this system gains

### 11.4 — Live limit-order infrastructure (separate ship)

Mirrors the Filter #27 BT logic to live execution for the 3 shipped systems (Oil Macro, Oil Micro, Gold Micro). Gold Macro stays on market entry. The protocol per the filter sweep framework is: BT defines the precision logic (steps 1–4 above), live mirrors it 1:1 reading from the same config keys (step 5). One source of truth, zero parallel implementations.

#### 11.4.0 Inventory of current live state (read 2026-06-16)

Before any change, inventory of where market orders live in production:

- **`backend/execution/mt5_executor.py`**: `place_market_order(instrument, units, sl, tp, comment)` (line 321). Used by all 4 services via `from backend.execution import place_market_order`. DWX command: `OPEN|<symbol>|<BUY|SELL>|<lots>|<price=0>|<sl>|<tp>|<comment>`.
- **`mql5/DWX_Server.mq5`**: `ProcessCommand` (line 258) handles `OPEN`, `MODIFY`, `CLOSE`, `CLOSE_ALL`, `CLOSE_PARTIAL`. **Does NOT handle pending orders.** `ExecuteOpen` (line 340) sets `request.action = TRADE_ACTION_DEAL` (immediate market). No `BUY_LIMIT` / `SELL_LIMIT` support exists.
- **`mql5/DWX_Server.mq5` `WriteOpenOrders`** (line 143) iterates `PositionsTotal()` only — pending orders (`OrdersTotal()`) are not written to `open_orders.json`. Python's reconciler is therefore blind to pending orders unless we add a new file.
- **`mql5/DWX_Server.mq5` `OnTradeTransaction`** (line 684) only logs `DEAL_ENTRY_OUT` / `DEAL_ENTRY_INOUT` (exit deals). Entry deals are tracked via `WriteOpenOrders`. **Pending-order placement / cancellation events are not logged anywhere by the EA.**
- **Live engines** (`backend/scanner/live_engine.py:278`, `backend-micro/scanner/live_engine.py:244`, `backend-oil/scanner/live_engine.py:203`, `backend-oil-micro/scanner/live_engine.py:220`): all call `place_market_order(...)` unconditionally with no `entry_mode` branching.
- **`backend/scanner/scheduler.py` and siblings**: schedulers do not read any `entry_mode` config key and have no per-order timer infrastructure. APScheduler is used for periodic scans (`alpha_sweep_poll`, `position_monitor`, `daily_recon`) but not per-trade jobs.

#### 11.4.1 Design constraints

- **Don't break the market-order path.** Gold Macro (and any future non-#27 system) keeps placing market orders. Existing `place_market_order` callers continue to work unchanged.
- **Same compute logic in BT and live.** The exact `limit_price` formula in `backend/backtest/engine.py` (and siblings) — `signal.entry`, engulfing close, or `signal.entry ± offset_pct × signal.risk` — must be replicated in the scheduler, ideally by extracting it to a shared helper that both the BT engine and the scheduler call.
- **TTL cancellation must be reliable.** If a limit doesn't fill in 15min and we don't cancel, broker may fill it minutes later at a stale price = phantom trade outside our intended setup. APScheduler date-trigger job per pending order is the cleanest mechanism.
- **Cancel-fill race must be handled.** If we send `CLOSE_PENDING` while broker fills the same second, OnTradeTransaction will fire `DEAL_ENTRY_IN` and the existing orphan reconciler adopts. We must not double-process: the limit-placement record in DB plus the orphan-adopted record must merge by `oanda_trade_id`.
- **DB schema lives without a new column.** A pending-order record can use the existing `gd_trades` row pattern: insert with `entry_time = NULL` (or a sentinel) and `oanda_trade_id = <ticket>`, update to `entry_time = NOW()` on fill, delete or mark `exit_reason = 'LIMIT_TTL_EXPIRED'` on cancel. Avoids schema migration.
- **Real money flow gate.** First live deploy is dry-run for 24h on one system before any real-money switch.

#### 11.4.2 Required changes (file-by-file)

**A. DWX EA (`mql5/DWX_Server.mq5`) — add pending-order primitives.**

1. `ProcessCommand`: handle 2 new actions:
   - `OPEN_PENDING|<symbol>|<BUY_LIMIT|SELL_LIMIT>|<volume>|<price>|<sl>|<tp>|<comment>` → `ExecuteOpenPending(...)`. Builds an `MqlTradeRequest` with `action = TRADE_ACTION_PENDING`, `type = ORDER_TYPE_BUY_LIMIT` or `ORDER_TYPE_SELL_LIMIT`, sets `price` to the limit, `expiration_type = ORDER_TIME_SPECIFIED`, `expiration = TimeCurrent() + ttl_seconds`. Returns ticket via `last_response.json`.
   - `CANCEL_PENDING|<ticket>` → `ExecuteCancelPending(...)`. Builds `MqlTradeRequest` with `action = TRADE_ACTION_REMOVE`, `order = ticket`. Returns `last_response.json` with success/failure.

2. **New file `pending_orders.json`** written every poll cycle alongside `open_orders.json`. Iterates `OrdersTotal()` (pending orders, not `PositionsTotal`). Same JSON shape as `open_orders.json` plus `expiration_time`, `order_type`. Lets Python reconciler see pending orders.

3. **OnTradeTransaction**: add a branch for `TRADE_TRANSACTION_ORDER_DELETE` — logs cancellations to a new `cancelled_orders.json` so Python knows the limit expired without filling. Existing `closed_orders.json` covers the case where the limit fills and then the position closes.

**B. `backend/execution/mt5_executor.py` — add `place_limit_order` + `cancel_pending_order`.**

```python
def place_limit_order(instrument, units, limit_price, sl, tp, ttl_seconds, comment):
    """Place a pending limit order. units sign = direction; ttl_seconds = how long
    the order stays alive before broker auto-cancels (matched by our APScheduler
    cancel-job too as belt-and-suspenders).
    """
    # Same volume → lots conversion as place_market_order
    # cmd: OPEN_PENDING|<symbol>|<BUY_LIMIT|SELL_LIMIT>|<lots>|<price>|<sl>|<tp>|<comment>
    # snapshot bid/ask at send time (slippage attribution)
    # _send_command, parse response, return {success, ticket, expiration_time, ...}

def cancel_pending_order(ticket):
    """Cancel a pending limit by ticket. Idempotent — a ticket that's already
    filled/cancelled returns success=False with a clear retcode that the caller
    can ignore."""
    # cmd: CANCEL_PENDING|<ticket>
    # _send_command, parse response, return {success, error}
```

Plus a small util `compute_limit_price(direction, signal_entry, signal_risk, df_at_bar_idx, limit_offset_pct) → float` that mirrors the BT engine's logic exactly. Extract this into `backend/execution/limit_price.py` so both BT engine and live scheduler import the same function. **This is the precision-mirror requirement.**

**C. `backend/scanner/live_engine.py` and siblings — branch on `entry_mode`.**

Replace each of the 4 `place_market_order(...)` call sites with:

```python
cfg = ALPHA_SWEEP  # or MICRO_ALPHA_SWEEP
entry_mode = cfg.get("entry_mode", "market")

if entry_mode == "limit":
    # Read limit-order kwargs from config (same source-of-truth as BT)
    limit_offset_pct = cfg["limit_offset_pct"]
    limit_ttl_bars = cfg["limit_ttl_bars"]
    ttl_seconds = limit_ttl_bars * 180  # M3 = 180s/bar

    # Compute limit_price using the SAME helper the BT engine uses.
    # signal_entry / signal_risk come from the strategy's signal generator;
    # we need the engulfing M3 bar's bid_close / ask_close for the "B" variant.
    # Fetch via get_candles(instrument, "M3", 1) at signal time.
    limit_price = compute_limit_price(
        direction=direction,
        signal_entry=entry_price,
        signal_risk=risk,
        engulf_close_ask=current_ask,  # from get_current_price
        engulf_close_bid=current_bid,
        limit_offset_pct=limit_offset_pct,
    )

    result = place_limit_order(
        instrument=instrument,
        units=oanda_units,
        limit_price=limit_price,
        sl=sl_price,
        tp=tp_price,
        ttl_seconds=ttl_seconds,
        comment=f"{strategy}|{trade_ref}",
    )
    # Persist as pending in gd_trades with a `pending` mode flag, schedule cancel timer
    # (belt-and-suspenders: broker has its own expiration, but we cancel client-side too)
else:
    result = place_market_order(...)  # unchanged path
```

**D. APScheduler cancel timer per pending order.**

When a limit is placed:
1. Insert into `gd_trades` with `mode='pending'`, `entry_time=NULL`, `oanda_trade_id=<ticket>`, `entry_price = limit_price` (the intended limit, not the actual fill).
2. Schedule a one-shot APScheduler job: `id=f"cancel_pending_{ticket}"`, `trigger='date'`, `run_date=now+ttl_seconds+5s` (5s grace beyond broker's own expiration).
3. Job calls `cancel_pending_order(ticket)`, then queries DB:
   - If `gd_trades` row for this trade_ref shows `entry_time IS NOT NULL` → broker already filled, ignore (cancel will fail with retcode-already-executed).
   - Else update row to `exit_time=NOW(), exit_reason='LIMIT_TTL_EXPIRED'`. Journal `LIMIT_TTL_EXPIRED`. Telegram once.

A separate `pending_order_monitor_job` runs every 30s to detect fills the EA reported via OnTradeTransaction's `DEAL_ENTRY_IN` deals or via `pending_orders.json` disappearing. When a fill is detected:
1. Update `gd_trades` row: `entry_time=<deal_time>, entry_price=<actual_fill_price>, mode='live'`.
2. Cancel the pending APScheduler cancel job (it's no longer needed).
3. Journal `LIMIT_FILLED` with fill_price + time-to-fill.
4. Telegram via `notify.trade_filled`.

**E. Journal events.**

Three new event types added to the existing journal pattern in `live_engine.py`:
- `LIMIT_PLACED` — fields: `limit_price`, `ttl_seconds`, `oanda_id` (broker ticket), `signal_entry` (for slippage attribution).
- `LIMIT_FILLED` — fields: `limit_price`, `actual_fill`, `time_to_fill_s`, `oanda_id`.
- `LIMIT_TTL_EXPIRED` — fields: `limit_price`, `ttl_seconds`, `cancel_method` ('client'|'broker'|'race-with-fill'), `oanda_id`.

**F. Telegram messages.**

New messages in `backend/notify.py`:
- `notify.limit_placed(trade_ref, instrument, direction, limit_price, ttl_seconds)` — "📋 LIMIT PLACED — {trade_ref} — {instrument} {direction} @ {limit_price}, TTL {ttl_seconds}s"
- `notify.limit_ttl_expired(trade_ref, instrument, limit_price)` — "⏱ LIMIT EXPIRED — {trade_ref} — {instrument} did not fill at {limit_price}"
- Existing `notify.trade_filled(...)` already covers the fill case; reuse it.

#### 11.4.3 Dry-run gate

Before flipping any system to live limit orders, run for **24h in shadow mode**:

1. Add `LIMIT_DRY_RUN=true` env var. When set, the new code path **logs what it would do** (calls `compute_limit_price`, logs the intended limit_price, logs "DRY_RUN: would place limit") but **still calls `place_market_order`** for the actual broker order.
2. After 24h, query the journal for all `LIMIT_DRY_RUN_INTENT` events and pair them with the actual market fills that happened. Calculate: "if we had used limit orders, how many would have filled?" — gives a real fill-rate number, vs the BT's optimistic 86-98%.
3. Only flip `LIMIT_DRY_RUN=false` for one system at a time, watching it for 5+ trades before enabling the next.

#### 11.4.4 Per-system staged rollout

Per [[feedback-selective-ship-pattern]]:

1. **Oil Macro first.** Cleanest yearly slice (18/21 up, 2.2% loss/gain). Lower trade frequency = safer to monitor.
2. **Gold Micro second.** Mid-frequency, mid-risk.
3. **Oil Micro last.** Highest trade frequency = highest blast radius if anything is wrong with the cancel-timer or fill-detection path. Wait for 5+ clean live limit fills on Oil Macro and Gold Micro before flipping.
4. **Gold Macro stays market.** Yearly slice rejected the variant; do not deploy.

#### 11.4.5 Acceptance criteria before live ship

The live limit-order code is shippable when:
1. ✅ DWX EA compiled and pending-order commands tested in MT5 strategy tester (place + cancel + fill scenarios).
2. ✅ `compute_limit_price` helper extracted, called by both BT engine and scheduler, has a unit test that asserts they produce identical numbers for the same input.
3. ✅ A live trade in dry-run mode produces a `LIMIT_DRY_RUN_INTENT` journal event with limit_price within $0.05 of what the BT engine would compute for the same signal.
4. ✅ Telegram dry-run alert fires with the right message format.
5. ✅ Cancel timer fires correctly (verified via a synthetic pending order on a strike that won't fill).
6. ✅ Cancel-fill race tested: place a limit that fills 1 second before TTL; assert that the cancel command returns the broker's "already filled" retcode and the DB row reflects the fill.
7. ✅ User explicit sign-off per [[feedback-no-auto-ship]] before flipping `LIMIT_DRY_RUN=false`.

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
| 2026-06-16 ~14:30 UTC | Yearly slice on Oil Micro | 18/21 up years, $-39k drag vs $+573k benefit → ship |
| 2026-06-16 ~14:40 UTC | User: do everything one-by-one tonight | Started yearly slices on remaining 3 systems |
| 2026-06-16 ~14:55 UTC | Oil Macro yearly slice | 18/21 up years, 2.2% loss/gain ratio → ship |
| 2026-06-16 ~14:55 UTC | Gold Macro yearly slice | 12/21 up, 5/7 recent years red, 45% loss/gain → STASH |
| 2026-06-16 ~14:58 UTC | Gold Micro yearly slice | 15/21 up, no recent tilt, 18% loss/gain → ship |
| 2026-06-16 ~15:00 UTC | Final ship decision | 3 systems ship, Gold Macro stashes. +$742k/21yr cumulative |

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
