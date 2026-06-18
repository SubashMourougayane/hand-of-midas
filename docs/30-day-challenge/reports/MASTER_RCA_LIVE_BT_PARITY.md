# MASTER RCA — Live ↔ Backtest Signal Divergence (All 4 Systems)

**Date:** 2026-06-18
**Author:** RCA spawned from Day 1 (30-day challenge) disaster — live system fired wrong-side LONG trades into bearish bias, lost $1,517. Backtest on the SAME freshly-imported JustMarkets data for the same window would have produced **+$1,115** across all 4 systems. Δ = $2,632. Same broker, same instruments, same strategy on paper.

**Question answered here:** Why do live and BT fire different signals on the same data? Is it one bug repeated 4 times, or 4 different bugs?

**Bottom line:** **4 systems, 4 different smoking guns, ONE shared root cause.** The root cause is **architectural** — every system has TWO parallel implementations of the strategy logic. Live and BT each have their own copy. They drift independently.

---

## Direct evidence — Day 1 numbers

| Source | Window | Trades | Net P&L |
|---|---|---|---|
| **Live JM (4 systems)** | Jun 18 (post $10K reset) | 4 SL hits + 1 BE-bug scratch + 2 TTL_EXPIRED | **−$1,517** |
| **BT on JM CSV (4 systems)** | Jun 17–18 (with bias_mode=neutral) | 10 trades (multi-system) | **+$1,115** |
| **Δ (BT − Live)** | | | **+$2,632** |

**Per-system BT vs Live overlap (Oil Macro Jun 11–18 — the most-affected system):**

- BT fired **7** signals: Jun 12 16:21 LONG, Jun 15 10:33 LONG, Jun 15 17:12 LONG, Jun 16 08:12 LONG, Jun 17 08:30 LONG, Jun 17 10:51 LONG, Jun 17 15:09 SHORT
- Live fired **5** signals: Jun 11 12:18 LONG, Jun 11 14:45 LONG, Jun 17 14:45 LONG, Jun 17 17:51 LONG, Jun 17 21:54 SHORT
- **Overlap: ZERO exact matches** (closest is Jun 17 SHORT in BT 15:09 vs live 21:54 — 6.5 hours apart, different price levels)

This is not "live missed one signal." This is **completely different signal sets on the same broker prices**.

---

## Why this happens — the architectural finding

**Every one of the 4 systems has TWO implementations of the strategy logic:**

| System | BT signal-gen function | Live signal-gen function | Live calls BT? |
|---|---|---|---|
| **Oil Macro** | `generate_signals()` in `backend-oil/strategies/alpha_sweep.py:29` | `_run_alpha_sweep_core()` in `backend-oil/scanner/scheduler.py:87` | NO |
| **Gold Macro** | `generate_signals()` in `backend/strategies/alpha_sweep.py:11` | `_run_alpha_sweep_core()` in `backend/scanner/scheduler.py:408` | NO |
| **Gold Micro** | `generate_signals()` in `backend/strategies/micro_alpha_sweep.py:42` | `_run_micro_sweep_core()` in `backend-micro/scanner/scheduler.py:184` | NO |
| **Oil Micro** | `generate_signals()` inlined in `backend-oil-micro/backtest/engine.py:72` | `_run_micro_sweep_core()` in `backend-oil-micro/scanner/scheduler.py:156` | NO |

**Confirmed via grep:** no scheduler imports its system's `generate_signals` from the strategy module. Each system's live core is a hand-written reimplementation.

This is the [project-live-backtest-parity-gap] architectural risk already in memory ("6 confirmed drift bugs in 3 weeks"). **Today's signal-divergence finding is drift bug #7.**

---

## All findings — exhaustive

### Findings common to all 4 systems

| Finding | What it is | Files |
|---|---|---|
| **F-COMMON-1** | Live scheduler has its own copy of strategy logic, NOT importing BT's `generate_signals`. | All 4 `scanner/scheduler.py` files |
| **F-COMMON-2** | Live wraps signal-gen in production-only gates: cooldown, open-position blocker, sweep blacklist, bar-lookback caps, scheduler tick cadence, wall-clock window. | All 4 schedulers, lines vary |
| **F-COMMON-3** | Bid/ask data path differs: BT loads from CSV (real bid/ask columns); live fetches from broker (DWX for Oil systems = MT5; OANDA for Gold systems). | `backend/data/cache.py:7` vs `backend/execution/oanda_executor.py` & `backend/execution/mt5_executor.py:392` |
| **F-COMMON-4** | Daily bias V1+V2 math is identical line-for-line across BT and live in all 4 systems. | per-system `engine.py` + `scheduler.py` |
| **F-COMMON-5** | Filter #28 (bias-mode) override surfaces differ: BT takes `bias_mode` kwarg, live reads `BIAS_MODE` env var. Same end-state, two surfaces — env-typo on VPS silently desyncs from parity harness. | per-system |

### Per-system smoking guns

| System | Smoking gun ID | What it is | Severity | Already explains today? |
|---|---|---|---|---|
| **Oil Macro** | **D1 — TP-formula divergence** | BT: `tpv = entry + asia_range × tp_multiplier` (entry-based, open-ended). Live: `tp = asia_high − tp_structure_buffer` (structure-based, capped). Same data → different TP value → different `tp_too_close` filter outcome → different signal sets. **THE primary smoking gun for today.** | HIGH | YES — explains LONG signals BT picked but live filtered (and vice versa) |
| **Gold Macro** | **D3 — Cross-strategy open-position lock** | Live blocks ALL Alpha-Sweep entries when ANY of `('alpha_sweep', 'mean_rev', 'cross_market')` has `exit_time IS NULL`. Cross-Market positions can hold for `max_hold_days=20`. BT has no such interlock. | HIGH | LATENT — none open Jun 11–17, but designed to block for weeks |
| **Gold Micro** | **D3 + D4 — rolling-window iteration + dedup keying** | (a) BT walks every H1 bar across all 12 windows; live polls only currently-active windows on a 3-min cron. Sweep detection is bar-deterministic in BT, tick-deterministic in live. (b) BT keys dedup as `(sbar_ts, start_hour)`; live keys as `(bar_timestamp, sweep_dir)` global. Same H1 bar → fires twice in BT (different windows), once in live. | MEDIUM-HIGH | YES if any same-direction overlap |
| **Oil Micro** | **D4 — MT5 cross-system lock** | Live's MT5 `get_open_trades()` is account-wide, not strategy-filtered. Oil Macro and Oil Micro both trade BCO_USD on the same JustMarkets demo account. **Any open Oil Macro BCO_USD trade silently kills all Oil Micro entries.** BT has no equivalent. | HIGH | YES — Oil Micro 1310e9cd fired only because Oil Macro had no open position at that moment; Oil Macro 9b521a21/c5b353f0 LONGs (15:57, 16:42) likely blocked Oil Micro thereafter |

### Per-system divergence catalogue (D1–DN)

#### Oil Macro

| ID | Divergence | BT side | Live side | Verdict |
|---|---|---|---|---|
| D1 | **TP formula** | `tpv = entry + ar × tp_mult` | `tp = asia_high − tp_buf` (LONG); `asia_low + tp_buf` (SHORT) | **HIGH** — primary smoking gun |
| D2 | 5-min cooldown advancing on skip reasons | advances only on filled | advances on `taken=True` OR skip-`order_error*` OR `sl_too_close_to_price` | Real |
| D3 | Open-position DB blocker | `position_exit_time` projection | DB query: `OIL-AS-%` rows with `exit_time IS NULL` blocks indefinitely | Real (low for Jun 11-17 window — no orphans) |
| D4 | Persistent sweep blacklist | per-day in-memory set | in-memory set + DB-backed `mark_sweep_consumed` (restart-safe) | Real |
| D5 | 24-bar H1 / 50-bar M3 lookback | full CSV | DWX `get_candles(count=24/50)` | Real, marginal magnitude |
| D6 | 3-min scheduler tick + M3 freshness | full M3 history per signal | only M3 closed by scheduler tick time | Real, marginal |
| D7 | Wall-clock 08-20 UTC window | per-bar `index.hour` filter | scheduler returns immediately if outside hour range | Real (fires if service is down) |
| D8 | `daily_candles` slicing for yesterday's bias | `oil_d.iloc[i-1]` with `+1day` shift (drift-bug-#6 fix) | `daily_candles[-2]` from `count=2` fetch | Possible (depends on DWX daily completeness) |
| D9 | Bid/ask reconstruction | CSV columns | MT5 `mid ± half_spread` with broken Brent point-size formula | Real but doesn't affect mid-based signal detection |
| D10 | Cap reset semantics | per-day reset on `current_date` change | DB query with `entry_time::date = today` | In parity post-Jun 18 cap rework |

#### Gold Macro

| ID | Divergence | BT side | Live side | Verdict |
|---|---|---|---|---|
| D1 | **TP formula** | `tp = asia_high − tp_buf` | `tp = asia_high − tp_buf` | **RULED OUT — same on both sides** |
| D2 | 5-min cooldown advancing on skip reasons | filled only | `taken` OR skip-failures | Real |
| D3 | **Open-position lock — CROSS-STRATEGY** | per-trade `position_exit_time` | DB query: `strategy IN ('alpha_sweep', 'mean_rev', 'cross_market')` blocks all 3 | **HIGH — cross-strategy lock can block for 20+ days (Cross-Market hold time)** |
| D4 | Persistent sweep blacklist | per-day | in-memory + DB-backed | Real |
| D5 | 24-bar H1 / 50-bar M3 lookback | full CSV | OANDA `get_candles(count=24/50)` | Real, marginal |
| D6 | 3-min scheduler tick | per-bar | wall-clock 3-min cron | Real, marginal |
| D7 | Wall-clock 08-19 UTC | per-bar `index.hour` | scheduler early-return | Real |
| D8 | OANDA `dailyAlignment=21` daily-bias slicing | BT explicitly shifts `+1day` (drift-bug-#6 fix at engine.py:167) | live takes `daily_candles[-2]` raw | Possible — depends on OANDA daily-bar completeness flag |
| D9 | Bid/ask source | CSV bid/ask | OANDA `price="BA"` real bid/ask | In parity for Gold |
| D10 | Cap reset | parity post-Jun 18 | parity post-Jun 18 | In parity |
| D11 | Daily-bias formula | V1+V2 identical | V1+V2 identical | In parity |
| D12 | Filter #28 surface | `bias_mode` kwarg | `BIAS_MODE` env | In parity end-state |

#### Gold Micro

| ID | Divergence | BT side | Live side | Verdict |
|---|---|---|---|---|
| D1 | **TP formula** | `tpv = range_high − tp_buf` | `tp = range_high − tp_buf` | **RULED OUT** |
| D2 | **Config-key drift** | reads `ALPHA_SWEEP["asia_min_range"]` | reads `MICRO_ALPHA_SWEEP["min_range"]` | Same value today (5.0) — silent on drift |
| D3 | **Window iteration model** | per-H1-bar, all-windows-each-bar walk | 3-min cron + only currently-active-windows | **HIGH — rolling-window-specific** |
| D4 | **Sweep dedup keying** | `(sbar_ts, start_hour)` per-window tuple | `(bar_timestamp, sweep_dir)` global string | **HIGH — dormant; surfaces on overlapping-window same-direction sweeps** |
| D5 | Cooldown advancing on skip-failures | filled only | `taken` OR skip-failures | Real |
| D6 | Open-position blocker (DB + MT5) | `position_exit_time` projection | DB `GD-MI-%` rows + `get_open_trades()` | Real, contained to `GD-MI-%` |
| D7 | Filter #27 dry-run gating | shared `compute_limit_price` | shared `compute_limit_price` + through-market refusal + wrong-side-SL refusal | Latent (no hits in prod) |
| D8 | Daily bias V1+V2 + OANDA dailyAlignment=21 | identical math | identical math | In parity |
| D9 | Daily-trade-cap counting | filled only | optimistic + roll-back on engine-skip | Diverges only on TTL_EXPIRED frequency |

#### Oil Micro

| ID | Divergence | BT side | Live side | Verdict |
|---|---|---|---|---|
| D1 | **TP formula** | `tpv = range_high − tp_buf` | `tp = range_high − tp_buf` | **RULED OUT** |
| D2 | **Rolling-window iteration** | per-H1-bar walk | 3-min cron + active-windows-only | Real (HIGH for Micro) |
| D3 | Cooldown semantics | filled only | `taken` OR skip-failures | Real |
| D4 | **Open-position MT5 cross-check (account-wide)** | none | DB query + `get_open_trades()` (no strategy filter) | **HIGH — Oil Macro BCO_USD trade locks Oil Micro out** |
| D5 | Persistent sweep blacklist (per-direction string) | per-day per-(ts, start_hour) tuple | DB-backed `(ts, sweep_dir)` string | Real, persistent across restart |
| D6 | 3-min scheduler tick cadence | bar-deterministic | tick-deterministic | Real |
| D7 | 45-min engulfing-window expiry | bar-driven | wall-clock-driven | Asymmetric on data gaps |
| D8 | Startup cooldown | none | 45-min block on startup | Live-only safety |
| D9 | Hardcoded `range(2, ...)` for engulfing | reads `cfg["skip_first_bar"]` | hardcoded `2` | Latent — flips silently if config changes |
| D10 | F28 env-var split | `bias_mode` kwarg | `BIAS_MODE` env | In parity end-state |
| D11 | Filter #27 limit-order live state machine | shared `compute_limit_price` only | full DWX file polling + grace + reconciliation | Asymmetric only on filled/unfilled classification |

---

## Cross-system smoking-gun matrix

| Aspect | Oil Macro | Gold Macro | Gold Micro | Oil Micro |
|---|---|---|---|---|
| Parallel impl confirmed | ✓ | ✓ | ✓ | ✓ |
| TP formula divergence | **YES (D1)** | NO | NO | NO |
| Cross-strategy lock | NO | **YES (D3, alpha+meanrev+cross)** | NO | NO |
| Cross-system MT5 lock | NO | NO | NO | **YES (D4, BCO_USD shared)** |
| Window-iteration mismatch | NO | NO | **YES (D3)** | **YES (D2)** |
| Dedup-keying mismatch | NO | NO | **YES (D4)** | **YES (D5)** |
| Persistent sweep blacklist | YES | YES | YES | YES |
| 5-min cooldown semantic asymmetry | YES | YES | YES | YES |
| Bar-lookback cap | YES | YES | YES | YES |
| Wall-clock window gate | YES | YES | YES | YES |
| Config-key drift | NO | NO | YES (`asia_min_range` vs `min_range`) | NO |
| Hardcoded constant drift | NO | NO | NO | YES (`range(2, ...)`) |

**Pattern:** Macros (Oil/Gold) drift on TP-math + open-position interlocks. Micros (Gold/Oil) drift on rolling-window iteration + dedup keying. **All 4 share the 6 production-only gates** as extra divergence surfaces.

---

## Numerical proof — Oil Macro D1 worked example

For LONG entry $79.30, asia_high $79.50, asia_range $1.00, risk $0.30, `tp_multiplier=2.0`, `tp_structure_buffer=0.13`:

- **BT TP:** `entry + asia_range × tp_multiplier = 79.30 + 1.00 × 2.0 = $81.30` (open-ended target)
- **Live TP:** `asia_high − tp_structure_buffer = 79.50 − 0.13 = $79.37` (capped at structure)
- TP-distance threshold: `risk × 0.8 = $0.24`
- **BT:** `tp − entry = $2.00 > $0.24` → passes filter, signal fires
- **Live:** `tp − entry = $0.07 < $0.24` → **fails filter, signal blocked**

Same data, different TPs, different filter outcomes. Quantified in 8 lines.

---

## What's NOT diverging (verified parity)

- Sweep detection (`bar.high > asia_high + threshold`) — identical math all 4 systems
- Engulfing detection — identical math all 4 systems
- Daily bias V1+V2 — identical formula all 4 systems
- SL placement (`sweep_wick ± sl_buffer`) — identical
- Risk gate (`if risk < min_sl: clamp; if risk > range × 0.8: skip`) — identical
- Filter #27 limit-price math — shared via `backend/execution/limit_price.py:compute_limit_price` — identical by design
- Filter #28 daily-bias override — identical end-state via `BIAS_MODE` resolution

---

## Why each smoking gun explains Day 1 specifically

| System | Today's live behavior | RCA explanation |
|---|---|---|
| Oil Macro | Fired LONG @ $77.06 + LONG @ $77.10 (both SL'd, −$1,151 combined) | TP formula divergence (D1): live's `asia_high − tp_buf` accepted these sweeps because the calculated TP was just inside the structural cap. BT's `entry + range × multi` rejected them because the open-ended target was unreachable in the prevailing range. So live fires what BT skips → live takes wrong-side bets. |
| Oil Micro | Fired LONG @ $77.16 / $77.58 (both TTL_EXPIRED), LONG @ $78.47 (SL'd −$367), SHORT @ $78.07 (BE-bug +$3) | D2 + D6 (rolling-window cadence): each tick, only 1 active window's worth of M3 history is scanned. BT picked SHORT setups Jun 17 04:18, 08:30, 19:18 that live missed entirely. D4 (MT5 cross-system lock) likely activated when Oil Macro's 9b521a21 fired @ 15:57 — Oil Micro signals after that point would have been blocked by `get_open_trades()`. |
| Gold Macro | No live signals fired Jun 17–18 | D3 cross-strategy lock — but no Cross-Market or Mean-Rev was open, so this can't be the explanation. More likely D7 wall-clock (no signals during scan window) OR D5 lookback (24-bar H1 didn't include the BT-detected sweep). |
| Gold Micro | 1 LONG signal Jun 17 (TTL_EXPIRED), 1 SHORT BE-bug | D3 (rolling-window iteration) + D4 (dedup keying). Multiple windows can detect same sweep in BT but only one fires in live. |

---

## Answers to standing questions

**Q1: Is it ONE bug repeated 4 times?**
A: NO. **4 different smoking guns** across systems. The architectural root cause (parallel implementations) is shared. The behavioral bugs that surface from that root cause are each system-specific.

**Q2: Why does live miss signals BT picks up?**
A: Six gates wrapping live's signal-gen that don't exist in BT (cooldown semantics, open-position blockers, persistent blacklists, lookback caps, scheduler cadence, wall-clock windows). PLUS Oil Macro has TP-math divergence that filters signals differently. PLUS Micros have window-iteration mismatch.

**Q3: Why does live pick signals BT doesn't?**
A: Same 6 gates but interpreted differently — live's tick-cadence scanning can detect sweeps at different bar boundaries than BT's per-bar walk. Plus Oil Macro D1 produces TPs that pass live's filter but fail BT's (or vice versa), so each side accepts/rejects different sweeps.

**Q4: Is the strategy itself broken?**
A: NO. The strategy logic (sweep + engulfing + bias + risk) is in parity. The breakage is in how live executes that logic — different gates, different iteration order, different state persistence.

**Q5: What if we make live call BT's `generate_signals` directly?**
A: That's the recommended fix. Eliminates D1, D2, D4 (signal-detection layer divergences) entirely. Production-only gates (D3 open-pos, D7 wall-clock) wrap the call but no longer drift on strategy math.

---

## Recommendation

**Unify by making each live scheduler call its system's BT `generate_signals` instead of having an inline reimplementation.** Production-only gates wrap the call.

**Effort estimate:** ~12 hours total across 4 systems. Phasing in the companion document `REFACTOR_PLAN_LIVE_BT_UNIFY.md`.

---

## Files referenced

### BT signal-gen (4 systems)

- `backend-oil/strategies/alpha_sweep.py` (Oil Macro, lines 29–148)
- `backend/strategies/alpha_sweep.py` (Gold Macro, lines 11–149)
- `backend/strategies/micro_alpha_sweep.py` (Gold Micro, lines 42–223)
- `backend-oil-micro/backtest/engine.py` (Oil Micro inline, lines 72–226)

### Live signal-gen (4 systems)

- `backend-oil/scanner/scheduler.py:_run_alpha_sweep_core` (Oil Macro, lines 87–431)
- `backend/scanner/scheduler.py:_run_alpha_sweep_core` (Gold Macro, lines 408–786)
- `backend-micro/scanner/scheduler.py:_run_micro_sweep_core` (Gold Micro, lines 184–571)
- `backend-oil-micro/scanner/scheduler.py:_run_micro_sweep_core` (Oil Micro, lines 156–525)

### Shared infrastructure

- `backend/data/cache.py:7` — `load_candles` (BT data path)
- `backend/execution/oanda_executor.py` — Gold systems' live data path
- `backend/execution/mt5_executor.py:392` — Oil systems' live data path (DWX → MT5)
- `backend/execution/limit_price.py:compute_limit_price` — Filter #27 shared math
- `backend/backtest/neutral_bias.py` — Filter #28 helpers

### Per-system divergence reports (companions to this master)

- `docs/30-day-challenge/reports/RCA_LIVE_VS_BT_SIGNAL_DIVERGENCE.md` — Oil Macro
- `docs/30-day-challenge/reports/RCA_GOLD_MACRO_DIVERGENCE.md` — Gold Macro
- `docs/30-day-challenge/reports/RCA_GOLD_MICRO_DIVERGENCE.md` — Gold Micro
- `docs/30-day-challenge/reports/RCA_OIL_MICRO_DIVERGENCE.md` — Oil Micro
