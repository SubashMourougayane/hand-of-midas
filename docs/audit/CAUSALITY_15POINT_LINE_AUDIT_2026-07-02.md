# 15-Point Causality Audit — Line-by-Line Proof

**Date:** 2026-07-02
**Scope:** Full Fib V2 + Fib V2 Intraday A+D signal→entry→exit path (BT + live share this code).
**Method:** Hostile — every audit point assumed guilty until proven innocent by the ACTUAL code line. Two independent reviewer agents traced the code; findings cross-checked against files.
**Mandate:** big-numbers-audit-mandate + strict-causality-mandate. 100% proof, cited to file:line.

Engine contract (verified): `on_bar` receives a JUST-CLOSED bar; `bar.timestamp` is the bar's open/left label; `history.iloc[-1].timestamp == bar.timestamp`; all history rows `<= bar.timestamp`. BT fills at the intended bar's OPEN (`simulator.py:36`).

Files audited:
- `bt_engine/strategies/fib_v2/strategy.py`
- `bt_engine/strategies/fib_v2/pivot_tracker.py`
- `bt_engine/strategies/fib_v2/regime_tracker.py`
- `bt_engine/strategies/fib_v2/swing_tracker.py`
- `bt_engine/strategies/fib_v2_intraday/strategy.py`
- `bt_engine/core/engine.py`
- `bt_engine/core/bracket.py`
- `bt_engine/execution/simulator.py`
- `bt_engine/runner/live.py` (warmup, tz)
- `bt_engine/data/dwx_live_provider.py` (tz)

---

## Verdict table — ALL 15 PASS

| # | Audit point | Verdict | Decisive cite |
|---|---|---|---|
| 1 | Pivot confirmation lag (idx+lb, no center look-ahead) | **PASS** | `pivot_tracker.py:59-64` |
| 2 | H1 aggregation causal (close ≤ bar.timestamp, no forming bar) | **PASS** | `strategy.py:346-350` (fast) / `362-367` (slow) |
| 3 | D1 regime lag (strict `<` prior-day, shift(1)) | **PASS** | `regime_tracker.py:131-136` |
| 4 | Swing tracker (current bar deferred to next call; also unused in entry rule) | **PASS** | `swing_tracker.py:48-53` |
| 5 | No phantom fill / next-bar entry at OPEN | **PASS** | `strategy.py:283-284,200-205,609` + `simulator.py:36` + `engine.py:191` |
| 6 | Confirmation candle uses PRIOR bar (prev_* set after match) | **PASS** | `strategy.py:563-564` read / `313-314` write-after |
| 7 | Zone/invalidation/session/regime on closed signal bar only | **PASS** | `strategy.py:520,525,533,535,543,551` |
| 8 | Bracket walk close-based, no forward peek (incl. P1a/P2a slip) | **PASS** | `bracket.py:94,141-148`; gap `engine.py:104-105` |
| 9 | Intraday strict-after (entry only bar > setup_confirm_ts) | **PASS** | `fib_v2_intraday/strategy.py:115-121` |
| 10 | Risk/cost computed at fill (next-open − sl); cost once | **PASS** | `strategy.py:609-613,629` |
| 11 | Setup dedup — (leg, confirm_ts) consumed-key idempotency | **PASS** | `strategy.py:258-264,286,304` |
| 12 | Intraday entry-bar dedup — (entry_ts, side, leg) | **PASS** | `fib_v2_intraday/strategy.py:165-173` |
| 13 | Min-risk floor rejects untradeable tiny stops | **PASS** | `fib_v2_intraday/strategy.py:150-157` |
| 14 | Setup expiry — max_hold_h from confirm_ts, bar.timestamp only | **PASS** | `strategy.py:705-706` |
| 15 | Live tz: broker UTC+3 → UTC at boundary, engine all-UTC | **PASS** | `dwx_live_provider.py:59-60`; `live.py:800-815` |

**No look-ahead found on any of the 15 points.**

---

## Detailed proofs

### 1 — Pivot confirmation lag · PASS
`pivot_tracker.py:59` early-returns until the `deque(maxlen=2*lb+1)` is full. The pivot candidate is the window CENTER `self._win[self.lb]` (`:63`) — `lb` bars behind the newest bar. `confirm_ts = ts` (`:64`) = newest (just-closed) bar's label. A pivot at bar `i` emits only once bar `i+lb` closes. No center evaluated at its own close. Strict max/min scans buffered CLOSED bars only (`:69-70, 76-77`).

### 2 — H1 aggregation causal · PASS
Fast path: H1 bar `k` closes at `ts_arr[k] + 1h` (`:348`); ingested only if `close_ns <= target_ns` where `target_ns = bar.timestamp` (`:345,349`). `<=` is the correct inclusive boundary — an H1 bar closing exactly at the current M5 left-label holds strictly-earlier data. A forming H1 (label = current hour, closes +1h) is excluded. Slow path: `closed_h1_left = floor_1h − 1h` (`:363`), slice `[closed_h1_left, +1h)` all `< floor_1h <= bar.timestamp` (`:367`); forming bucket excluded; `last_h1_seen` dedup (`:364`).

### 3 — D1 regime lag · PASS
`regime_for(m5_ts)`: `day_floor = floor(m5_ts,'1D')` (`:125`); selects most recent D1 with `prev_ts < day_floor` — **strict `<`** (`:132`). Today's forming D1 never returned. `gate_passes` reads only this lagged dict (`:161`); fails-closed when no prior day (`:135,162`). Ingest side only accepts D1 with `close +1d <= bar.timestamp` (`strategy.py:390-393`).

### 4 — Swing tracker · PASS
`update(bar)` pushes the PREVIOUS stashed bar into the deque (`:48-50`), then stashes current bar's high/low WITHOUT appending (`:52-53`). Current bar first enters window next call = `shift(1).rolling` exactly. Also: swing values never read in `_signal_bar_matches`/`_build_setup` — nil leak surface.

### 5 — No phantom fill · PASS
Signal on bar k → `pending_entries.append` only, NO order created (`strategy.py:283-284`). Next `on_bar` (k+1) finalizes FIRST (`:200-205`), `entry_price = bar.open` of k+1 (`:609`), `intended_entry_bar = bar.timestamp` (k+1) (`:634`). Engine fills at `next_bar.open` (`simulator.py:36`) with assertion `next_bar.timestamp == intended_entry_bar` (`simulator.py:30`). Strategy risk-open and engine fill-open agree (same bar). Same-bar fill structurally impossible.

### 6 — Confirmation candle prior bar · PASS
Engulfing reads `state.prev_open/prev_close` only (`:563-564,567-572,585-590`). `prev_*` written at END of `on_bar` (`:313-314`) AFTER the match loop — during bar k's match they hold bar k-1. First-bar None guard (`:558`).

### 7 — Signal checks closed bar only · PASS
Invalidation `bar.close` (`:520,525`); zone `bar.close` (`:533,535`); session `_ny_hour(bar.timestamp)` pure-time (`:543`); regime `bar.timestamp` → strict-prior-day (`:551`). Uses `close` not intrabar high/low — more conservative, cannot leak.

### 8 — Bracket close-based · PASS
`close = bar.close` (`bracket.py:94`); `hit_stop`/`hit_tp` on `close` (`:141-148`). Engine walks one just-closed bar per tick (`engine.py:139-158`). `bar.high/low` used only for current-bar MFE/MAE (`bracket.py:107-111`). P1a/P2a slip: SL slip = deterministic `stop − side*slip` (`:163`); gap uses `bar_gap_seconds` from consecutive timestamps (`engine.py:104-105`) — no forward peek.

### 9 — Intraday strict-after · PASS
`fib_v2_intraday/strategy.py:115`: `if bar.timestamp == setup.setup_confirm_ts: return False`. Entry eligible only bar strictly after confirm — matches research `searchsorted(side='right')`.

### 10 — Risk/cost at fill · PASS
`entry_price = bar.open` (k+1) (`:609`); `risk = entry − sl` / `sl − entry` (`:611,613`); `sl_price` fixed at setup-build from confirmed pivots; `cost_r = cost_usd / risk` computed ONCE (`:629`), engine reads from `extra` (`:657`) — no double-count.

### 11 — Setup dedup · PASS
`(leg_name, setup_confirm_ts)` consumed-key set. Skip build if key in set (`:259-260`); dupe-ts guard (`:263-264`); marked consumed on match (`:286`) and on expiry/invalidation (`:304`). Idempotent — a setup fires at most one entry.

### 12 — Intraday entry-bar dedup · PASS
`key = (bar.timestamp, side, leg_name)` (`fib_v2_intraday/strategy.py:165`); reject if in `consumed_entry_keys` (`:166-172`); else add (`:173`). Blocks multi-pivot stacking on the same M15 bar. Opposite-dir A+D allowed (different side). State pinned via single-threaded shim (`:188-192`).

### 13 — Min-risk floor · PASS
`if order.risk_units < min_risk_units: return None` (`fib_v2_intraday/strategy.py:150-157`). Rejects broker-untradeable tiny stops (min 0.50 on XAU). Runs after base risk-pct check, before order propagates.

### 14 — Setup expiry · PASS
`_setup_invalidation_reason`: `expiry = setup_confirm_ts + max_hold_h hours` (`:705`); `if bar.timestamp > expiry` → expired (`:706`). Uses only setup's own confirm_ts + current bar timestamp. No future info.

### 15 — Live timezone · PASS
Broker bars/quotes are UTC+3 (JustMarkets, no DST). `Mt5LiveBarProvider._read_normalized` subtracts `server_utc_offset` (`dwx_live_provider.py:59-60`) → UTC bars to the engine. `_infer_server_utc_offset_hours` (`live.py:800-815`) reads offset once at start (JM UTC+3 fixed → safe; would need re-check on a DST broker). Reconciler `_to_utc_dt` subtracts offset + stamps UTC (`broker_reconciler.py:119-126`). Engine/dedup/session all operate in UTC. Fidelity gap (not a leak): live fill timestamp uses machine wall-clock UTC not broker echo — off by <1s, doesn't affect bars/dedup/brackets.

---

## Cross-reference

Consistent with:
- `docs/audit/L99_HOSTILE_AUDIT_2026-07-01.md` — 4 execution bugs found+fixed, 9 no-bug.
- `docs/audit/L99_BT_VS_LIVE_PARITY_2026-07-02.md` — 22 BT-vs-live divergences (execution realism, not causality).
- memory `strict-causality-mandate`, `intraday-ad-final-audit-record` (3 fresh reviewers, zero bugs).

This audit extends the record with a fresh **line-cited** pass over the full strategy code path, both base ensemble and intraday A+D + combined.

## Non-leak documentation notes (worth cleanup, no correctness impact)
1. `fib_v2/strategy.py:18-39` docstring has STALE prose ("bar.close as proxy for entry_price", "Phase 1 approximation"). Actual code (`:609`) uses next-bar OPEN correctly. Docstring misleading; logic clean.
2. Live open-trade fib_L/H not persisted to DB (dashboard trade-story gap) — instrumentation, not trading.
3. `_infer_server_utc_offset_hours` reads once at start — safe for JM (no DST); re-audit if broker observes DST.

---

*Generated 2026-07-02. Two independent hostile reviewer agents + manual cross-check. All 15 points PASS with file:line citations. No look-ahead, fully time-aware candle-close execution, no causality bug — bible rules upheld across the entire live+BT strategy path.*
