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
| 2 | SL absolute vs fill-relative (design decision) | ⏳ |
| 3 | Cost model constant vs per-lot | ⏳ |
| 4 | Partial-TP command sequence race (retry / safe close) | ⏳ |
| 5 | Reconciler assumes single deal per ticket | ⏳ |
| 6 | max_open_positions bypass for concurrent A + D | ⏳ |
| 7 | Dedup key stability BT vs live (tz) | ⏳ |
| 8 | Warmup contaminates consumed_setup_keys | ⏳ |
| 9 | Server time offset assumed constant | ⏳ |
| 10 | Kill switch checked at start only | ⏳ |
| 11 | Fill price = 0 recovery | ⏳ |
| 12 | BT latency vs live async fill | ⏳ |
| 13 | Pending order expiry | ⏳ |

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

Design question tied to #1. Deferred.

---

## Suspect 3 — Cost model constant vs per-lot

**Hypothesis**: BT uses `cost_usd = $0.65/trade` regardless of qty. Real JustMarkets commission is per-lot ($6.50/lot round-turn) + spread ($per-oz × 100oz × qty). At 0.43 lot ≈ $9.47 friction, not $0.65 (14.6× underestimate).

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

**Broker verify**: TODO

---

## Suspect 4 — Partial-TP command sequence race

**Hypothesis**: `close_partial` succeeds then `modify(sl=BE)` fails → half-position with original SL. No retry.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

**Broker verify**: TODO

---

## Suspect 5 — Reconciler assumes single deal per ticket

**Hypothesis**: MT5 partial-close creates 2 exit deals for the same position_id. `find_closed_deal` returns FIRST match; broker_gross_usd captures only partial not full trade.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

**Broker verify**: TODO

---

## Suspect 6 — max_open_positions bypass for A + D

**Hypothesis**: Each leg proc has its own `LiveSafetyBroker` with `max_open_positions=1`, but check is against BROKER TOTAL open positions across all magics. A fires → 1 open. D checks → 1 open ≥ 1 → rejects. Blocks legitimate hedge.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

**Broker verify**: TODO

---

## Suspect 7 — Dedup key stability BT vs live

**Hypothesis**: `consumed_setup_keys.add((leg, bar.timestamp))`. BT bar_ts from parquet vs live bar_ts from DWX (server UTC+3 → UTC in provider). If shift is 1s off, dedup fails.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

---

## Suspect 8 — Warmup contaminates consumed_setup_keys

**Hypothesis**: 200-bar warmup replays through `on_bar`. Setups spawned during warmup add their keys to `state.consumed_setup_keys`. Live bars post-warmup with same keys get skipped.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

---

## Suspect 9 — Server time offset assumed constant

**Hypothesis**: `_infer_server_utc_offset_hours()` runs once at start. Won't detect DST or server-time changes mid-session.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

---

## Suspect 10 — Kill switch checked at start only

**Hypothesis**: `_assert_live_safety()` reads `LIVE_DISABLED` once. Touching mid-session doesn't halt subsequent entries.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

**Broker verify**: TODO

---

## Suspect 11 — Fill price = 0 recovery

**Hypothesis**: DWX returns success + missing price → we emit `ORDER_FILL_INVALID` and return None, but broker has opened position. Ghost trade.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

**Broker verify**: TODO

---

## Suspect 12 — BT latency vs live async fill

**Hypothesis**: BT fill fires instantly at synthetic bar.open. Live: broker fill is async, may take seconds. If engine's tick loop moves past target bar before fill lands, order sits pending.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

---

## Suspect 13 — Pending order expiry

**Hypothesis**: `intended_entry_bar = signal_bar + 15min`. If engine skips that bar (network / EA lag), order sits forever.

**Reproduction steps**: TODO

**Evidence**: TODO

**RCA**: TODO

**Verdict**: TODO

**Fix commit**: TODO

---

## Broker smoke suite

See `docs/audit/BROKER_SMOKE_2026-07-01.md` for real echoes from JustMarkets-Demo2.
