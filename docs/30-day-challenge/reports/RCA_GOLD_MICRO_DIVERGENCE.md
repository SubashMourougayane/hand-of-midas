# RCA — Live vs Backtest Signal Divergence (Gold Micro deep-dive)

**Date:** 2026-06-18
**System:** Gold Micro (XAU_USD, `micro_alpha_sweep` rolling 4hr consolidation + 6hr scan windows every 2hr).
**Trigger:** Companion deep-dive to Oil Macro and Gold Macro RCAs. Per the live↔backtest parity-gap memo, every system has a parallel reimplementation; verify whether Gold Micro inherits Oil Macro's TP-formula divergence, Gold Macro's cross-strategy lock, or has a system-specific smoking gun (rolling-window iteration).

**Method:** Code-level diff between BT signal-gen (`backend/strategies/micro_alpha_sweep.py`) and the live core (`backend-micro/scanner/scheduler.py:_run_micro_sweep_core`). No replay numbers. Quotes are line-anchored.

---

## TL;DR

Gold Micro **DOES** ship two parallel implementations (BT in `micro_alpha_sweep.py:generate_signals` lines 42–223; live in `scheduler.py:_run_micro_sweep_core` lines 184–571). However:

- **TP formula MATCHES** between BT and live — same pattern as **Gold Macro**, NOT Oil Macro. Both use `range_high − tp_buf` (LONG) / `range_low + tp_buf` (SHORT). Gold Micro does **NOT** inherit Oil Macro's D1.
- The detection math (sweep, engulfing, bias V1+V2, risk gates, range-min, slippage) is line-for-line equivalent.
- Live wraps signal-gen in **7 production-only gates** that BT only partially mirrors: 5-min cooldown, open-position DB-AND-MT5 blocker, persistent sweep blacklist, startup cooldown, daily-max-loss, "one-at-a-time", and Filter-#27 limit-order path with through-market refusal. Drift surfaces equal Gold Macro's count plus Filter-#27.
- **Gold Micro–specific smoking gun:** the **window-iteration model is fundamentally different**. BT walks every H1 bar chronologically and checks all windows for that bar; live iterates only the windows currently in their scan phase at scheduler tick time (every 3 min wall-clock). Combined with `_traded_sweeps` keying differences (BT keys by `(sbar_ts, start_hour)`, live keys by `(bar_timestamp, sweep_dir)` and is **global across all windows**), live can mark a sweep "consumed" for window A and refuse the same H1 bar in window B — BT would still attempt it. See D6 + smoking-gun #1.

---

## Architecture: two parallel signal generators

| Layer | Function | File | Lines |
|---|---|---|---|
| **BT signal-gen** | `generate_signals(gold_h1, gold_m3, daily_bias, disable_market_close)` | `backend/strategies/micro_alpha_sweep.py` | 42–223 |
| **BT execution** | iterates `all_signals`, applies cooldown / one-at-a-time / DD / Filter-#27 | `backend-micro/backtest/engine.py` | 187–345 |
| **Live signal-gen + exec (single fn)** | `_run_micro_sweep_core(now, active_windows, h1, daily, m3, dry_run)` | `backend-micro/scanner/scheduler.py` | 184–571 |
| **Live tick driver** | `micro_sweep_job` (cron `*/3` minutes) → `_get_active_windows(now)` | `backend-micro/scanner/scheduler.py` | 102–140, 38–84 |

Confirmed via grep: `scheduler.py` imports `MICRO_ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE` from `config` and `backend.config` but does **NOT** import `micro_alpha_sweep.generate_signals`. The live core is a hand-coded reimplementation.

---

## Differences (line-level)

### D1 — TP formula: **NO DIVERGENCE** (matches Gold Macro pattern, NOT Oil Macro)

| | BT (`micro_alpha_sweep.py`) | Live (`scheduler.py`) |
|---|---|---|
| **LONG TP** | `tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])`<br>`tpv = range_high - tp_buf` (lines 182–183) | `tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])`<br>`tp = range_high - tp_buf` (lines 472–473) |
| **SHORT TP** | `tpv = range_low + tp_buf` (line 203) | `tp = range_low + tp_buf` (line 491) |

`tp_structure_buffer = 2.0` is set in **both** `backend/config.py:42` (ALPHA_SWEEP, used by BT signal-gen) and `backend-micro/config.py:38` (MICRO_ALPHA_SWEEP, used by live). The fallback (`consol_range × tp_multiplier`) is never reached. Same anchor on consolidation high/low, no entry-based formula.

**Verdict:** Ruled out. Gold Micro does NOT inherit Oil Macro's D1.

### D2 — Config-key drift: BT reads `ALPHA_SWEEP`, live reads `MICRO_ALPHA_SWEEP`

BT signal-gen: `from backend.config import ALPHA_SWEEP` (line 16) → uses `cfg["asia_min_range"]` (line 110), `cfg["sweep_threshold"]`, `cfg["sl_buffer"]`, `cfg["min_sl"]`, etc.

Live: `from config import MICRO_ALPHA_SWEEP` (line 14) → uses `cfg["min_range"]` (line 334) — **different key name** (`asia_min_range` vs `min_range`), same value (5.0). All other gates pull from `MICRO_ALPHA_SWEEP`.

Both `min_range = 5.0` and `asia_min_range = 5.0` today. **Drift surface:** changing one config without the other silently desyncs the systems with no error. This already bit Gold Micro: `backend-micro/config.py:53` sets `disable_market_close=True` (Filter shipped 2026-06-15), and BT only respects it because the BT execution loop reads `MICRO_ALPHA_SWEEP.get("disable_market_close")` at `engine.py:64–65` and explicitly threads it into `micro_alpha_sweep.generate_signals(...)` as a kwarg, while signal-gen falls back to its own `cfg.get("disable_market_close", False)` from `ALPHA_SWEEP`. Two separate dicts, one shared semantic.

**Verdict:** Latent drift, neutralized today by accident-of-equality. Same shape as Oil Macro D6.

### D3 — Window iteration model: continuous vs scheduler-tick (CRITICAL)

BT (`micro_alpha_sweep.py` lines 73–101):
```python
for bar_ts, bar in day_h1.iterrows():
    now_hour = bar_ts.hour
    ...
    for start_hour in range(0, 24, mcfg["scan_gap_hours"]):
        ...
        if not _hour_past(now_hour, end_hour):
            continue
        if _hour_past(now_hour, scan_end_hour):
            continue
```
BT walks **every completed H1 bar** of every day, and for each bar evaluates **all 12 windows**. Each scan-bar inside the window is checked exhaustively: `for sbar_ts, sb in scan_bars.iterrows():` (line 120) — every scan bar up to and including the current iteration bar.

Live (`scheduler.py:_get_active_windows` lines 38–84):
```python
def _get_active_windows(now: datetime) -> list:
    ...
    for start_hour in range(0, 24, cfg["scan_gap_hours"]):
        ...
        if not _hour_past(current_hour, end_hour): continue
        if _hour_past(current_hour, scan_end_hour): continue
        windows.append({...})
```
Live computes `now = datetime.now(timezone.utc)` (line 104) and only queries the windows whose scan phase contains the current wall-clock hour. The cron fires every 3 minutes (`scheduler.add_job(micro_sweep_job, "cron", minute="*/3"...)` line 652), and for each tick fetches the most recent 24 H1 candles + 50 M3 candles via `get_candles(...)` (lines 168–179).

**Effect:** If the live process is down for >3 min during a scan window, the H1 sweep bar is still in the candle-history fetch, but the live engine relies on a sweep being scanned within the same scheduler tick that the engulfing forms in M3. The startup cooldown (`_restore_traded_sweeps_on_startup` lines 574–620) blocks for `engulfing_window_hours = 0.75` after the most recent taken signal precisely because the live engine cannot deterministically replay missed ticks. BT, by contrast, always walks chronologically end-to-end.

**Verdict:** This is the structural divergence. It manifests as: live can miss sweeps that BT catches when (a) the scheduler tick lands after the engulfing window has expired, or (b) the service restarts mid-window. Tracked in production by the startup-cooldown logic, never fully closed.

### D4 — Sweep dedup keying: per-window-per-bar vs per-bar-per-direction (CRITICAL)

BT (`micro_alpha_sweep.py` line 134): `sk = (sbar_ts, start_hour)` — keyed by **(scan-bar timestamp, window start hour)**. Same H1 bar can fire in window A AND window B independently (different start_hour).

Live (`scheduler.py` line 382): `sweep_key = f"{bar['timestamp']}_{sweep_dir}"` — keyed by **(scan-bar timestamp, sweep direction)**. Same H1 bar can fire in window A but is **blocked** in window B even if window B is also active and the sweep direction matches.

`_traded_sweeps["keys"]` is a per-day global set (line 26) that persists across all 3-min ticks until midnight reset (lines 113–114), and is also DB-backed via `is_sweep_consumed` / `mark_sweep_consumed` for restart safety (lines 384–386, 518–520).

BT's `traded_sweeps` is per-day-loop-iter (line 71) and lives only inside `generate_signals`.

**Verdict:** Real semantic divergence. A bar that sweeps both range-high in window 0–4 and range-high in window 2–6 is entered twice in BT (with different consol ranges), once in live. **No counter-evidence in production yet** — no audited case observed — but the pattern is dormant and will surface on overlapping-window, same-direction sweeps.

### D5 — Cooldown semantics: BT advances on fill only, live advances on order-error / sl-too-close

`scheduler.py:283–299`:
```python
if recent_signal[0]["taken"] or _skip.startswith("order_error") or _skip.startswith("oanda_error") or _skip == "sl_too_close_to_price":
    if now < last_signal_time + _td(minutes=5):
        return None
```
BT (`engine.py:212`): `if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS: continue`, where `last_signal_time = signal.date` is set only after `execute_trade` returns `result.filled == True` (line 310, after line 305's `if not result.filled: continue`).

**Verdict:** Same shape as Gold Macro D2 / Oil Macro D2. Live blocks sweeps after benign order errors that BT does not.

### D6 — Open-position blocker: live checks DB AND MT5; BT uses position_exit_time

Live (`scheduler.py:393–406`):
```python
open_micro = execute("SELECT COUNT(*) ... AND exit_time IS NULL", fetch=True)
if open_micro and open_micro[0]["cnt"] > 0:
    continue
mt5_open = get_open_trades()
if mt5_open and len(mt5_open) > 0:
    continue
```
Plus a defense-in-depth duplicate inside `execute_signal` (live_engine.py:250–257).

BT (`engine.py:215–217`): `if position_exit_time and signal.date < position_exit_time: continue`. `position_exit_time = signal.date + timedelta(seconds=result.bars_held * bar_seconds)` (line 319).

**Effect:** Live blocks if **any** Micro trade is open, including stuck/orphan positions. BT only blocks the inner-window range. Cross-strategy lock from Gold Macro doesn't apply here because Micro is on its own service+TRADE_REF_PREFIX, but intra-Micro orphans block the strategy until reconciled — surfaced by `reconcile_orphans` (line 158).

**Verdict:** Real divergence — same shape as Gold Macro D3 but contained to `GD-MI-%`.

### D7 — Filter-#27 (limit-order entry) live path

Live `execute_signal` (live_engine.py:261–477) implements the full limit-order primitive: `compute_limit_price` → through-market refusal (LONG limit > ask, SHORT limit < bid) → wrong-side SL refusal (C2) → `place_limit_order` with TTL (15 min) → DB row with `mode='pending'`. `dry_run` is gated by `parse_dry_run_env(system_prefix="MICRO")`; production has `MICRO_LIMIT_DRY_RUN` controlling rollout.

BT (`engine.py:258–295`) computes the **same** `compute_limit_price` (shared helper) and threads `entry_mode="limit"` into `execute_trade` with `limit_ttl_bars=5`. **Parity by design** for the price math, but BT does **not** simulate through-market refusal or wrong-side-SL refusal — those are live-only safety gates.

**Verdict:** Latent divergence — when production limit price is refused by H6/C2, BT doesn't model the skip. Currently rare (both gates verified zero hits 2026-06-17), but the `limit_price_through_market` skip path emits no fills while BT counts a missed-limit instead.

### D8 — Daily bias: identical V1+V2 logic, identical OANDA dailyAlignment=21 fix

BT (`engine.py:106–131`) and live (`scheduler.py:218–246`) both implement the same Combined V1+V2 bias (body% ≥ 0.4 OR close-position in top/bottom 20% of range). BT keys daily_bias by `(gold_d.index[i] + pd.Timedelta(days=1)).date()` to handle OANDA dailyAlignment=21 (line 110, drift bug #6 fix). Live reads `daily_candles[-2]` directly (line 220) — `count=2` from `get_candles(..., granularity="D")` returns the most recent two D-bars, where `[-2]` is yesterday's session bar from OANDA's perspective (already aligned to the prior session). Filter #28 override is identical (`BIAS_MODE = parse_bias_mode_env(...)`).

**Verdict:** Match. No drift.

### D9 — Daily-trade-cap: signal-gen no longer caps; engine caps on filled trades only

BT signal-gen line 71 comment: "Cap rework Jun 18: signal-gen no longer caps at max_trades_per_day. Engine execution loop caps on FILLED trades only." Engine `engine.py:208`: `if signal.strategy == "micro_alpha_sweep" and day_filled_trades >= max_per_day: continue` and `day_filled_trades` increments only inside the `result.filled` branch (line 315).

Live `scheduler.py:200–216` filters `LIMIT_TTL_EXPIRED` from the count and self-heals `_daily_state["trades"]` to the DB count. Live counter increments **optimistically** on signal fire (line 521) and rolls back on engine-skip (line 544).

**Verdict:** Different counting semantics; outcomes converge when broker order succeeds, diverge when limit-TTLs expire frequently.

---

## CRITICAL — TP formula match status

| System | TP formula match? | Pattern |
|---|---|---|
| Oil Macro | **NO** (BT uses `entry + range × multi`; live uses `asia_high − tp_buf`) | smoking gun |
| Gold Macro | YES (both use `asia_high − tp_buf`) | Gold-pattern |
| **Gold Micro** | **YES** (both use `range_high − tp_buf`) | Gold-pattern |

Gold Micro inherits the Gold Macro TP geometry exactly — the asia/consolidation-structure formula on **both** sides. The Oil Macro asymmetry does NOT exist here.

---

## Smoking-gun ranking (Gold Micro)

1. **Window-iteration mismatch + dedup keying (D3 + D4) — TOP CANDIDATE.** BT walks every H1 bar across all windows; live polls every 3 min via cron and only sees windows currently in scan phase. Combined with the (sbar_ts, sweep_dir) global dedup vs BT's (sbar_ts, start_hour) per-window dedup, overlapping-window same-direction sweeps fire twice in BT and once in live. Service restarts compound this: `_restore_traded_sweeps_on_startup` blocks for the engulfing window (45 min) but cannot recover sweeps whose engulfing M3 already formed during downtime. **No production audit yet.**
2. **Cooldown semantic asymmetry (D5).** Live cooldown advances on `order_error*` / `oanda_error*` / `sl_too_close_to_price` skip reasons; BT only on filled trades. Gold Micro is sensitive to this because the rolling-window architecture produces denser candidate signals than fixed-Asia macros.
3. **Filter-#27 dry-run gating (D7).** Live can refuse a limit at `limit_price_through_market` / `limit_invalid_sl_wrong_side`; BT does not model these refusals. Currently zero hits in prod (verified 2026-06-17), so impact is latent.
4. **Open-position DB+MT5 blocker (D6).** Orphans block all subsequent Micro signals until `reconcile_orphans` resolves. BT uses a clean `position_exit_time`. Magnifies any orphan event into a window-wide skip.
5. **Config-key drift (D2).** `ALPHA_SWEEP["asia_min_range"]` (BT signal-gen) vs `MICRO_ALPHA_SWEEP["min_range"]` (live). Same value today, no error if they diverge.

**Bottom line:** Gold Micro's TP formula matches BT (Gold pattern). The Oil-Macro–style asymmetry is absent. Divergence is concentrated in the **window-iteration / dedup-keying** layer (D3 + D4) — a Micro-specific smoking gun unique to the rolling-window architecture, not seen in the fixed-Asia macros. Secondary surfaces are the same six gates that drift Oil Macro and Gold Macro, plus the Filter-#27 live-only safety refusals.
