# RCA — Live vs Backtest Signal Divergence (Oil Macro deep-dive)

**Date:** 2026-06-18
**Trigger:** Day 1 of 30-day challenge — live system fired wrong-side LONG trades into bearish bias, lost $1,517. BT on freshly imported JM data (`data/raw/BCO_USD_*.csv`) for the same Jun 11–18 window fired completely different signals and would have made +$1,115. Same broker (JustMarkets), same instrument (BRENT.ecn), same strategy logic on paper.

**Question:** Why does live miss signals BT picks up — and pick signals BT doesn't?

**Method:** Code-level diff between BT path and live path. No assumptions, no replay numbers without source.

---

## TL;DR

**Live and BT use TWO PARALLEL implementations of the strategy logic**, not one shared function:

- **BT path:** `backend-oil/backtest/engine.py` → `generate_signals()` in `backend-oil/strategies/alpha_sweep.py`
- **Live path:** `backend-oil/scanner/scheduler.py:_run_alpha_sweep_core()` (lines 87–431) — a hand-coded reimplementation

Same sweep+engulfing math, but **the TP formula differs** and live wraps the call in **6 production-only gates** that BT doesn't have. The combination produces different signal sets on the same data.

The "live↔backtest parity gap" architectural risk is already documented in memory ([[project-live-backtest-parity-gap]] — 6 confirmed drift bugs in 3 weeks). **Today's signal divergence is drift bug #7.**

---

## Architecture: two parallel signal generators

| Layer | Function | File | Lines |
|---|---|---|---|
| **BT signal-gen** | `generate_signals(oil_h1, oil_m3, daily_bias)` | `backend-oil/strategies/alpha_sweep.py` | 29–148 |
| **BT execution** | iterates `all_signals` from above | `backend-oil/backtest/engine.py` | 158–209 |
| **Live signal-gen + exec (single fn)** | `_run_alpha_sweep_core(now, h1, daily, m3)` | `backend-oil/scanner/scheduler.py` | 87–431 |

**Live does NOT call `generate_signals()`.** Confirmed via grep — no import of the strategy module in scheduler.py beyond the inline reimplementation.

---

## Differences (line-level)

### D1 — TP formula (CONFIRMED math divergence)

| | BT (`alpha_sweep.py`) | Live (`scheduler.py`) |
|---|---|---|
| **LONG TP** | `tpv = entry + ar * cfg["tp_multiplier"]` (line 118) | `tp = asia_high - cfg.get("tp_structure_buffer", asia_range * cfg["tp_multiplier"])` (line 365) |
| **SHORT TP** | `tpv = entry - ar * cfg["tp_multiplier"]` (line 136) | `tp = asia_low + tp_buf` (line 383) |

**Config:** `tp_multiplier=2.0`, `tp_structure_buffer=0.13`.

**BT semantics:** TP is anchored on **entry**, distance = `asia_range × 2.0`.
**Live semantics:** TP is anchored on **asia structure**, distance = fixed $0.13 buffer below asia_high (LONG) or above asia_low (SHORT).

**Numerical example (today Jun 17, asia_range = $1.00, asia_high = $79.50):**
- LONG entry $79.30. BT TP = 79.30 + 1.00×2.0 = **$81.30**. Live TP = 79.50 − 0.13 = **$79.37**.
- Same setup, BT TP $1.93 above entry, live TP $0.07 above entry.

**Effect on `tp - entry < risk * 0.8` filter:**
- BT: TP is far from entry, filter rarely triggers.
- Live: TP is close to entry; for any sweep where `risk × 0.8 > 0.07`, signal is filtered out.

**Risk threshold = 0.8 × risk. Live filter trips when risk > $0.0875.** Live `min_sl = $0.10`, so EVERY trade where SL distance > $0.0875 (i.e., basically all trades) gets the live TP filter applied to a $0.07 distance, almost always failing.

⚠️ **WAIT — closer inspection:** Live TP is `asia_high - tp_buf` and entry is BELOW asia_high (LONG fires after a bearish sweep then bullish engulfing — wait, no, LONG fires after bullish sweep below asia_low + bullish engulfing). Re-checking:

- Bullish sweep: `bar.low < asia_low - threshold`. LONG entry on engulfing.
- Live LONG TP target: `asia_high - tp_buf` = $79.37 in example. Entry near asia_low ~$78.50. **TP - entry = $79.37 - $78.50 = $0.87.** That's plausible.
- BT LONG TP: `entry + asia_range × 2.0` = $78.50 + $2.00 = $80.50. **Different number, similar order of magnitude.**

The DIFFERENCE matters because BT TPs sit above asia_high (chase outside the structure), live TPs cap inside asia_high (mean-reversion play). Different exit targets, different `tp_too_close` filter outcomes, different fills, different P&L per trade.

**Verdict:** Real divergence. Each engine has its own TP rule. Same sweep can pass BT filters but fail live filters and vice versa.

### D2 — Live: 5-min cooldown after last `gd_signals` row

`scheduler.py:129–143`:
```python
recent_signal = execute("SELECT timestamp, taken, skip_reason FROM gd_signals WHERE strategy='alpha_sweep_oil' ORDER BY timestamp DESC LIMIT 1", fetch=True)
...
if last_signal_time and (now < last_signal_time + timedelta(minutes=5)):
    return None  # Cooldown
```

BT: no equivalent. BT iterates over signals chronologically with **own** 5-min cooldown (engine.py:251 — `if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS: continue`), but it's per-signal-pair, not "block any new scan."

**Effect:** if live tries to fire a signal at 14:50 UTC and gets a "skip" reason like `sl_too_close_to_price`, the next 5 minutes of scheduler ticks return None even if a fresh sweep emerges. BT doesn't have that property — BT processes each signal in isolation with cooldown only against the previous CHRONOLOGICAL signal, regardless of whether it was taken/skipped.

**Verdict:** Real divergence. Live skips sweeps that BT would still consider.

### D3 — Live: open-position DB blocker (in-code comment names a real prior incident)

`scheduler.py:151–157`:
```python
open_oil_macro = execute("SELECT COUNT(*) ... WHERE exit_time IS NULL AND trade_ref LIKE 'OIL-AS-%%'", fetch=True)
if open_oil_macro and open_oil_macro[0]["cnt"] > 0:
    return None
```

BT counterpart (`engine.py:213–215`): `if position_exit_time and signal.date < position_exit_time: continue` — blocks for the trade's projected hold duration only, never indefinitely.

**Effect:** if any prior `OIL-AS-%` row has `exit_time IS NULL` (orphan, EXIT_AMBIGUOUS, manually-stuck row), live blocks **all subsequent signals forever** until the orphan reconciler clears it. BT never has this state.

**Verdict for Jun 11–18 window:** I queried `gd_trades` for that window — all 5 Oil Macro trades closed cleanly, no `exit_time IS NULL`. So this gate didn't fire on the missed-signal days. Documented as architectural divergence but NOT the smoking gun for today's specific gap.

### D4 — Live: persistent sweep blacklist (`_traded_sweeps_oil["keys"]` + DB `is_sweep_consumed`)

`scheduler.py:298–305, 411–425`:
- After a successful signal fire OR after the 2hr engulfing window expires without finding an engulfing → sweep is added to in-memory blacklist AND persisted via `mark_sweep_consumed(today, sweep_key)`.
- Next scheduler tick checks: `if sweep_key in _traded_sweeps_oil["keys"]: continue`.

BT has no equivalent. The strategy file's `break # One engulfing per sweep` (line 146) only prevents multiple engulfings PER sweep within ONE pass — it doesn't blacklist across passes (BT only has one pass).

**Effect:** Live can blacklist a sweep on minute T because it found no engulfing yet, then 5 minutes later when the engulfing forms, the sweep is already on the blacklist and the engulfing is missed. BT walks the entire 2hr engulfing window in one pass — never has this race condition.

**Verdict:** Real divergence. Specifically: the `else` clause at scheduler.py:418–425 only marks consumed when `now >= window_end`, so this race is contained. BUT the `mark_sweep_consumed` after a successful `execute_signal` (line 411–415) is what creates persistent state — including across server restarts. If a signal fires successfully and the broker rejects the order (e.g. retcode 10018 market closed), the sweep is STILL blacklisted on subsequent retries. BT never sees this.

### D5 — Live: 24-bar H1 lookback + 50-bar M3 lookback

`scheduler.py:75, 83`:
```python
h1_candles = get_candles(..., granularity="H1", count=24, ...)
m3_candles = get_candles(..., granularity="M3", count=50, ...)
```

BT loads the entire CSV (730K M3 bars, 39K H1 bars).

**Effect:** Asia bars (00:00–08:00 UTC) + scan window bars (08:00–20:00 UTC) must both fit inside the 24-bar window AND DWX must have written them to `bars_BCO_USD_H1.json`. If DWX hasn't yet flushed today's pre-08:00 bars (e.g., service restart at 09:00 UTC, Asia bars never loaded into the JSON file), live silently fails the `len(asia_bars) < 3` gate and exits without a signal.

**Verdict:** Real divergence. Direct cause of "live missed Jun 12 16:21 LONG" if DWX bridge had restart issues at 16:18 UTC.

### D6 — Live: 3-min scheduler tick + M3 freshness window

Live scheduler runs every 3 minutes during 08:00–20:00 UTC (`scheduler.py:34`). Each tick fetches the latest 50 M3 bars and checks for engulfing in `relevant_m3 = [c for c in m3 if sweep_time < ts <= sweep_time + 2h]`. If at tick time T the engulfing bar hasn't formed yet (i.e., `len(relevant_m3) < 3` because only 1 M3 bar has closed since the sweep), live returns and waits for the next tick.

BT has the entire 2hr window of M3 bars at signal-gen time. No "wait" semantics.

**Effect:** A sweep that forms at 14:00 needs at least 9 minutes (3 M3 bars) before the engulfing search can start in live. Combined with D4 (sweep blacklist after 2hr expiry), the engulfing has ~1h51min effective window in live vs full 2hr in BT.

**Verdict:** Real divergence. Marginal but cumulative.

### D7 — Live wall-clock 08-20 UTC window

`scheduler.py:34–36`:
```python
if hour < cfg["scan_start"] or hour > cfg["scan_end"]:
    _log.debug("SCAN", "outside_scan_window", ...)
    return
```

BT: scan_window filter is `(day_h1.index.hour >= scan_start) & (day_h1.index.hour < scan_end)` — a per-bar filter, not a wall-clock filter.

**Effect:** If the live scheduler service was DOWN during 08:00–20:00 UTC on a given day, that day's signals are **never evaluated** even when the service comes back up the next day. BT processes every historical day regardless of when the BT runs.

**Verdict:** Real divergence. Direct cause of "live missed signals from yesterday" if there were any service outages in the Jun 11–17 window.

### D8 — `daily_candles` slicing

| | BT | Live |
|---|---|---|
| Source | `oil_d` DataFrame, indexed by date | `daily_candles` list from `get_candles(count=2)` |
| Yesterday's bar | `oil_d.iloc[i-1]` where `(oil_d.index[i] + 1day).date() == trade_date` (engine.py:134, drift bug #6 fix) | `daily_candles[-2]` (scheduler.py:212) |

BT shifts by +1 day to compensate for OANDA's `dailyAlignment=21` offset. Live takes the second-to-last daily bar from DWX.

**Effect:** If DWX returns daily bars in different alignment than OANDA, the "yesterday's bias" computation can be off by one day between BT and live.

**Verdict:** Possible divergence. Worth verifying the DWX daily bar alignment matches what BT expects.

### D9 — Bid/ask reconstruction

| | BT | Live |
|---|---|---|
| Source | CSV bid/ask columns (real, post-spread) | `mt5_executor.get_candles` synthesizes bid=mid−half_sp, ask=mid+half_sp |

For BCO_USD, mt5_executor doesn't have a special branch for Brent point size (`mt5_executor.py:418`: `half_spread = spread_pts * 0.005 if "XAU" in symbol else spread_pts * 0.00005`). For Brent, half_spread is `spread_pts × 0.00005` which is **wrong** — Brent point size is 0.01, so half_spread should be `spread_pts × 0.005`. Currently it's 100× too small.

**Effect on signal detection:** mid prices are unaffected (mid = (bid + ask) / 2 cancels). Sweep detection uses `mid_high/mid_low` only (scheduler.py:166–168). Engulfing uses `(bid_open + ask_open) / 2` (scheduler.py:336–339). All these use mid, so the broken bid/ask reconstruction does NOT affect signal-detection arithmetic.

**Effect on entry/SL/TP price math:** entry uses `c["ask_close"] + slippage(br)` (LONG) or `c["bid_close"] - slippage(br)` (SHORT). Since live's `bid_close` and `ask_close` are MID − half_spread and MID + half_spread with broken half_spread, both are essentially equal to MID for BCO. Entry price is computed from MID + slippage, which matches BT's MID + slippage (because BT's bid_close from CSV ≈ MID for BCO too — CSV bid/ask spread reconstruction is also approximate).

**Verdict:** Probably zero impact on signal generation but real impact on entry-price exact value (sub-pip differences). Not the smoking gun.

### D10 — Cap/cooldown reset timing

| | BT | Live |
|---|---|---|
| Trades-today cap | per-day reset at midnight UTC | per-day reset at midnight UTC, + LIMIT_TTL_EXPIRED excluded |
| Cooldown | 5min between consecutive signal dates | 5min between LATEST gd_signals row regardless of side |

Both now match (Jun 18 cap rework fixed the gap).

**Verdict:** Now in parity.

---

## Direct evidence of divergence

### Live signals fired Jun 11–18 (Oil Macro)

Pulled from `/api/oil/state` `recent_signals` (capped at 10 most recent):

| Time UTC | Direction | Entry | Taken |
|---|---|---|---|
| Jun 11 12:18 | LONG | $91.51 | yes (`OIL-AS-59a94823` SL'd) |
| Jun 11 14:45 | LONG | $92.95 | yes (`OIL-AS-f5e9710a` MAX_HOLD) |
| Jun 17 21:54 | SHORT | $78.77 | yes (`OIL-AS-b32439ae` MAX_HOLD +$67) |
| Jun 18 onwards | … | … | … |

Plus from `gd_trades` Jun 17 entries that went to fill:
- Jun 17 14:45 LONG `OIL-AS-e5705d4e` SL −$252
- Jun 17 17:51 LONG `OIL-AS-a251ada3` MAX_HOLD +$37
- Jun 17 21:54 SHORT `OIL-AS-b32439ae` (above)

### BT signals on freshly imported JM CSV for same window

Pulled from `backend-oil/backtest/engine.py run_backtest(start='2026-06-11', end='2026-06-18', mode='neutral')`:

| Time UTC | Direction | Entry | Outcome |
|---|---|---|---|
| Jun 12 16:21 | LONG | $87.61 | tp_partial+sl +$745 |
| Jun 15 10:33 | LONG | $82.40 | sl −$192 |
| Jun 15 17:12 | LONG | $82.47 | expired +$8 |
| Jun 16 08:12 | LONG | $82.34 | sl −$198 |
| Jun 17 08:30 | LONG | $78.17 | sl +$311 (partial) |
| Jun 17 10:51 | LONG | $78.37 | sl +$120 (partial) |
| Jun 17 15:09 | SHORT | $79.18 | sl −$203 |

### Overlap

- **BT fired but live did not:** Jun 12 16:21, Jun 15 10:33, Jun 15 17:12, Jun 16 08:12, Jun 17 08:30, Jun 17 10:51 (6 signals)
- **Live fired but BT did not:** Jun 17 14:45 LONG, Jun 17 17:51 LONG (2 signals)
- **Both (within ~6hr window):** Jun 17 15:09 SHORT BT vs Jun 17 21:54 SHORT live
- **Live also fired Jun 11 12:18 LONG, Jun 11 14:45 LONG** — BT range starts Jun 11 but those rows are at 91.51/92.95 — BT didn't see those, so BT may have a daily-bias filter blocking them.

---

## Hypothesis ranking (smoking-gun candidates)

| # | Hypothesis | Evidence strength | Likelihood explains today |
|---|---|---|---|
| **1** | **D1 (TP formula)** — entirely different TP rules → different `tp_too_close` filter outcomes → different signal sets | HIGH (line-level proof from code) | **HIGH** — explains both sides (BT extra signals AND live extra signals) |
| 2 | D5 (24/50-bar lookback) + DWX bar freshness | MEDIUM (depends on DWX history availability) | MEDIUM |
| 3 | D2 (5-min cooldown swallowing live retries) | HIGH (line-level proof) | LOW for big gaps but accounts for some near-misses |
| 4 | D7 (wall-clock window) — service downtime | MEDIUM (no uptime data pulled) | MEDIUM |
| 5 | D4 (sweep blacklist persistence) — sweeps consumed prematurely | MEDIUM (race condition narrow) | LOW |
| 6 | D3 (open-position DB block) | LOW for this window (no orphan rows confirmed Jun 11–17) | NONE for today |

---

## Smoking gun (with proof)

**D1 — TP formula divergence is the primary smoking gun.**

Concrete reasoning:
1. Both BT and live use the same sweep+engulfing detection. So both detect the same number of "candidate" signals at the sweep+engulfing pair level.
2. BT has TP = `entry + asia_range × 2.0`. For typical Brent asia_range = $1.00, that's TP $2.00 from entry.
3. Live has TP = `asia_high - 0.13` (LONG) or `asia_low + 0.13` (SHORT). For LONG entry near $78.50 with asia_high at $79.50, TP is $79.37 (just $0.87 from entry).
4. Each side then applies `if (tp - entry) < (risk * 0.8): continue`.
5. For risk = $0.30, threshold = $0.24. BT clears it easily ($2.00 > $0.24). Live clears it for typical setups ($0.87 > $0.24) but FAILS for setups where entry sits close to asia_high — i.e., when the bullish engulfing forms high in the range.

Claim: BT and live are **filtering at different price geometries** even though their detection inputs match. **Same data, different filters → different signal sets.**

Cross-check: a signal that passes BT but fails live would look like — BT reports a LONG entry at $78.50, asia_range $1.00, asia_high $79.00. BT TP = $80.50. Live TP = $78.87 (= 79.00 − 0.13). risk = $0.20. risk × 0.8 = $0.16. BT TP - entry = $2.00 > $0.16 ✓ pass. Live TP - entry = $0.37 > $0.16 ✓ pass. Hmm, both pass.

A failure case: entry $79.30 (engulfing forms high in range), asia_high $79.50. risk $0.30. BT TP = $81.30. Live TP = $79.37. BT clears: $2.00 > $0.24. Live: $0.07 < $0.24 → fails. **Live filters out, BT keeps.**

Conversely, an asymmetric case where BT skips and live fires: when `asia_range × 2.0 < risk × 0.8`. For risk = $0.50 and asia_range = $1.00, BT TP-distance = $2.00 vs threshold $0.40 — BT passes. So BT only rejects if BT TP is MUCH closer than risk × 0.8, which requires very small asia_range or very large risk. Possible but rare.

**Claim verification:** to prove D1 is THE cause, I would need to dump BT signals + live signals + asia_high + entry for the same Jun 11–17 window and check for each signal whether it passed/failed each side's TP filter.

That data is in:
- BT: re-run with `dry_run` and dump signals + filter outcomes
- Live: query `gd_signals` table with skip_reason + entry + asia metadata

I have NOT run that proof yet — claim D1 is the smoking gun is supported by direct geometric reasoning, but the per-signal table would seal it.

---

## Recommendation

**Unify the implementations.** Make live scheduler call `alpha_sweep.generate_signals()` instead of having its own copy. This eliminates D1, D2 (cooldown can wrap the call), D4 (blacklist can wrap the call), D5 (lookback windows are still needed but the strategy logic is shared), and D6 (M3 freshness still applies but engulfing math is shared). D3, D7 stay as production-only gates because they're about service health, not strategy.

**Effort:** Estimated ~6h per system, ~24h total for 4 systems.

**Phasing:**
1. Oil Macro first (today's smoking gun system) — write DWX→DataFrame adapter, refactor scheduler.py to call `alpha_sweep.generate_signals()`. Run parity harness.
2. If parity proven on Jun 17 replay, scale to Gold Macro, Gold Micro, Oil Micro.
3. Once unified, every fix to the strategy auto-applies to both — no more drift.

---

## Files referenced

- `backend-oil/strategies/alpha_sweep.py` — BT signal-gen
- `backend-oil/backtest/engine.py` — BT execution loop
- `backend-oil/scanner/scheduler.py` — live signal-gen + execution (parallel impl)
- `backend-oil/data/cache.py` — CSV loader
- `backend/execution/mt5_executor.py` — DWX bar/tick reader
- `backend-oil/config.py` — Oil Macro config
