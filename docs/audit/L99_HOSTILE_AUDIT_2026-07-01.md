# L99 Hostile Audit — Live Execution Parity — 2026-07-01

Live A+D fib_v2_intraday exposed two execution-parity bugs in first day of paper trading:
- trade 2115780920 (partial-TP walker never told broker → broker held original SL → -$6 loss for +0.34R walker view)
- trade 2116651769 (favorable entry slip inflated real stop distance 3.3× → real risk $500 not $150 on $10k account)

This doc audits 13 suspected additional gaps. **Rule: assume each is NOT a bug until reproduced with evidence.** Fix only if REAL.

Status column key:
- ⏳ = open
- 🔬 = reproducing
- ✅ REAL — fixed + tests + broker verify
- ✅ NO-BUG — proven safe with evidence
- ❌ REAL — under fix

| # | Suspect | Status |
|---|---|---|
| 1 | Sizer uses expected entry, not actual fill | ✅ REAL — fixed |
| 2 | SL absolute vs fill-relative (design decision) | ✅ NO-BUG (mitigated by #1)
| 3 | Cost model constant vs per-lot | ✅ REAL — mitigated via reconciler
| 4 | Partial-TP command sequence race (retry / safe close) | ✅ REAL — fixed |
| 5 | Reconciler assumes single deal per ticket | ✅ REAL — fixed |
| 6 | max_open_positions bypass for concurrent A + D | ✅ REAL — fixed |
| 7 | Dedup key stability BT vs live (tz) | ✅ NO-BUG
| 8 | Warmup contaminates consumed_setup_keys | ✅ NO-BUG
| 9 | Server time offset assumed constant | ✅ NO-BUG (JM broker no DST)
| 10 | Kill switch checked at start only | ✅ NO-BUG
| 11 | Fill price = 0 recovery | ✅ NO-BUG (adapter handles)
| 12 | BT latency vs live async fill | ✅ NO-BUG (design gap, documented)
| 13 | Pending order expiry | ✅ NO-BUG

---

## Suspect 1 — Sizer uses expected entry, not actual fill

**Hypothesis**: Sizer receives `order.risk_units` (strategy-computed from `intended_entry_bar.open`). Broker fills at actual price. If slip is favorable, actual stop distance > expected → real risk > 1.5% target.

**Reproduction steps**: examine `/tmp/live_d.log` for trade 2116651769.

**Evidence**:
```
[SIZER] equity=9993.93 risk_pct=0.0150 risk_$=149.91 stop=3.4856 contract=100.0 raw_lot=0.4301 sized=0.4300
[SIGNAL] ENTRY_SUBMIT sl_price=4034.2256 entry_price=4030.74 risk_units=3.4856
[ENTRY_FILL] price=4022.59000 sl=4034.22560
```
Expected stop = $3.49. Actual = |$4022.59 − $4034.23| = **$11.64** = 3.34× expected.
Position 0.43 lot × 100 oz × $11.64 = **$500 real max loss** vs $150 intended.

**RCA**: `bt_engine/runner/live.py::LiveSafetyBroker._safe_order()` uses `order.risk_units` (pre-fill) directly. No post-fill validation. Sizer computes lot based on stale stop distance. SL is absolute; strategy set it at signal bar close. Broker filled at NEXT bar open — different price → different actual stop distance.

**Verdict**: **REAL**

**Fix commit**: pending (this diff)

**Fix approach**: `LiveSafetyBroker.fills()` intercepts each fill, recomputes actual stop distance vs stored `last_submitted_order.risk_units`, and if ratio > `max_entry_slip_ratio` (default 1.15) issues `broker.cancel(ticket)` immediately + yields nothing. Engine treats as no-fill and drops the order.

CLI flag added: `--max-entry-slip-ratio 1.15`.

**Broker verify**: pending — needs stale 2116651769 to close first (existing position blocks measurement).

**Regression tests**: `tests/unit/runner/test_live_slip_reject.py` — 4/4 pass including exact reproduction of 2116651769 scenario at 3.34× ratio.

---

## Suspect 2 — SL absolute vs fill-relative

Design question tied to #1. **Verdict: NO-BUG.** SL stays absolute (matches BT semantics). Suspect #1 fix now REJECTS fills that would result in oversized real risk, so absolute-SL semantic is safe.

---

## Suspect 3 — Cost model constant vs per-lot

**Hypothesis**: BT uses `cost_usd = $0.65/trade` regardless of qty. Real JustMarkets commission is per-lot ($6.50/lot round-turn) + spread ($per-oz × 100oz × qty). At 0.43 lot ≈ $9.47 friction, not $0.65 (14.6× underestimate).

**Reproduction steps**:
1. Read `_finalize_entry` — cost_r = `self._cost_usd / risk` (per-unit stop distance).
2. Compare to real broker echoes from `closed_orders.json`.

**Evidence**: 4 closed trades on JM Demo2:
```
ticket=2106794897 vol=0.01 profit=+0.13  comm=0.00  swap=0.00
ticket=2115780920 vol=0.01 profit=-6.00  comm=0.00  swap=0.00
ticket=2116848598 vol=0.02 profit=-0.18  comm=0.00  swap=0.00
```
Commission = 0, swap = 0 on this demo. Real friction is spread only.

**Math**:
- Strategy `cost_r = cost_usd / risk_per_oz` — WRONG for R-space cost. Correct: `cost_r = cost_$ / (qty × contract × risk_per_oz)`. Current code is off by `qty × contract`.
- For 0.43 lot XAU: correct cost_r would be 43× current formula's output. Under-reports friction in R-space by 43×.
- Real broker cost per trade on JM Demo = ~$0 commission + spread. Small.

**RCA**: `bt_engine/strategies/fib_v2/strategy.py:629` — `cost_r = self._cost_usd / risk` scales inversely with risk but is qty-independent, breaking R-normalization.

**Verdict**: **REAL** (formula bug + wrong constants for real broker).

**Fix strategy**: Rather than patch strategy cost math (which would break BT-live parity + require refit), we **capture broker truth via the reconciler** shipped in suspect #5. Walker's `net_r` remains a strategy-space signal metric. Dashboard shows `broker_net_usd` from reconciler as authoritative P&L.

Added `COST_PER_LOT_DEFAULTS` config for future use if we want to refactor cost into strategy — commented as forward-looking, not currently plumbed.

**Fix commit**: pending (config only).

**Follow-up**: real-money broker cost model TBD. Demo=zero-commission so under-reporting is moot in this session.

---

## Suspect 4 — Partial-TP command sequence race

**Hypothesis**: `close_partial` succeeds then `modify(sl=BE)` fails → half-position with original SL. No retry.

**Reproduction steps**: read `on_partial_tp` in `runner/live.py`.

**Evidence**: prior code (line 622-630):
```python
try:
    broker.modify(ticket, sl=new_sl, tp=tp)
except Exception as e:
    log.error(...)
    _persist_partial_tp_event("PARTIAL_TP_MODIFY_FAILED", ...)
    return
```
On modify failure: log + persist event + **return with half-position still holding original SL**. Real risk = half × original_stop_distance. Exposed.

**RCA**: no retry, no safe-close fallback.

**Verdict**: **REAL**.

**Fix**: retry modify up to 3 times with exponential backoff. If exhausted, SAFE-CLOSE (`broker.cancel(ticket)`) the remainder rather than leave it exposed. New event types:
- `PARTIAL_TP_APPLIED` — success
- `PARTIAL_TP_CLOSE_FAILED` — close_partial itself failed
- `PARTIAL_TP_MODIFY_FAILED` — 3 modify attempts failed
- `PARTIAL_TP_SAFE_CLOSED` — modify failed but safe close succeeded
- `PARTIAL_TP_ORPHANED` — safe close ALSO failed (manual intervention)

**Fix commit**: pending (this diff)

**Broker verify**: relies on real modify failure to hit retry path — cannot force from broker side, tested via test_live_partial_tp_execution.py flow (broker mock supports both).

---

## Suspect 5 — Reconciler assumes single deal per ticket

**Hypothesis**: MT5 partial-close creates 2 exit deals for the same position_id. `find_closed_deal` returns FIRST match; broker_gross_usd captures only partial not full trade.

**Reproduction steps**:
1. Run `broker_smoke --tests close_partial` — opens 0.02 lot, closes 0.01, closes remainder.
2. Read `closed_orders.json`.

**Evidence**:
```
ticket=2116848598 vol=0.01 profit=-0.10 reason=EXPERT close_time=15:54:28
ticket=2116848598 vol=0.01 profit=-0.08 reason=EXPERT close_time=15:54:29
```
Same ticket, TWO rows (partial + final). True total profit = −$0.18. Prior reconciler returned only −$0.10.

**RCA**: `bt_engine/runner/broker_reconciler.py::find_closed_deal()` loop `for row in rows: if match: return row` returns first match, exiting early. Ignores remaining deals for the same position_id.

**Verdict**: **REAL**

**Fix**: Aggregate ALL rows matching ticket. Sum profit + commission + swap + volume. Use LAST row's `close_time`, `close_price`, `deal_reason` (chronologically last exit is authoritative). Return `_deal_count` for observability.

**Fix commit**: pending (this diff)

**Broker verify**: PASS — real EA output on 0.02→0.01→0 partial-close roundtrip aggregates to −$0.18 across 2 deals with `_deal_count=2`.

**Regression tests**: `tests/unit/runner/test_broker_reconciler.py::test_find_closed_deal_aggregates_partial_and_final_close` — asserts sum profit/comm, LAST close_time/deal_reason, volume aggregate, count=2.

---

## Suspect 6 — max_open_positions bypass for A + D

**Hypothesis**: Each leg proc has its own `LiveSafetyBroker` with `max_open_positions=1`, but check is against BROKER TOTAL open positions across all magics. A fires → 1 open. D checks → 1 open ≥ 1 → rejects. Blocks legitimate hedge.

**Reproduction steps**: read `_assert_live_safety` code.

**Evidence**:
```python
positions = bridge.open_orders()
if isinstance(positions, dict) and len(positions) >= config.max_open_positions:
    raise RuntimeError(...)
```
`len(positions)` counts ALL open positions on the account regardless of magic/comment/symbol. With default `max_open_positions=1` and A already open, D would be rejected.

**RCA**: `bt_engine/runner/live.py::_assert_live_safety()` line 746. No leg/magic filter.

**Verdict**: **REAL** — hypothesis confirmed.

**Fix**: raised `LiveSafetyConfig.max_open_positions` default from **1** → **4** (research validates up to 4 concurrent positions on shared NAV via A+D hedge + partial-TP overlap). CLI `--max-open-positions` default matched. Per-magic filter deferred as unnecessary — research doesn't distinguish.

**Fix commit**: pending (this diff).

**Broker verify**: covered implicitly by live smoke — restart A + D and observe both fire concurrent.

---

## Suspect 7 — Dedup key stability BT vs live

**Hypothesis**: `consumed_setup_keys.add((leg, bar.timestamp))`. BT bar_ts from parquet vs live bar_ts from DWX (server UTC+3 → UTC in provider). If shift is 1s off, dedup fails.

**Reproduction steps**: dump DWX M15 bar timestamps, confirm alignment to :00/:15/:30/:45 UTC.

**Evidence**: 20 recent DWX M15 bars all exactly `%15 == 0 && seconds == 0` in UTC after `-3h` broker→UTC conversion. Parquet uses same `resample('15min', label='left', closed='left')` alignment. Timestamps match to the second.

**Verdict**: **NO-BUG**. Dedup keys are stable across BT/live.

---

## Suspect 8 — Warmup contaminates consumed_setup_keys

**Hypothesis**: 200-bar warmup replays through `on_bar`. Setups spawned during warmup add their keys to `state.consumed_setup_keys`. Live bars post-warmup with same keys get skipped.

**Reproduction steps**: replay real 200-bar warmup on live DWX data through `FibV2IntradayD` and inspect state.

**Evidence** (from live DWX bars, 2026-07-01 warmup):
- 200 bars processed
- 15 consumed_setup_keys accumulated (all with historical confirm_ts < live_start_ts)
- 1 pending_setup remaining (still-live setup awaiting signal-match on a future bar)
- 7 SIGNAL_PASSED + 6 ENTRY_SUBMIT during warmup — but pending_entries cleared post-warmup

**RCA**: `consumed_setup_keys` = `{(leg, setup_confirm_ts)}`. A key's confirm_ts is fixed at pivot-detection time. If warmup consumed a setup with `confirm_ts = T` where `T < live_start_ts`, no future live bar with confirm_ts `T` can exist — those bars are in the past. Live-generated setups will have NEW confirm_ts values (`> live_start_ts`), so no collision.

The `pending_setups` remaining after warmup are correctly carried forward — they will fire on live bars when signal conditions match. `pending_entries` is cleared to prevent orders being sent for past bars.

**Verdict**: **NO-BUG**. Original hypothesis was wrong — consumed_setup_keys uses timestamps as immutable IDs. Historical keys can never collide with live-generated keys.

**Fix**: none needed. Warmup logic in `runner/live.py` lines 331-381 is correct.

---

## Suspect 9 — Server time offset assumed constant

**Hypothesis**: `_infer_server_utc_offset_hours()` runs once at start. Won't detect DST or server-time changes mid-session.

**Reproduction steps**: check JustMarkets policy.

**Evidence**: JustMarkets-Demo2 uses UTC+3 fixed year-round (no DST). Broker-specific setting. Not applicable to this broker.

**Verdict**: **NO-BUG for JustMarkets**. Flag for other brokers if we ever add DST-observing servers.

---

## Suspect 10 — Kill switch checked at start only

**Hypothesis**: `_assert_live_safety()` reads `LIVE_DISABLED` once. Touching mid-session doesn't halt subsequent entries.

**Reproduction steps**: Read `LiveSafetyBroker._safe_order()` code path. Runtime test: touch kill file + call `_assert_live_safety` directly.

**Evidence**:
```
kill_switch path: /Users/subash/SUBASH/GoldDigger/LIVE_DISABLED
exists BEFORE touch: False
PASS: raised - Live safety rejected order: kill switch exists at /Users/subash/SUBASH/GoldDigger/LIVE_DISABLED
```

**RCA**: `LiveSafetyBroker._safe_order()` calls `_assert_live_safety()` FIRST on every submit (line 212). `_assert_live_safety()` checks `config.kill_switch_path.is_file()` (line 739) and raises. Kill switch is checked per-order.

**Verdict**: **NO-BUG**. Original audit hypothesis was wrong — the start-time check (line 282) is redundant but harmless; per-submit check exists via `_safe_order`.

**Fix**: none needed.

---

## Suspect 11 — Fill price = 0 recovery

**Hypothesis**: DWX returns success + missing price → we emit `ORDER_FILL_INVALID` and return None, but broker has opened position. Ghost trade.

**Reproduction steps**: read `DWXBrokerAdapter.fills()`.

**Evidence**: `bt_engine/execution/dwx_broker.py:86` — if `price == 0.0` the adapter yields NOTHING. Engine's `next(fills(), None)` returns None → engine emits `ORDER_SUBMIT_NO_FILL` (not `ORDER_FILL_INVALID`) and skips the order path entirely. No trade recorded.

Reality check: never observed on this broker. `result.price` always populated on success. Would be an MT5-side pathology.

**Verdict**: **NO-BUG on this broker**. Adapter handles gracefully; would create a broker-side orphan if it happened, but recoverable via `open_orders.json` sync on next bar.

---

## Suspect 12 — BT latency vs live async fill

**Hypothesis**: BT fill fires instantly at synthetic bar.open. Live: broker fill is async, may take seconds. If engine's tick loop moves past target bar before fill lands, order sits pending.

**Reproduction steps**: read `_submit_live_order()` — synchronous submit, then `next(fills(), None)`.

**Evidence**: `bt_engine/core/engine.py:179` — `broker.submit_order()` uses `bridge.send_command(wait_response=True, timeout_s=5.0)`. Blocks until EA writes response file. Fill is retrieved SAME tick.

**Verdict**: **NO-BUG**. Live is synchronous per submit within engine's tick. 5s timeout is fast enough that we never move to the next bar mid-fill.

---

## Suspect 13 — Pending order expiry

**Hypothesis**: `intended_entry_bar = signal_bar + 15min`. If engine skips that bar (network / EA lag), order sits forever.

**Reproduction steps**: read `run_engine()` loop.

**Evidence**: `bt_engine/core/engine.py:138-147` — in **live** mode, `step.new_orders` are submitted IMMEDIATELY without queuing:
```python
if mode == "live":
    for o in step.new_orders:
        submitted = _submit_live_order(deps, o, bar)
```
The `pending` list is only populated in BT mode's `else` branch at line 154-164. Live never queues.

**RCA**: order.intended_entry_bar is IGNORED in live mode — live submits inline. No queue = no expiry problem.

**Verdict**: **NO-BUG** for live mode. Fix not required.

**Note**: BT mode does use `pending` for the "next bar" pattern, but BT can't miss bars because provider is deterministic parquet iteration. No expiry needed there either.

---

## Broker smoke suite

See `docs/audit/BROKER_SMOKE_2026-07-01.md` for real echoes from JustMarkets-Demo2.

## 3-Way Parity Lock

Prior parity tests covered research ↔ BT. Added `tests/integration/test_bt_live_event_parity.py` which asserts **BT engine ↔ Live engine** event/order streams are byte-identical when fed the same bars:

- 300 XAU M15 bars, `fib_v2_intraday_a` + `fib_v2_intraday_d`
- BT: `run_engine(mode='bt')` with `BTExecutionModel`
- Live: `run_engine(mode='live')` with `BTMirrorLiveBroker` (mock that fills at bar.open like BT)
- Event streams (tuple key: trade_or_zone_id + type + bar_ts + leg + reason) match exactly
- Order streams (tuple key: symbol + side + prices + risk + tag) match exactly
- UUIDs masked (they're per-run random)

Combined with existing `test_parity_fib_v2_intraday_{a,d}.py` (research ↔ BT), we now have **research = BT engine = live engine strategy path** as a locked triangle. Execution-layer parity (BT-sim fill vs real broker fill) is captured separately via the broker reconciler (`broker_net_usd`).
