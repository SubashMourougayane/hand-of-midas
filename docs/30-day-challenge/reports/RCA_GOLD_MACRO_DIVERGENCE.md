# RCA — Live vs Backtest Signal Divergence (Gold Macro deep-dive)

**Date:** 2026-06-18
**System:** Gold Macro (XAU_USD, alpha_sweep + mean_rev + cross_market). Focus = Alpha-Sweep.
**Trigger:** Companion deep-dive to Oil Macro RCA (`RCA_LIVE_VS_BT_SIGNAL_DIVERGENCE.md`). Per the live↔backtest parity-gap memo, every system has a parallel reimplementation; verify whether Gold Macro inherits the same TP-formula divergence and the same production-only gates as Oil Macro.

**Method:** Code-level diff between BT signal-gen (`backend/strategies/alpha_sweep.py`) and the live core (`backend/scanner/scheduler.py:_run_alpha_sweep_core`). No replay numbers, no speculation.

---

## TL;DR

Gold Macro **DOES** ship two parallel implementations of Alpha-Sweep (BT in `alpha_sweep.py:generate_signals`, live in `scheduler.py:_run_alpha_sweep_core`). However:

- **The TP formula is IDENTICAL between BT and live** (both use the asia-structure formula `tp = asia_high - tp_buf` for LONG / `asia_low + tp_buf` for SHORT). This is **the OPPOSITE pattern** to Oil Macro, where BT uses an entry-based formula (`entry + asia_range × tp_multiplier`) and live uses an asia-structure formula. **Gold Macro does NOT have the D1 TP-formula divergence that smoking-gunned Oil Macro.**
- The detection math (sweep + engulfing + bias + risk gates) is line-for-line equivalent.
- Live still wraps the signal-gen in **6 production-only gates** that BT lacks (cooldown, open-position DB blocker, sweep-blacklist persistence, lookback windows, scheduler tick cadence, wall-clock window). Same drift surfaces as Oil Macro.

So Gold Macro's divergence — if any — is driven by the production-only gates and the live-data path, not by strategy math. Drift bug count for Gold Macro Alpha-Sweep stays at parity with Oil Macro on **gating** but **not** on TP geometry.

---

## Architecture: two parallel signal generators (same topology as Oil Macro)

| Layer | Function | File | Lines |
|---|---|---|---|
| **BT signal-gen** | `generate_signals(gold_h1, gold_m3, daily_bias)` | `backend/strategies/alpha_sweep.py` | 11–149 |
| **BT execution** | iterates `all_signals` from above | `backend/backtest/engine.py` | 193–392 |
| **Live signal-gen + exec (single fn)** | `_run_alpha_sweep_core(now, h1, daily, m3, dry_run)` | `backend/scanner/scheduler.py` | 408–786 |

Confirmed via grep: `scheduler.py` imports `ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE` from `backend.config` but does **NOT** import `alpha_sweep.generate_signals`. The live core is a hand-coded reimplementation.

---

## Differences (line-level)

### D1 — TP formula: **NO DIVERGENCE** (key contrast vs Oil Macro)

| | BT (`alpha_sweep.py`) | Live (`scheduler.py`) |
|---|---|---|
| **LONG TP** | `tp_buf = cfg.get("tp_structure_buffer", ar * cfg["tp_multiplier"])`<br>`tpv = ah - tp_buf` (lines 110–111) | `tp_buf = cfg.get("tp_structure_buffer", asia_range * cfg["tp_multiplier"])`<br>`tp = asia_high - tp_buf` (lines 703–704) |
| **SHORT TP** | `tpv = al + tp_buf` (line 135) | `tp = asia_low + tp_buf` (line 736) |

**Config (`config.py:36-53`):** `tp_multiplier=2.0`, `tp_structure_buffer=2.0`.

Both engines resolve to the same `tp_buf = 2.0` (because `tp_structure_buffer` is set, the fallback `ar * tp_multiplier` is never used). Both anchor TP on **asia structure**, not on entry. Same input data → same TP value → same `tp_too_close` filter outcome.

**Verdict:** Ruled out. **Gold Macro does NOT inherit Oil Macro's D1.** The Oil Macro asymmetry (`tpv = entry + ar × tp_multiplier` in BT vs `tp = asia_high - tp_buf` in live) does not exist here — Gold Macro's BT path also uses the asia-structure formula. This is the most important finding of this RCA.

### D2 — Live: 5-min cooldown after last `gd_signals` row

`scheduler.py:447–462`:
```python
recent_signal = execute("SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='alpha_sweep' ORDER BY timestamp DESC LIMIT 1", fetch=True)
...
if recent_signal[0]["taken"] or _skip.startswith("order_error") or _skip.startswith("oanda_error") or _skip == "sl_too_close_to_price":
    if now < last_signal_time + timedelta(minutes=5):
        return None
```

BT counterpart (`engine.py:268–269`):
```python
if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
    continue
```

Same 5-min interval, but semantics differ:
- BT: `last_signal_time` only updates when a signal is **filled** (line 360 — only set after `execute_trade` returns a non-None filled result). Skipped signals do not advance the cooldown.
- Live: cooldown advances on `taken` OR specific skip reasons (`order_error*`, `oanda_error*`, `sl_too_close_to_price`). A signal with skip reason `sl_too_close_to_price` blocks the next 5 minutes of scheduler ticks even though no trade was actually opened.

**Effect:** Live skips sweeps that BT would still consider when the prior signal had a known-failure skip reason.

**Verdict:** Real divergence — same shape as Oil Macro D2.

### D3 — Live: open-position DB blocker (cross-strategy lock)

`scheduler.py:466–474`:
```python
open_macro = execute(
    """SELECT COUNT(*) as cnt FROM gd_trades
       WHERE exit_time IS NULL
         AND strategy IN ('alpha_sweep', 'mean_rev', 'cross_market')""",
    fetch=True
)
if open_macro and open_macro[0]["cnt"] > 0:
    return None
```

**Important:** this gate locks Alpha-Sweep entries on ANY open Gold-Macro trade (alpha_sweep, mean_rev, cross_market) — including a multi-day Cross-Market position with `max_hold_days=20` or a Mean-Rev hold up to 5 days. BT has no equivalent cross-strategy interlock — `engine.py` walks each signal independently with only the 5-min cooldown.

**Effect:** Any open Cross-Market or Mean-Rev trade silently blocks **all** Alpha-Sweep signals for the duration of the hold (potentially 20 trading days). BT will fire these signals.

**Verdict:** Real divergence. **Gold Macro–specific** (Oil Macro doesn't have mean_rev/cross_market peers in scope). Likely a much larger source of dropped signals than the equivalent gate on Oil Macro.

### D4 — Live: persistent sweep blacklist (`_traded_sweeps_macro["keys"]` + DB `is_sweep_consumed`)

`scheduler.py:633–641, 757–776`:
- After successful signal fire OR after the 0.75-hour engulfing window expires without engulfing → sweep added to in-memory `_traded_sweeps_macro["keys"]` AND persisted via `mark_sweep_consumed("gold-macro", today, sweep_key)`.
- Each tick: `if sweep_key in _traded_sweeps_macro["keys"]: continue`. Hot cache + DB-backed for restart safety (Issue #9 fix 2026-06-15).

BT has no equivalent — `alpha_sweep.py:147` `break  # One engulfing per sweep` only prevents multiple engulfings PER sweep within ONE pass.

**Effect:** Same race as Oil Macro: live can blacklist a sweep prematurely if a transient broker error fires `execute_signal` at line 721/753 (which consumes the sweep at line 757) but the order fails downstream. Subsequent ticks see the blacklisted sweep and skip the engulfing.

**Verdict:** Real divergence — same shape as Oil Macro D4.

### D5 — Live: 24-bar H1 lookback + 50-bar M3 lookback

`scheduler.py:396–404`:
```python
h1_candles = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=24, price="BA") if c.get("complete", True)]
...
daily_candles = get_candles(instrument="XAU_USD", granularity="D", count=2, price="BA")
m3_candles = get_candles(instrument="XAU_USD", granularity="M3", count=50, price="BA")
```

BT loads the entire CSV (`engine.py:27–29` — `load_candles("XAU_USD_H1.csv")`, `XAU_USD_M3.csv`).

Note Gold Macro live uses **OANDA** (`get_candles → OANDA REST`), not DWX (Oil Macro lives on JustMarkets MT5). The lookback semantics still apply: if OANDA returns fewer than 8 H1 bars (`scheduler.py:397–399 — len(h1_candles) < 8`) live silently exits.

50 M3 bars × 3 min = 150 minutes = 2.5 hours of M3 history. With `engulfing_window_hours=0.75` (45 min) this is comfortable, but only marginally — pre-08:00 UTC service restart with empty OANDA M3 cache could still under-supply the engulfing search.

**Verdict:** Real divergence. Risk lower than Oil Macro because of OANDA's better historical-data reliability.

### D6 — Live: 3-min scheduler tick + M3 freshness window

Live scheduler runs `london_session_job` every 3 min during 08:00–19:00 UTC (`scheduler.py:939` cron `*/3, hour=8-19`). Each tick fetches latest 50 M3 bars and checks for engulfing in `relevant_m3 = [c for c in m3_candles if sweep_time < ts <= window_end]` (lines 658–662). At tick time T, only M3 bars CLOSED by T are visible; intra-bar engulfings are invisible until the bar closes 3 min later.

BT has the entire 0.75h engulfing window of M3 bars at signal-gen time.

**Effect:** Engulfing has effective window of ~0.75h − 3min ≈ 42 min in live vs 45 min in BT. Marginal.

**Verdict:** Real divergence, marginal magnitude. Same shape as Oil Macro D6.

### D7 — Live wall-clock 08-20 UTC window

`scheduler.py:372–374`:
```python
if hour < cfg["scan_start"] or hour > cfg["scan_end"]:
    _log.debug("SCAN", "outside_scan_window", ...)
    return
```

BT (`alpha_sweep.py:30`):
```python
scan_window = day_h1[(day_h1.index.hour >= cfg["scan_start"]) & (day_h1.index.hour < cfg["scan_end"])]
```

BT is per-bar; live is wall-clock. If the gold-macro service was DOWN during 08:00–19:00 UTC on a day, that day's signals are never evaluated. BT processes every historical day.

**Verdict:** Real divergence — same shape as Oil Macro D7.

### D8 — `daily_candles` slicing (yesterday's bias) — **PARTIAL DIVERGENCE**

| | BT | Live |
|---|---|---|
| Source | `gold_d` DataFrame, indexed by date | `daily_candles` list from `get_candles(count=2)` (scheduler.py:400) |
| Yesterday's bar | `gold_d.iloc[i-1]`, with `trade_date = gold_d.index[i] + 1day` (engine.py:167 — drift bug #6 fix) | `daily_candles[-2]` (scheduler.py:525) |

BT shifts by +1 day to compensate for OANDA's `dailyAlignment=21` — a bar at timestamp T 21:00 UTC represents the session T 21:00 → T+1 21:00, so `bar.date()` is 1 day before the session it represents. Live takes `daily_candles[-2]` — that's the second-to-last daily bar from a `count=2` fetch, i.e., yesterday's bar by raw index, which on OANDA = the session two days prior.

**Wait — closer reading.** With `count=2`, the request returns the two most recent **complete** daily bars. If the request fires at 14:00 UTC today (mid-scan-window), the last bar's timestamp is yesterday 21:00 UTC representing the session yesterday→today (i.e., the still-open session). `daily_candles[-1]` = yesterday's 21:00 bar = session-in-progress. `daily_candles[-2]` = day-before-yesterday's 21:00 bar = the session that closed yesterday at 21:00 — which is exactly "yesterday's session bias." That matches BT's intent of using the prior session.

**But:** if OANDA returns only the most recent INCOMPLETE bar excluded, `count=2` could mean `[..., yesterday-21:00]` and `daily_candles[-2]` is the wrong day. This depends on OANDA's `complete` flag handling, which the live path does not filter on for daily bars (only for H1, line 396).

**Verdict:** Possible divergence. Worth verifying that OANDA daily `count=2` always returns `[day-before-yesterday-21:00, yesterday-21:00]` regardless of intra-session timing. If OANDA ever returns the in-progress bar, live's bias is computed off the WRONG day vs BT.

### D9 — Bid/ask source

BT loads bid/ask columns directly from the CSVs (`load_candles("XAU_USD_M3.csv")`). Live uses OANDA's BA pricing (`price="BA"`), which returns true bid/ask. Both sides are real (no mid synthesis). For Gold (XAU_USD), the live `mt5_executor` synthetic spread issue documented in Oil Macro D9 does not apply.

**Verdict:** Ruled out for Gold Macro. (Oil Macro uses MT5/DWX with broken Brent half-spread; Gold Macro uses OANDA which delivers real bid/ask.)

### D10 — Cap/cooldown reset timing

| | BT | Live |
|---|---|---|
| Trades-today cap | per-day reset (`engine.py:255–256` — `if trade_date != current_date: day_filled_trades = 0`) | per-day reset by `entry_time::date = today` query (`scheduler.py:438`) |
| Cap excludes | LIMIT_TTL_EXPIRED only counts FILLED trades | same — `exit_reason NOT IN ('LIMIT_TTL_EXPIRED', 'LIMIT_TTL_EXPIRED_GRACE')` |

Cap rework Jun 18 fixed the gap. **In parity.**

### D11 — Daily-bias formula

Both BT (`engine.py:170–186`) and live (`scheduler.py:534–549`) use the same V1+V2 combined bias logic: `body_pct >= 0.4` (V1), `close_position >= 0.8 / <= 0.2` (V2), bearish wins ties. Identical math.

**Verdict:** In parity.

### D12 — Filter #28 bias-mode override

Both BT (`engine.py:151–156`) and live (`scheduler.py:554–558`) honour `BIAS_MODE` env var. BT reads it via `bias_mode` parameter; live reads it via `from backend.config import BIAS_MODE as _bias_mode_cfg`. Same default (`"production"`), same flip semantics (`"neutral"` → all days neutral). **In parity** post-F28-H1 fix.

---

## Critical question: TP formula divergence — Gold vs Oil

| | Oil Macro BT | Oil Macro Live | Gold Macro BT | Gold Macro Live |
|---|---|---|---|---|
| LONG TP | `entry + ar × tp_mult` | `asia_high − tp_buf` | `asia_high − tp_buf` | `asia_high − tp_buf` |
| SHORT TP | `entry − ar × tp_mult` | `asia_low + tp_buf` | `asia_low + tp_buf` | `asia_low + tp_buf` |

**Gold Macro's BT was already updated to the asia-structure formula.** Oil Macro's BT was not. This means the structural TP-divergence smoking gun on Oil Macro **does not apply to Gold Macro** — both sides compute the same TP.

What this implies:
1. Per-trade P&L from a filled signal should match between BT and live for Gold Macro (subject to slippage / fill-model differences in `execute_trade` vs OANDA actual fills).
2. The `tp_too_close` filter outcome should be identical for Gold Macro (same TP geometry, same risk × 0.8 threshold).
3. Any signal-set divergence on Gold Macro is driven by the production-only gates (D2–D8), not by strategy math.

This is consistent with the live↔backtest parity-gap memo's claim that Gold Macro's drift surface is gating, not signal arithmetic.

---

## Smoking-gun ranking for Gold Macro Alpha-Sweep

| # | Hypothesis | Evidence | Likelihood explains a missed live signal |
|---|---|---|---|
| **1** | **D3 (cross-strategy open-position lock)** — any open Cross-Market or Mean-Rev trade locks out Alpha-Sweep for up to 20 days | HIGH (line-level proof, multi-day hold by strategy design) | **HIGH** |
| 2 | D2 (5-min cooldown advancing on skip reasons) — `sl_too_close_to_price` swallowing next tick | HIGH (line-level proof) | MEDIUM |
| 3 | D4 (sweep blacklist persistence after broker reject) | MEDIUM (race condition narrow, but DB-backed across restarts) | MEDIUM |
| 4 | D8 (OANDA daily bar alignment off-by-one) — needs verification | MEDIUM (depends on OANDA `complete` semantics on daily bars) | LOW–MEDIUM |
| 5 | D7 (wall-clock window) — service downtime | MEDIUM (no uptime data pulled here) | MEDIUM |
| 6 | D5 (24-bar H1 lookback + missing pre-08:00 OANDA bars) | LOW (OANDA more reliable than DWX) | LOW |
| 7 | D6 (3-min tick latency vs 45-min engulfing window) | LOW (margin is comfortable) | LOW |
| — | D1 (TP formula) | **RULED OUT** — both sides identical | NONE |

---

## Recommendation

Same as Oil Macro RCA: unify the implementations. Have `_run_alpha_sweep_core` call `alpha_sweep.generate_signals()` directly with a DWX-or-OANDA→DataFrame adapter. This eliminates D2/D4/D5/D6 as potential drift surfaces and leaves only D3 (cross-strategy lock) and D7 (wall-clock window) as deliberately production-only gates.

Effort budget for Gold Macro: lower than Oil Macro because **D1 is already in parity**, so the unification is mechanical, not behavioural. Estimated ~4h.

**One Gold-Macro-specific item before unification:** verify D8 — pull live `gd_signals` rows around 22:00 UTC daily-close boundaries and confirm that the `bias` value in the row matches what BT computes for the same date. If not, OANDA's daily-bar-alignment slicing in live is off by a day vs BT.

---

## Files referenced

- `backend/strategies/alpha_sweep.py` (BT signal-gen, lines 11–149)
- `backend/backtest/engine.py` (BT execution loop + bias resolver, lines 82–428)
- `backend/scanner/scheduler.py` (live signal-gen + execution, parallel impl, lines 363–786)
- `backend/scanner/live_engine.py` (execute_signal + position checks, 857 lines)
- `backend/config.py` (ALPHA_SWEEP config, lines 35–53)
- `backend/backtest/neutral_bias.py` (Filter #28 helpers)
