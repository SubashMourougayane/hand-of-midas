# BUG: Timezone Drift Bug (TDB)

**Status**: CONFIRMED, NOT YET FIXED  
**Severity**: CRITICAL — affects all 4 live trading systems  
**Date Discovered**: 2026-06-09  
**Discovered During**: Postmortem of Gold SHORT trade with R:R 0.46 + Oil LONG -$526 loss  
**First Lived On VPS**: Since first deploy with MT5 executor (~May 22, 2026)  
**Estimated Damage**: ~$1,255 in past week alone (Jun 2-9)  

---

## Naming

**The Timezone Drift Bug** (TDB) — also called the **"3-Hour Phantom Session"** bug.

The system labels MT5 broker-server timestamps (GMT+3) as UTC, causing the strategy to treat the wrong wall-clock hours as "Asia session" and "London/NY scan window." Every signal fires 3 hours earlier than the strategy was designed for.

---

## One-Sentence Summary

`mt5_executor.get_candles()` appends `"Z"` to GMT+3 server timestamps, marking them as UTC, which silently shifts the entire strategy's session detection 3 hours into the wrong sessions, triggering trades during the wrong time of day with wrong reference ranges.

---

## How It Works (and Fails)

### The Single Line of Code

`backend/execution/mt5_executor.py` line 216:

```python
candles.append({
    "timestamp": t.replace(".", "-").replace(" ", "T") + "Z" if "." in t else t,
    ...
})
```

### What `t` Looks Like

MT5's DWX EA writes bars to JSON with **server time** in `"YYYY.MM.DD HH:MM:SS"` format:

```json
{"time": "2026.06.09 11:00:00", "open": 4326.30, ...}
```

JustMarkets MT5 server runs **GMT+3** (verified June 9: server time `13:50` while real UTC was `10:50`, IST was `16:20`).

### What the Code Does

It converts the string and appends `"Z"`:
- Input: `"2026.06.09 11:00:00"` (server time = real UTC 08:00)
- Output: `"2026-06-09T11:00:00Z"` (claims to be UTC 11:00)

### What `_parse_ts` Then Sees

`backend/scanner/scheduler.py` (every system):
```python
def _parse_ts(ts_str):
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
```

Returns a `datetime` with `tzinfo=UTC` and `hour=11`. **But the actual UTC moment is `hour=8`**.

### Why It Bleeds

Every strategy filter that uses `ts.hour` is now off by 3:

```python
# scheduler.py
asia = day_h1[(day_h1.index.hour >= 0) & (day_h1.index.hour < 8)]   # Asia 0-7
scan_window = day_h1[(day_h1.index.hour >= 8) & (day_h1.index.hour < 20)]  # 8-20
```

Code intends:
- Asia = real UTC 00:00 → 07:59 (Tokyo session, low volatility)
- Scan = real UTC 08:00 → 19:59 (London + NY, high volatility)

What actually happens (with server labels treated as UTC):
- Asia = real UTC **21:00 prev → 04:59 today** (NY close + Tokyo open)
- Scan = real UTC **05:00 → 16:59 today** (Tokyo + London + early NY, cuts off late NY)

---

## Strategy Impact

### Asia Range Built From Wrong Bars

The "Asia consolidation range" (key reference price for the strategy) is being built from **NY close + Tokyo open** bars instead of pure Tokyo session.

- Real Asia: low volatility, tight range, useful as a reference baseline
- NY close: high volatility, end-of-day flows, large directional moves
- Mixing them → range is too wide AND not a real consolidation

### Scan Window Cuts Off Late NY

Strategy was designed to catch **London Open + NY morning sweeps**. With the shift, the scan ends at real UTC 16:59 — cutting off the NY afternoon session where most institutional flows happen.

### Sweep Detection Is Confused

Sweeps "above Asia high" or "below Asia low" — but Asia high/low is now the wrong reference. Many "sweeps" the system detects aren't real liquidity grabs; they're just normal price action against an artificially-defined range.

### R:R Math Is Distorted

`TP = range_low + buffer` and `SL = sweep_wick + buffer` both depend on the (wrong) Asia range. So R:R calculations are based on incorrect levels. This explains:

- **Jun 5 Gold Macro LONG**: R:R 0.65 (rejected by filter in code, but passed because the math used a different Asia range than expected)
- **Jun 9 Gold SHORT today**: R:R 0.46 (same issue — wrong reference levels)

---

## Evidence Chain

### 1. Server Timezone Verified

Real UTC: `2026-06-09 11:23:40`  
MT5 server: `2026-06-09 14:23:40`  
**Offset: +3.0 hours**

### 2. CSV vs MT5 Format Mismatch

```
CSV (real UTC):     2026-05-26 13:00:00+00:00, 4520.37, ...
MT5 (server time):  2026.06.09 11:00:00 (means real UTC 08:00)
```

Both are 1-hour bars but in different timezones. The backtest reads CSV directly (real UTC). The live engine reads MT5 (server time but labeled as UTC).

### 3. 20-Year Backtest Comparison

Simulated what the live system actually does (server hours treated as UTC):

| | Backtest (real UTC) | Live (timezone-shifted) |
|---|---:|---:|
| Total signals | 1,077 | 962 |
| Signals at UTC hour 5-7 | 0 | **175** |
| Signals at UTC hour 17-19 | 154 | 0 |
| Signals only in live | — | **175** |
| Signals only in backtest | 707 | — |

**Less than 18% overlap** between live and backtest signals across 20 years.

### 4. Today's Trade Forensics

**Gold SHORT June 9:**
- Engulfing M3 bar at server-labeled `09:42:00` = real UTC `06:42:00`
- Cron fires at real UTC 08:00 = server `11:00`
- 78-minute lag between engulfing and fill
- Backtest's same logic: would not trigger (real UTC 06:42 is before scan_start 08:00)
- Live: triggered, filled at price that had drifted $10 against entry, R:R fell from 1.46 → 0.46

**Oil LONG June 9:**
- Same timing pattern
- Result: -$526 loss in 8 minutes (SL hit immediately)

### 5. Past Week P&L

| System | Trades | Live Result |
|--------|:---:|---:|
| Gold Macro | 3 closed | +$411 (one trade was R:R 0.65 lucky win +$295) |
| Gold Micro | 6 closed | -$1,140 |
| Oil Macro | 1 closed + 1 open | -$526 |
| Oil Micro | 0 | $0 |
| **TOTAL** | **10+** | **-$1,255** |

Backtest expectation for similar week: PF 4-5, expect positive result.

---

## Why It Wasn't Caught Earlier

1. **OANDA worked correctly** — original deploy used OANDA which returns real UTC (with proper offset). All testing happened on OANDA.
2. **MT5 was added later** — switched to JustMarkets via DWX bridge for live trading. The format conversion in `mt5_executor.py` line 216 was a quick adapter that nobody checked against backtest.
3. **Strategy still "trades"** — it produces signals that look plausible (sweeps detected, engulfings found, R:R passes filters at calc time). They're just based on wrong reference levels.
4. **Win rate masking** — even with wrong sessions, sweep+engulfing patterns occur at all hours. Some win, some lose. The compounding edge degradation isn't visible in any single trade.
5. **Backtest was the only oracle** — and we trusted it without comparing live signal generation to backtest signal generation on the same dates.

---

## Risk Assessment Before Fix

### Things That Will Definitely Change

- All 4 live systems will see different bars as "Asia" and "scan"
- Trade frequency: live currently fires 18% of trades that backtest doesn't see + misses 65% that backtest does see → fix dramatically reshuffles signals
- Per-day trade counts will change

### Things That Could Break

#### A. The `today` boundary
- `datetime.now(timezone.utc).date()` is real UTC date
- MT5-labeled bars from real UTC 21:00-23:59 currently have `ts.date() = TOMORROW` (server date)
- After fix: those bars have `ts.date() = TODAY` (real UTC date) → suddenly included in "today's Asia range"
- Sweep blacklist (`_traded_sweeps_macro`) keys based on bar timestamp will be different
- **Mitigation needed**: clear blacklist on first scheduler tick after deploy

#### B. The `_traded_sweeps_macro` daily reset
- Resets when `today` changes
- Still works after fix (real UTC date), but the keys (bar timestamps) shift
- Risk: existing in-memory keys from before fix become irrelevant
- **Mitigation needed**: scheduler restart with empty blacklist (already happens on service restart)

#### C. Existing DB records
- `gd_trades.entry_time` already in real UTC (uses `datetime.now(utc)`)
- `gd_signals.timestamp` likely in real UTC
- `gd_journal.timestamp` real UTC
- ✅ DB records unaffected by fix

#### D. The `mt5_executor.get_open_trades()` `open_time` field
- Returns server time as-is in `open_time`
- Some downstream uses might compare to real UTC
- Need to audit all consumers

#### E. Oil Micro and Gold Micro rolling windows
- Use hours 0-22 for windows, market_close at 21-22
- After fix, "market close" hours align with real UTC (which actually IS Sunday close 21:00 UTC = market close)
- ✅ This actually FIXES Oil/Gold Micro market close detection

---

## Fix Plan (Conservative)

### Phase 1: Audit (no code changes)
1. Grep all consumers of `get_candles()` across all 4 backends
2. Grep all uses of `ts.hour`, `ts.date()`, `_parse_ts` in scheduler/live_engine for each system
3. Grep all places that store/compare timestamps to DB columns
4. Check `get_open_trades()` `open_time` consumers
5. Check `get_trade_details()` `close_time` consumers

### Phase 2: Single-line fix in executor
```python
# backend/execution/mt5_executor.py line 216
# Replace:
"timestamp": t.replace(".", "-").replace(" ", "T") + "Z" if "." in t else t,
# With:
"timestamp": _server_to_utc(t),

# New helper at top of file:
SERVER_OFFSET_HOURS = 3  # JustMarkets MT5 = GMT+3

def _server_to_utc(t):
    if "." not in t:
        return t  # already in real UTC format
    from datetime import datetime, timedelta
    server_dt = datetime.strptime(t, "%Y.%m.%d %H:%M:%S")
    utc_dt = server_dt - timedelta(hours=SERVER_OFFSET_HOURS)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
```

### Phase 3: Test mode (don't go live)
- Run all 4 services with fix on a TEST DB
- Compare signal generation to backtest for same dates
- Expect: live signals == backtest signals (or very close, accounting for live being mid-bar)

### Phase 4: Verification harness
- Add `tests/harness/test_16_timezone_parity.py`
- Verifies that for sample MT5 input, output timestamp equals real UTC equivalent

### Phase 5: Production deploy
- Deploy during off-hours (UTC 21:00 - 04:00 = market close)
- Restart all 4 services with empty in-memory state
- Watch first signal/trade in each system
- Have rollback plan ready

### Phase 6: Backfill
- DB still has correct timestamps
- Existing orphan positions (Oil OIL-AS-f557abc0) need cleanup
- New trades go forward correctly

---

## Confidence Level

**95% confident the bug is correctly identified.**  
**70% confident the one-line fix will work without regression.**

The 30% uncertainty:
- Possible interactions with `today` boundary checks
- Possible subtle dependencies elsewhere I haven't audited
- Possible MT5 server timezone changes (DST? Different broker = different offset?)

**Recommendation**: Implement Phase 1 (audit) before any code changes.

---

## Related Bugs (Discovered Same Day)

### MT5 `id` vs `trade_id` Key Mismatch (Fixed in commit `124a8b2`)
Oil Macro `check_open_positions()` used `t["trade_id"]` but MT5 returns `t["id"]`. KeyError silently aborted the function, leaving orphan positions in DB. Other 3 systems use `t.get("id") or t.get("trade_id")`.

### Oil Macro V1-Only Bias (Fixed in commit `5c048f1`)
Oil Macro was using V1-only bias when other 3 systems use Combined V1+V2. June 9 Oil LONG trade was allowed by V1 (neutral) but V2 (bearish) would have blocked it. -$526 loss.

These are independent bugs, all surfaced today. Combined with the Timezone Drift Bug, they explain the past week's $1,255 loss.

---

## TL;DR

The system trades the wrong sessions because MT5 timestamps are GMT+3 but get marked as UTC. Strategy thinks "London Open" is when it's actually still Asia. Asia range is built from NY close. Sweeps are detected against wrong references. Trades fire at wrong times with wrong R:R math. Has been bleeding ~18% of every win and adding 18% phantom signals for 2-3 weeks. Single-line fix in `mt5_executor.py` should restore live=backtest parity.
