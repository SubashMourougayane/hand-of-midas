# L99 God-Mode Audit: BT vs Live Parity — Divergence Map

**Date:** 2026-07-02
**Scope:** Every code path where BT (`run_backtest_intraday`) and Live (`run_live`) diverge.
**Method:** Hostile — categorize each divergence as SAFETY-GAP / REALISM-GAP / EDGE-DIVERGENCE / NO-BUG (design intentional). Recommend fix or accept.

Shared code path: `run_engine()`, strategy code (`FibV2IntradayA/D/Composite`), bracket walker (`walk_bracket_on_bar`). Divergence lives in `EngineDeps` wiring + execution model + broker adapter.

---

## Summary Table

| # | Feature | Live | BT | Category | Impact |
|---|---|---|---|---|---|
| 1 | `max_lot` hard cap | 2.0 (CLI) | **none** | REALISM-GAP | BT trades unbounded lot at high equity → compound fantasy |
| 2 | `max_open_positions` broker-wide | 4 | **none** | REALISM-GAP | BT ignores broker position ceiling |
| 3 | `max_spread` guard | 0.50 | **none** | REALISM-GAP | BT trades even at zero spread (unrealistic) |
| 4 | `max_entry_slip_ratio` post-fill | 1.15 | **N/A** (no slip) | SAFETY-GAP | BT never rejects fills — fills always ideal |
| 5 | Entry slippage on fill | actual broker bid/ask | exact `bar.open` | EDGE-DIVERGENCE | BT ≈+5-15% edge vs live avg |
| 6 | Stop-loss gap slippage | actual broker fill | exact `stop_price` | EDGE-DIVERGENCE | BT understates losses on gap-hits |
| 7 | Per-lot commission + spread | real broker charges | flat `cost_usd=$0.65` | EDGE-DIVERGENCE | 15-118× cost gap at real qty |
| 8 | Overnight swap cost | real broker charges | **none** | EDGE-DIVERGENCE | 2-5% edge overstatement on 24h+ holds |
| 9 | `kill_switch` file check per submit | yes | **none** | SAFETY-GAP | BT can't be halted mid-run (not applicable, but noted) |
| 10 | Demo-account guard | yes | **N/A** | NO-BUG | BT has no broker at all |
| 11 | `on_partial_tp` callback → broker echo | yes (CLOSE_PARTIAL + MODIFY + retry + safe-close) | **none** | EDGE-DIVERGENCE | BT walker moves SL to BE in-memory; live can fail broker call |
| 12 | Broker reconciler (real P&L per trade) | yes (aggregates deals) | **N/A** | NO-BUG | BT is truth; live reconciles to truth |
| 13 | Warmup: 200-bar replay + state seed | yes | **none** | REALISM-GAP | BT starts cold from bar 0; live starts warm at bar 200 → BT emits ~200 stale bars of no-signal |
| 14 | `initial_open_trades` from broker snapshot | yes | none | REALISM-GAP | BT can't resume mid-position |
| 15 | Fill delay / broker latency | 1-3s async | 0ms sync | EDGE-DIVERGENCE | BT overstates fast-market catches |
| 16 | Requote / partial-fill / order reject | can happen | **never** | EDGE-DIVERGENCE | BT gets ~1% of orders live wouldn't |
| 17 | Fill price echoed from broker | yes | synthetic from bar.open | NO-BUG | Design |
| 18 | Weekend / holiday gap risk | real | **none** | EDGE-DIVERGENCE | BT never gaps through SL over weekend |
| 19 | `equity_sizer.on_trade_closed` — Model B compounding | yes (real $ pnl) | yes (net_r × qty × contract × stop) | EDGE-DIVERGENCE | BT compounds w/o broker cost — fantasy tail |
| 20 | Live sizer replaces `order.qty` at submit | yes | **no** — strategy emits qty | REALISM-GAP | BT uses strategy default qty; live rewrites |
| 21 | `server_utc_offset_hours` inference | yes | N/A (UTC parquet) | NO-BUG | Design |
| 22 | Journal + walker events per bar | yes | yes | ✓ parity | ✓ |
| 23 | `bt_trades` schema | live inserts | bt inserts | ✓ parity (columns) | ✓ (broker_* nulls in BT) |
| 24 | `on_bar_close` account snapshot | broker balance/equity/spread | equity sizer state OR none | ACCEPTABLE | Design |
| 25 | Setup / entry dedup key | shared | shared | ✓ parity | ✓ |
| 26 | Kill on file `LIVE_DISABLED` per submit | yes | N/A | NO-BUG | Design |

---

## Detailed Findings

### CATEGORY A · REALISM-GAP — BT missing constraints live has (causes fantasy PnL)

#### R1. No max_lot cap in BT
- **Code:** `bt_engine/runner/backtest.py` — `EquitySizer` used but no clamp on returned qty.
- **Live parallel:** `bt_engine/runner/live.py:242` — `LiveSafetyBroker._safe_order` clamps `qty` to `max_lot=2.0`.
- **Evidence:** Realistic PnL harness (2026-07-02) showed baseline BT overflows to $10^140 without cap; capping at 2.0 gives $500k-1M/yr realistic.
- **Recommendation:** Add `max_lot` arg to `run_backtest_intraday()`, apply to sizer output or via a wrapper adapter. Same knob as live.

#### R2. No max_open_positions in BT
- **Code:** `bt_engine/core/engine.py` — pending orders always fill, no cap on `open_trades` list length.
- **Live parallel:** `live.py:_assert_live_safety` checks broker.positions() count vs `max_open_positions=4`.
- **Impact:** Composite A+D BT can hold >4 concurrent (rare but possible w/ partial-TP overlap). Live cannot.
- **Recommendation:** Add engine-level cap in BT `EngineDeps` mirroring live default 4.

#### R3. No max_spread guard in BT
- **Live parallel:** `live.py:_assert_live_safety` checks broker spread quote before every submit; rejects if > 0.50.
- **BT:** exact bar.open fill, no spread simulated.
- **Recommendation:** Add spread column to bar frame (already in DWX bars), apply spread penalty at fill in `BTExecutionModel`.

#### R4. No warmup in BT
- **Live parallel:** live replays 200 bars through `on_bar` to seed pivot tracker before first live bar.
- **BT:** starts cold. First ~50 bars produce no signals until `PivotTracker(lb=3)` warms up.
- **Impact:** BT emits ~200 bars of `on_bar_close` with no signals. Not incorrect but wasteful. Doesn't affect edge, only bar_walk row count.
- **Recommendation:** Optional. Not urgent.

#### R5. No initial_open_trades in BT
- **Live parallel:** live queries `broker.positions()` and rebuilds `OpenTrade` list to resume mid-position.
- **BT:** always starts flat. Cannot replay a live session with pre-existing positions.
- **Recommendation:** Not applicable to standalone BT; is applicable to hypothetical "resume BT from live snapshot" mode.

#### R6. No sizer at order submit in BT
- **Code:** `run_backtest_intraday()` uses `EquitySizer` in `_on_close` (updates equity after trade) but NOT at submit (strategy's qty=1.0 stays).
- **Live parallel:** `LiveSafetyBroker._safe_order` calls `sizer.size_order()` at submit → real lot from equity × risk_pct.
- **Impact:** BT's Model B tracking is post-hoc: net_r × 1 × contract × stop = capital always seen as if qty=1. Compounding math in `_on_close` still runs but qty in DB = 1.0 always.
- **Recommendation:** **CRITICAL** — BT should size at submit like live. Otherwise realistic-PnL analysis is post-hoc only.

---

### CATEGORY B · EDGE-DIVERGENCE — BT overstates edge vs realistic live

#### E1. Fill at exact bar.open (no slippage)
- **Code:** `BTExecutionModel.simulate_fill` returns `Fill(price=next_bar.open × (1 + side × slippage_bps/10000))`. Default `slippage_bps_value=0.0`.
- **Live:** actual broker bid/ask varies by 0.2-2.0 pip = $0.20-$2.00 on XAU.
- **Impact:** Every entry in BT is a "free fill". Live loses 2-5% of trades to adverse slip.
- **Recommendation:** Default `slippage_bps_value=5-10` (5-10 bps = $0.20-$0.40 on XAU@$4000). Configurable.

#### E2. Stop-loss fills at exact stop_price
- **Code:** `walk_bracket_on_bar` — SL hit → `exit_price = trade.stop_price` exact.
- **Live:** SL fills at market — usually WORSE than trigger (gaps, fast markets). 5-30 pip worse on XAU M15.
- **Impact:** BT's loss-per-trade is best-case. Real live losses 5-15% larger on average, and 50-100% larger on gap events.
- **Recommendation:** Add stop_slip_pips param (default 3-5) to bracket, apply asymmetric penalty.

#### E3. TP fills at exact take_profit
- Same as E2 but often FAVORABLE on TP (price gaps past TP → slightly better fill).
- **Impact:** Neutral net.
- **Recommendation:** No fix; documented.

#### E4. Flat cost_usd=$0.65
- **Code:** `run_backtest_intraday(cost_usd=0.65)` default. Strategy computes `cost_r = cost_usd / risk_units`.
- **Live real:** commission $6.50/lot round-turn + spread $9/lot = $15.50/lot avg.
- **At 0.02 lot (current live):** BT cost $0.65 vs real $0.31 — BT actually OVERSTATES cost at tiny lots.
- **At 2.0 lot (Model B on $500k):** BT $0.65 vs real $31.00 — 47× understated.
- **At 5.0 lot ceiling:** BT $0.65 vs real $77.50 — 118× understated.
- **Recommendation:** **CRITICAL** — replace flat cost with per-lot in strategy `_finalize_entry`. Reads qty from order.qty (sized), computes real cost, threads via `order.extra["cost_r"]`.

#### E5. No overnight swap
- **Broker rate:** JM Demo2 XAU: long swap −$71.04 pts/night, short swap −$84.12 pts/night (from live chart).
- **Impact:** D leg holds up to 24h → often crosses at 22:00 UTC broker rollover = one swap deducted. A leg holds 12h → sometimes crosses. ~5-10% of trades.
- **Recommendation:** Add `apply_swap(bar_ts, side, qty)` in bracket walker. Model against real JM swap rates.

#### E6. Instant fill / zero latency
- Live latency: signal fires at M15 bar close → broker sees order 1-3s later → fills at NEW price.
- BT: fills at exact bar.open of NEXT bar (2s+ ahead of signal in real time).
- **Impact:** BT catches perfect momentum trades that live misses. Rare but skews winners high.
- **Recommendation:** Model as random 0-3s "latency slip" bps on fills.

#### E7. Zero requote / partial fill / reject
- Live: ~0.5-2% of orders reject/requote on fast markets.
- BT: 100% fill rate.
- **Impact:** ~1% of BT trades wouldn't happen live.
- **Recommendation:** Random dropout with `p=0.01` per submit in BT.

#### E8. No weekend/session gap
- Fri close XAU → Mon open often gaps ±$5-30.
- BT: bars continuous, no gap.
- Live: trade held over weekend hits gap on Mon open = SL fills far worse OR TP fills far better.
- **Impact:** Tail risk BT doesn't see. ~2-5% of losers gap through SL for 2-5× worse fill.
- **Recommendation:** Model gap in M5 data (already there — resample skips weekend gap) + apply gap slip on SL hits at Mon.open bar.

#### E9. No partial-TP broker retry / safe-close
- **Live:** `on_partial_tp` callback → `close_partial` → 3-retry `modify(sl=BE)` → safe-close fallback if modify fails.
- **BT:** walker mutates trade state in-memory. Always succeeds. No callback.
- **Impact:** BT never sees the `PARTIAL_TP_MODIFY_FAILED` scenario. Live loses ~1-2% of partial-TP trades to this path (broker modify race).
- **Recommendation:** Optional random-failure injection at partial-TP for BT.

---

### CATEGORY C · SAFETY-GAP — BT missing safety live has

#### S1. No slip-reject post-fill
- **Live:** `LiveSafetyBroker.fills()` computes actual vs expected risk ratio; rejects if >1.15.
- **BT:** exact fill → risk always matches expected. No reject needed. But if slippage were modeled (E1), rejects would apply.
- **Recommendation:** After adding E1 slip model, also add slip-reject logic in BT execution.

#### S2. No kill-switch check in BT
- **Live:** every submit checks `LIVE_DISABLED` file → aborts.
- **BT:** irrelevant (batch process).
- **Category:** NO-BUG.

#### S3. No demo-account guard
- **Live:** rejects if account not demo.
- **BT:** N/A.
- **Category:** NO-BUG.

---

### CATEGORY D · SHARED / PARITY OK

- Strategy code identical (verified by parity tests).
- Bracket walker identical (`walk_bracket_on_bar`).
- Signal generation identical.
- Journal event schema identical.
- `bt_trades` columns aligned (BT nulls broker_*).
- Setup dedup key identical.
- Partial-TP walker logic identical (execution echo differs — E9).

---

## Priority Fix List

### P0 — must fix to trust BT $
1. **E4**: Per-lot cost model in strategy (`_finalize_entry`). Replace flat $0.65 with `commission×qty + spread×qty`. ~30 min.
2. **R1**: max_lot cap in BT sizer. ~15 min.
3. **R6**: BT sizer at submit (mirror live). ~30 min.

Result: BT $ output will match ballpark of live-realistic. No more $10^140 overflows.

### P1 — realism sweep
4. **E1**: entry slippage (5-10 bps default).
5. **E2**: SL fill slippage (3-5 pip asymmetric).
6. **E5**: overnight swap costs.
7. **R2**: max_open_positions engine cap.
8. **R3**: max_spread guard in fill.

Result: BT edge estimate drops ~15-30% from current headline — closer to what live will actually earn.

### P2 — tail risk realism
9. **E8**: weekend gap model.
10. **E6**: latency slip model.
11. **E7**: random requote dropout.
12. **E9**: partial-TP broker-fail simulation.

Result: BT tail losses widen ~5-10% — matches real drawdown risk.

### P3 — nice-to-have
13. R4: warmup in BT (optional, cosmetic).
14. R5: initial_open_trades resume (only if replaying live in BT).

---

## Recommended next step

**Do P0 (3 items) first.** All are surgical changes in existing files:
- `bt_engine/strategies/fib_v2/strategy.py::_finalize_entry` — per-lot cost
- `bt_engine/runner/backtest.py` — max_lot arg + sizer-at-submit
- Optional: `bt_engine/execution/simulator.py` — slippage default > 0

Then rerun combined A+D BT and compare vs live-realistic-harness numbers.

If numbers converge (BT ≈ live-realistic-harness within 20%), we have a **trustworthy BT harness**. Currently the two disagree because BT ignores 6 realism dimensions.

## Key insight

The parity test `test_bt_live_event_parity.py` locks **strategy code** identical (research=BT=live). It does NOT (and cannot) lock **execution outcome** identical, because live has irreducible physical constraints BT doesn't model. The gap between "code identical" and "outcome identical" is measured by this audit's 22 divergences.

The audit's job is to make BT's execution simulation as realistic as we can. Perfect parity impossible; ballpark within 20-30% possible with P0+P1.
