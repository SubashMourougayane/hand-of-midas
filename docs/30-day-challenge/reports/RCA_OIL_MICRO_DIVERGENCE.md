# RCA — Live vs Backtest Signal Divergence (Oil Micro deep-dive)

**Date:** 2026-06-18
**System:** Oil Micro — `micro_alpha_sweep_oil` on BCO_USD M3 (rolling 4hr consolidation, scan 6hr after).
**Trigger:** Companion deep-dive to Oil Macro (`RCA_LIVE_VS_BT_SIGNAL_DIVERGENCE.md`) and Gold Macro (`RCA_GOLD_MACRO_DIVERGENCE.md`). Per the live↔backtest parity-gap memo, every system has a parallel reimplementation; verify whether Oil Micro inherits Oil Macro's TP-formula divergence or stays clean like Gold Macro.

**Method:** Code-level diff between BT signal-gen (`backend-oil-micro/backtest/engine.py:generate_signals`) and the live core (`backend-oil-micro/scanner/scheduler.py:_run_micro_sweep_core`). No replay numbers.

---

## TL;DR

Oil Micro **DOES** ship two parallel implementations of the rolling-window Alpha-Sweep (BT in `engine.py:generate_signals`, live in `scheduler.py:_run_micro_sweep_core`). However:

- **TP formula is IDENTICAL between BT and live.** Both branches compute `tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])` and anchor TP on `range_high - tp_buf` (LONG) / `range_low + tp_buf` (SHORT). **Oil Micro does NOT inherit Oil Macro's D1 TP-formula divergence — it matches Gold Macro's clean pattern.**
- Detection math (sweep level, engulfing, bias, risk gates, Filter #27 limit-price) is line-for-line equivalent.
- Live still wraps signal-gen in **8 production-only gates** that BT lacks — more than Gold Macro because Oil Micro adds rolling-window tick cadence, persistent blacklist, MT5 cross-check, and a startup cooldown.

The smoking gun for Oil Micro divergence is **gating + iteration-order semantics** of the rolling-window architecture, not strategy math.

---

## Architecture: two parallel signal generators

| Layer | Function | File | Lines |
|---|---|---|---|
| **BT signal-gen** | `generate_signals(oil_h1, oil_m3, daily_bias)` | `backend-oil-micro/backtest/engine.py` | 72–226 |
| **BT execution** | iterates `all_signals` from above | `backend-oil-micro/backtest/engine.py` | 550–690 |
| **Live signal-gen + exec (single fn)** | `_run_micro_sweep_core(now, active_windows, h1, daily, m3, dry_run)` | `backend-oil-micro/scanner/scheduler.py` | 156–525 |

`scheduler.py:14` imports `MICRO_ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE` from `config` but does **NOT** import `engine.generate_signals`. Live is a hand-coded reimplementation.

Note: Oil Micro does NOT have a separate `strategies/` file (unlike Gold Macro / Oil Macro). The BT signal generator is inlined in `engine.py` at the top — a Gold-Micro-style structural choice.

---

## Differences (line-level)

### D1 — TP formula: **NO DIVERGENCE** (matches Gold Macro pattern, not Oil Macro)

| | BT (`engine.py`) | Live (`scheduler.py`) |
|---|---|---|
| **LONG TP** | `tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])`<br>`tpv = range_high - tp_buf` (lines 185–186) | `tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])`<br>`tp = range_high - tp_buf` (lines 428–429) |
| **SHORT TP** | `tpv = range_low + tp_buf` (lines 205–206) | `tp = range_low + tp_buf` (lines 446–447) |

Config (`config.py:38-39`): `tp_multiplier=2.0`, `tp_structure_buffer=0.13`. Both engines resolve to `tp_buf = 0.13` (fallback never used).

**Verdict:** Ruled out. Oil Micro's BT does **not** use Oil Macro's `entry + asia_range × tp_multiplier` asymmetry. Same input → same TP value → same `tp_too_close` filter outcome.

### D2 — Rolling-window iteration: BT walks per-bar timeline, live walks active-windows per scheduler tick

BT (`engine.py:91-99`):
```python
for bar_ts, bar in day_h1.iterrows():
    now_hour = bar_ts.hour
    ...
    for start_hour in range(0, 24, cfg["scan_gap_hours"]):
```
BT iterates **every H1 bar of the day**, recomputing which windows are active at that bar's hour, then walks `scan_bars` filtered to `day_h1.index <= bar_ts` (line 125). The active-window check uses `_hour_past(now_hour, end_hour)` and `_hour_past(now_hour, scan_end_hour)`.

Live (`scheduler.py:99, 268`):
```python
active_windows = _get_active_windows(now)
...
for window in active_windows:
```
Live runs **once every 3 minutes** (cron `*/3`, line 585), evaluates `now.hour` against the same `_hour_past` predicate, and processes only windows currently in their scan phase. Inside a window, `scan_bars` is filtered by `ts.hour in scan_hours` (lines 299-307) — no `<= bar_ts` upper bound, so live can re-evaluate completed bars.

**Effect:** BT can detect a sweep on bar T at simulation-time T (deterministic). Live can only detect it on the next 3-min cron tick after T closes. If the cron skips a tick (Python crash, MT5 reconnect during DWX FILE_SHARE bug), the sweep is missed forever once the window's `scan_until` passes — even though BT would still capture it. Compounded by D6.

**Verdict:** Real architectural divergence. Higher impact for Oil Micro than for Macro because the scan window is shorter and runs more frequently.

### D3 — Live: 5-min cooldown after last `gd_signals` row

`scheduler.py:245-260`:
```python
recent_signal = execute("SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='micro_alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 1", fetch=True)
...
if recent_signal[0]["taken"] or _skip.startswith("order_error") or _skip.startswith("oanda_error") or _skip == "sl_too_close_to_price":
    if now < last_signal_time + timedelta(minutes=5):
        return [] if dry_run else None
```

BT (`engine.py:573-574`): `if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS: continue` — `last_signal_time` updates only on **filled** signals (line 663), and only at portfolio-loop level.

**Effect:** Live cooldown advances on `taken=True` plus three known-failure skip reasons. BT cooldown advances only on filled. Drift surface identical to Oil Macro D2 / Gold Macro D2.

**Verdict:** Real divergence — same shape as peer systems.

### D4 — Live: open-position DB blocker + MT5 cross-check (D4a + D4b)

`scheduler.py:349-362`:
```python
open_micro = execute(
    f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time IS NULL",
    fetch=True)
if open_micro and open_micro[0]["cnt"] > 0: continue
mt5_open = get_open_trades()
if mt5_open and len(mt5_open) > 0: continue
```

Layered defense: DB query first, then live MT5/OANDA broker check. BT (`engine.py:576-577`) only has `if position_exit_time and signal.date < position_exit_time: continue`, where `position_exit_time = signal.date + timedelta(seconds=result["bars_held"] * 180)` (line 665).

**Important:** the MT5 check (`get_open_trades()`) is **account-wide**, not strategy-filtered. Oil Macro and Oil Micro both trade BCO_USD on the **same** JustMarkets demo account. If Oil Macro has any BCO_USD position open, **Oil Micro is locked out** of every signal until that closes. BT has no equivalent cross-system interlock.

**Verdict:** Real divergence with cross-system blast radius. Likely a much larger source of dropped Oil Micro signals than the equivalent gate on Macro systems.

### D5 — Live: persistent sweep blacklist (`_traded_sweeps["keys"]` + DB)

`scheduler.py:337-346, 462-476`:
- After successful fire, AND after the 0.75-hour engulfing window expires without an engulfing → sweep added to in-memory `_traded_sweeps["keys"]` AND persisted via `mark_sweep_consumed("oil-micro", today, sweep_key)`. Restart-safe (Issue #9 fix 2026-06-15).
- Crucially, the sweep is **pre-marked before order placement** (line 473) to break the orphan-trade cascade pattern from June 10.

BT analogue (`engine.py:89, 153, 217, 222`): `traded_sweeps = set()` per-day, never persisted, scoped by `(sbar_ts, start_hour)` tuple — different cardinality than live's `f"{bar['timestamp']}_{sweep_dir}"` string.

**Effect:** Live blacklist is wider (per-direction string, not per-(timestamp, window) tuple) **and** persistent across restart. BT clears state at day boundary. After a restart that hits an in-flight sweep, live skips it; BT re-fires.

**Verdict:** Real divergence. Same shape as Gold Macro D4 but Oil Micro keys differ.

### D6 — Live: scheduler tick cadence (3-min cron)

`scheduler.py:585`: `scheduler.add_job(micro_sweep_job, "cron", minute="*/3", id="oil_micro_sweep_poll")`. Sweep detection executes every 3 min wall-clock. BT executes once per H1 bar (effectively continuous — every H1 bar inside the scan window is checked).

**Effect:** Live can lag a sweep by up to 3 min. Combined with engulfing-window-expiry logic (D7), a sweep that fires at minute 44 of the 45-min window has only one tick to find an engulfing — BT walks every M3 bar inside the window deterministically.

### D7 — Live: 45-min engulfing-window expiry (`engulfing_window_hours: 0.75`)

`scheduler.py:376-394`:
```python
sweep_time = _parse_ts(bar["timestamp"])
window_end = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])
relevant_m3 = [...]
if len(relevant_m3) < 3:
    if now >= window_end: _traded_sweeps["keys"].add(sweep_key); mark_sweep_consumed(...)
    continue
```

BT (`engine.py:150-154`):
```python
eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
m3_window = oil_m3[(oil_m3.index > sbar_ts) & (oil_m3.index <= eng_end)]
if len(m3_window) < 3: traded_sweeps.add(sk); continue
```

Both use the same 45-min window. BUT live's `now >= window_end` check is wall-clock; BT's check is data-driven. If MT5 returns an M3 history with gaps (weekend/maintenance), live sees `len(relevant_m3) < 3` and blacklists the sweep at `now >= window_end`; BT just doesn't have those bars in its CSV and never enters the loop. Asymmetric edge case.

### D8 — Live: startup cooldown

`scheduler.py:262-266, 528-553`. On process start, if a `gd_signals` row exists from within the last 45 min with `taken=True`, `_startup_cooldown_until` is set to `last_ts + engulfing_window_hours`. While active, every tick returns early. BT has no concept of "process start."

### D9 — Live: hardcoded engulfing start_idx

`scheduler.py:396`: `for j in range(2, len(relevant_m3)):` — hardcoded `2` (always-skip-first-bar).
BT `engine.py:156`: `start_idx = 2 if cfg["skip_first_bar"] else 1`.

With current config (`skip_first_bar=True`) both resolve to 2, so behaviorally equivalent today. **Config-drift risk**: if `skip_first_bar` is ever flipped to `False` in `MICRO_ALPHA_SWEEP`, BT changes but live silently does not. Latent bug.

### D10 — Live: F28 bias-mode env override

`scheduler.py:210-216` reads `BIAS_MODE` from `config` (sourced from `OIL_MICRO_BIAS_MODE` env). BT (`engine.py:483-487`) takes `bias_mode` as an explicit kwarg via `resolve_bias_mode()`. Same end-state but two different config surfaces — env-var typo on VPS would silently keep V1+V2 bias on while the parity harness runs with `bias_mode='neutral'`.

### D11 — Live: Filter #27 limit-order live state machine

`live_engine.py:282-456` plus `pending_order_monitor` (lines 1187-1444): full live limit-order lifecycle including DWX `pending_orders.json` / `open_orders.json` / `cancelled_orders.json` polling, TTL grace fallback (60s), bad-`open_price` escalation, broker-orphan reconciliation, dry-run gate (`OIL_MICRO_LIMIT_DRY_RUN`).

BT (`engine.py:284-319`) collapses all of this into `_execute_trade`'s pre-walk: walk `bar_start+1..ttl_end`, fill on first `bid_low <= limit_price` (LONG) / `ask_high >= limit_price` (SHORT) bar. No grace, no DWX file races, no MT5 reconnect, no orphan paths.

**Effect:** BT cannot model fill-misses caused by 30s file-poll race or DWX file-write delay. Live can register `LIMIT_TTL_EXPIRED` for sweeps BT counts as filled. Asymmetric only on the "filled" classification, not on the signal itself — BT compensates via `would_have_won_count` lookahead but that's informational, not used in P&L.

---

## CRITICAL — TP formula vs Oil Macro / Gold Micro patterns

| System | BT TP formula | Live TP formula | Verdict |
|---|---|---|---|
| **Oil Macro** | `entry + asia_range × tp_multiplier` (entry-based) | `asia_high - tp_buf` (structure-based) | **DIVERGENT (D1 smoking gun)** |
| **Gold Macro** | `asia_high - tp_buf` | `asia_high - tp_buf` | **MATCH** |
| **Oil Micro** (this RCA) | `range_high - tp_buf` (structure-based) | `range_high - tp_buf` | **MATCH** |

Oil Micro's BT was inlined in `engine.py` rather than copied from `backend/strategies/alpha_sweep.py`, which means it never inherited the Oil Macro entry-based asymmetry. Its `_compute_limit_price` import (`engine.py:12`) and live counterpart (`live_engine.py:23`) both use the **same shared helper** (`backend.execution.limit_price.compute_limit_price`), so Filter #27 limit math is also identical.

**Oil Micro is in the "clean TP" cohort with Gold Macro.**

---

## Smoking-gun ranking (signal-gen drift, descending)

1. **D4 (open-position MT5 cross-check)** — Highest blast radius. Account-wide MT5 query means any Oil Macro BCO_USD trade silently kills Oil Micro entries. Cross-system interlock not present in BT. Same pattern that smoking-gunned Gold Macro D3.
2. **D2 (rolling-window iteration order)** — Architectural mismatch unique to Micro systems. 3-min cron vs per-bar walk creates window-edge misses, especially when combined with D6 + D7 + the 45-min engulfing-window expiry (sweeps detected late in the window get one cron tick).
3. **D5 (persistent sweep blacklist)** — Blacklist is wider in live (per-direction string) than BT (per-(timestamp, window) tuple) AND persists across restart. Drives one-way drift after any process restart inside an active scan window.
4. **D3 (5-min cooldown semantics)** — Same shape as peer systems. Live cooldown advances on `sl_too_close_to_price` skips that BT ignores entirely.
5. **D7 + D6 (45-min engulfing window vs 3-min cron)** — Asymmetric for sweeps detected late in their window. BT walks every M3 bar inside the window; live gets up to 15 ticks in the best case, 1 tick in the worst.
6. **D11 (Filter #27 fill-miss asymmetry)** — Real but bounded; affects the filled/unfilled classification, not the signal itself.
7. **D8 (startup cooldown)** — Bounded to process-start events.
8. **D10 (F28 env-var split)** — Latent env-var typo risk only.
9. **D9 (hardcoded `range(2,...)`)** — Behaviorally inert today; latent if `skip_first_bar` ever flipped.

**Conclusion:** Oil Micro divergence is **gate-driven**, not formula-driven. The most likely sources of "BT signal not seen live" are D4 (cross-system MT5 lock from Oil Macro) and D2/D6/D7 (rolling-window cadence vs deterministic per-bar walk). The TP-formula bug pattern from Oil Macro does **not** exist here.
