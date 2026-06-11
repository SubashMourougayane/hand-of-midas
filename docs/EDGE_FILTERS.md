# EDGE_FILTERS — Strategy & Execution Enhancement Plan

**Status:** Draft / pre-backtest
**Created:** 2026-06-11
**Surfaced by:** Live trade `GD-MI-14e2fed1` (2026-06-11), peaked at +$256 then drifted, illustrating the "late secondary sweep" pattern
**Owner:** Subash
**Prerequisite for shipping:** [Parity Verification Harness](#prerequisite-parity-verification-harness)

---

## Why this exists

Alpha-Sweep (Macro and Micro variants) takes setups that pass all 5 entry gates: bias match, sweep direction, engulfing close, window state, no DD pause. Most of these are profitable in aggregate (PF 3.5+ in backtest). But **a meaningful fraction are structurally low-edge** — technically valid but economically late or in a regime where the move has already exhausted.

Today's trade `GD-MI-14e2fed1` is a clean illustration:

- **Sweep #1** at 01:30 UTC: bearish wick to $4118, drove price to $4060 (-$58, the day's main move)
- **Sweep #2** at 08:00 UTC: bearish wick to $4112.62, with only $32 of TP distance remaining
- Strategy entered Sweep #2 → late entry into trending market that had already used most of its daily range
- Trade peaked at +$256 unrealized, then drifted back toward entry

Visually this looks like a "late" entry. Mathematically the issue is sharper: **the strategy doesn't measure how much expected daily range remains before taking a sweep.** Setups that fire after most of the day's directional energy is spent have lower expectancy than setups that fire fresh.

EDGE_FILTERS is the umbrella name for **9+ ideas that filter or refine these low-edge setups before they enter live.** Filters #1-#4 are signal-generation gates (skip the trade), #5-#7 are execution refinements (change how the trade is managed once entered), #8 is an entry-pattern quality filter (engulfing close-strength, surfaced live by user observation 2026-06-11), and #9 is an R:R upper-bound gate (surfaced from R:R-distribution analysis on the 2026-06-11 stuck trade).

The goal is **not to take more trades** — it's to take fewer, better trades and squeeze more from each.

---

## Naming convention

- Code identifier: `edge_filters` / `EDGE_FILTERS`
- Config key: `EDGE_FILTERS = { "range_exhaustion_enabled": True, ... }`
- Journal event names: `EDGE_FILTER_SKIP`, `EDGE_FILTER_RANGE_EXHAUSTED`, etc.
- Telegram tag: `[EDGE_FILTER]` prefix on skip notifications (so non-trades are still visible)

---

## The 9 enhancements (and growing — see [EDGE_FILTERS_IMPLEMENTATION.md](EDGE_FILTERS_IMPLEMENTATION.md) for the rollout plan)

Filters are numbered by priority (#1 highest expected impact, cheapest to test).

### #1 — Range Exhaustion Filter

**Idea:** Before taking a sweep entry, check how much of the typical daily range price has already covered today. If the day has already spent most of its energy, skip.

**Hypothesis:** Gold (and Oil) tend to make one decisive directional move per day during the active session. Sweeps within the same direction AFTER that move tend to be echoes — they pass entry gates but produce low-edge trades because there's little fuel left for TP.

**Code sketch:**
```python
# At entry time (after engulfing confirmation, before order placement)
today_high = get_today_high(symbol)  # rolling high since 00:00 UTC today
today_low = get_today_low(symbol)
daily_range_already = today_high - today_low

atr_20 = compute_atr(symbol, period=20, timeframe="D")  # 20-day ATR
exhaustion_pct = daily_range_already / atr_20

if exhaustion_pct > EDGE_FILTERS["range_exhaustion_threshold"]:  # default 0.7
    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                taken=False, skip_reason="range_exhausted")
    _log_journal(trade_ref, strategy, "EDGE_FILTER_SKIP", entry_price, {
        "filter": "range_exhaustion",
        "exhaustion_pct": exhaustion_pct,
        "today_range": daily_range_already,
        "atr_20": atr_20,
    })
    notify.signal_skipped(symbol, strategy, direction,
                         f"range_exhausted ({exhaustion_pct:.0%} of ATR_20)")
    return None
```

**Parameters to backtest:**
- `range_exhaustion_threshold` — try 0.6, 0.7, 0.8, 0.9
- ATR window — try 20, 14, 10 days
- Daily-high/low source — calendar day vs trading session

**Expected effect on backtest:**
- Total trades: -15% to -30% (estimate; needs validation)
- PF: +20% to +50% (best case if hypothesis holds)
- Average winner P&L: similar (we keep the high-edge winners)
- Average loser P&L: smaller (we skip the late, low-edge stalls)
- Win rate: +5 to +10pp

**Backtest cost:** ~30 min to add to scanner, ~3 hours to run replay over 1 year of data and compare metrics. **Cheapest big-impact filter.**

**Dependencies:**
- ATR computation (may already exist; needs verification in `backend-micro/scanner/scheduler.py`)
- Per-symbol daily high/low tracking

**Rollout risk:** Low. Pure additive filter — if disabled (`range_exhaustion_enabled: False`), system behaves identically to today.

**Today's trade applied:** Daily range was ~$58 ($4118 → $4060) when our entry fired at $4097. ATR_20 for Gold M3 ≈ $80. Exhaustion = 72%. **Filter at threshold 0.7 would have skipped.**

---

### #2 — First-Sweep-of-Day Filter

**Idea:** Track sweeps that have already been TAKEN today, per direction. Skip the second same-direction sweep.

**Hypothesis:** The first sweep of a direction captures the bulk of the move. Subsequent same-direction sweeps are echoes — same edge problem as #1 but seen through a different lens. This is a simpler, deterministic version of #1.

**Code sketch:**
```python
# Module-level state, reset at 00:00 UTC daily (or per session)
_taken_sweeps_today = {"bullish": False, "bearish": False}

# At entry time
if _taken_sweeps_today.get(sweep_dir, False):
    if EDGE_FILTERS["first_sweep_only_enabled"]:
        _log_signal(..., taken=False, skip_reason="second_same_direction_sweep")
        return None

# After successful entry (in execute_signal):
_taken_sweeps_today[sweep_dir] = True
```

**Parameters to backtest:**
- Reset cadence: 00:00 UTC daily / 23:00 UTC session start / weekly
- Direction granularity: per-direction (current sketch) vs any-direction
- Whether to gate on TAKEN trades only or ALL detected sweeps

**Expected effect:**
- Total trades: -10% to -20% (smaller cut than #1; more conservative)
- PF: +10% to +30%
- Net P&L: positive (kept winners are better; lost echoes were marginal)

**Backtest cost:** Low. ~30 min to add tracking, ~2 hours to validate.

**Dependencies:** None new.

**Rollout risk:** Low.

**Subtle interaction with #1:** Filters #1 and #2 overlap heavily. If both enabled, #1 likely catches everything #2 would. **Test #1 alone first**, only ship #2 if #1 doesn't already cover the cases. May make #2 obsolete.

**Today's trade applied:** No prior bearish sweep had been taken today (the 16-20 window's bullish sweep was bias-filtered, not taken). So this filter alone wouldn't have skipped today's trade. **#1 is the better fit for today's pattern.**

---

### #3 — TP Feasibility Check

**Idea:** At entry time, calculate whether TP is reachable in the time remaining before MAX_HOLD or the high-volume session ends, given current ATR pace.

**Hypothesis:** Trades that need 4 hours of average movement to reach TP, but only have 2 hours of session left, are statistically unlikely to TP. They'll either MAX_HOLD timeout, drift back to entry, or scratch.

**Code sketch:**
```python
def _tp_feasible(entry_price, tp_price, side, current_utc_time, atr_h):
    """Estimate whether TP is reachable in the time we have."""
    required_distance = abs(tp_price - entry_price)

    # Effective session-end: NY close (21:00 UTC) or MAX_HOLD bars elapsed
    minutes_to_max_hold = MAX_BARS * 3  # M3 bars × 3 min
    minutes_to_session_close = (21 - current_utc_time.hour) * 60
    effective_minutes_remaining = min(minutes_to_max_hold, minutes_to_session_close)

    # Expected distance based on ATR_H (H1 ATR)
    expected_distance = (effective_minutes_remaining / 60) * atr_h

    # Apply directional bias factor (0.7 = need 70% of expected to be confident)
    return expected_distance >= required_distance * EDGE_FILTERS["tp_feasibility_factor"]

# At entry time
if not _tp_feasible(entry_price, tp_price, side, datetime.utcnow(), atr_h):
    _log_signal(..., taken=False, skip_reason="tp_not_feasible_in_session_time")
    return None
```

**Parameters to backtest:**
- `tp_feasibility_factor` — 0.5, 0.7, 0.9, 1.0
- ATR timeframe — H1 (current sketch), M15, mixed
- Session-close hour — 21 UTC default, configurable per symbol

**Expected effect:**
- Total trades: -5% to -15% (catches a smaller subset)
- PF: +10% to +20%
- Particular help: late-day signals where TP was structurally unreachable

**Backtest cost:** Medium. Needs ATR_H (may not exist on M3 stack), session-close per symbol. ~1 hour to code, ~3 hours to validate.

**Dependencies:**
- H1 ATR computation
- Per-symbol session close (Gold = 21 UTC, Oil = different)

**Rollout risk:** Medium. ATR errors compound; faulty ATR could over-filter.

**Today's trade applied:** Entry at 08:30 UTC. Session-close (21 UTC) = ~12.5 hours remaining. ATR_H for Gold is ~$3-5. Expected distance: 12.5 × $4 = $50. Required: $43. **Filter would NOT have skipped today** — too much session left. So this filter alone wouldn't address today's pattern; it's complementary to #1, not redundant.

---

### #4 — Anti-Second-Leg / Trend-Extension Filter

**Idea:** If price has already moved more than 2× ATR in the same direction over the last N hours, the next sweep in that direction is statistically a fade-trade, not a continuation. Skip.

**Hypothesis:** Markets mean-revert eventually. After a strong directional move, taking another entry in the same direction is paying full risk to ride the tail of an already-extended move. The expected value drops.

**Code sketch:**
```python
def _trend_extended(symbol, side, lookback_hours=4):
    """Check if recent price action has already moved 2× ATR in the
    same direction we're about to enter."""
    bars = get_candles(symbol, "M15", count=lookback_hours * 4)
    if not bars or len(bars) < 8:
        return False
    open_price = bars[0]["open"]
    close_price = bars[-1]["close"]
    move = close_price - open_price
    atr = compute_atr_from_bars(bars)

    if side == "SHORT" and move < -2.0 * atr:
        return True  # already extended downward, SHORT is late
    if side == "LONG" and move > 2.0 * atr:
        return True  # already extended upward, LONG is late
    return False

# At entry time
if _trend_extended(symbol, side):
    if EDGE_FILTERS["anti_trend_extension_enabled"]:
        _log_signal(..., taken=False, skip_reason="trend_already_extended")
        return None
```

**Parameters to backtest:**
- `lookback_hours` — 2, 4, 6
- ATR multiplier — 1.5×, 2.0×, 2.5×, 3.0×
- Timeframe — M15 vs H1

**Expected effect:**
- Total trades: -10% to -25%
- PF: +15% to +35%
- Heavy overlap with #1; possibly redundant if both ship

**Backtest cost:** Medium. ~1 hour to code, ~3 hours to validate. Backtest must measure overlap with #1.

**Dependencies:** ATR computation (shared with #1, #3).

**Rollout risk:** Low-medium.

**Today's trade applied:** Looking back 4 hours from 08:30 UTC entry → covers 04:30–08:30 UTC. In that window: $4118 (high) to $4097 (entry) = $21 down move. ATR M15 ≈ $5. Move = 4.2× ATR — strongly extended. **Filter at threshold 2.0× would have skipped.**

---

### #5 — Earlier BE Trigger (50% → 35%)

**Idea:** Currently BE arms when price moves 50% of the way to TP. Reduce to 35% so BE arms earlier, before late-stage stalls erode unrealized profit.

**Hypothesis:** Trades that reach 35% of TP have already proven directional commitment. The marginal gain from the next 15% (50% level) is small compared to the risk of a stall-and-reversal back to entry.

**Code sketch:**
```python
# In backend-micro/config.py:
MICRO_ALPHA_SWEEP = {
    ...
    "be_trigger_pct": 0.35,  # was 0.50
    ...
}
```

That's the entire change. (Identical line in `backend-oil-micro/config.py`, `backend/config.py`, `backend-oil/config.py` if applied to other systems.)

**Parameters to backtest:**
- `be_trigger_pct` — 0.30, 0.35, 0.40, 0.45, 0.50 (current)
- Per-system: same value or per-strategy?

**Expected effect:**
- More BE-stop scratches (trades that would have continued to TP after small pullback)
- Fewer net-negative-from-positive-territory trades (the today pattern)
- Net P&L: depends on the ratio — backtest will reveal

**Backtest cost:** Low. 1-line config change, ~2 hours to validate per system.

**Dependencies:** None.

**Rollout risk:** Medium. **Calibration change with non-obvious tradeoffs.** Don't ship without backtest.

**Today's trade applied:** With `be_trigger_pct: 0.35`:
- 35% of $4097.27 → $4054.26 = $4082.79
- Today's price touched $4082 at the intraday low
- **BE would have armed.** Trade would either TP or scratch. No SL exposure.

---

### #6 — Trailing SL After BE Arm

**Idea:** Once BE has armed (SL moved to entry), trail SL by 30-50% of favorable excursion as price continues toward TP. Locks in progressive gains instead of risking BE-bounce-to-entry.

**Hypothesis:** After BE arms, the trade is risk-free — but it can also stall and revert without ever giving meaningful profit. Trailing the SL converts unrealized profit into locked profit progressively.

**Code sketch:**
```python
# In check_alpha_sweep_breakeven (or new function check_alpha_sweep_trail)
def update_trailing_sl(trade, current_price, side):
    """After BE armed, trail SL by 50% of favorable excursion."""
    if not trade.get("be_armed"):
        return  # BE hasn't fired yet; no trailing

    entry = float(trade["entry_price"])
    sl = float(trade["sl_price"])
    favorable = (entry - current_price) if side == "SHORT" else (current_price - entry)
    if favorable <= 0:
        return  # No favorable excursion; SL stays at entry

    trail_distance = favorable * EDGE_FILTERS["trail_sl_factor"]  # default 0.5
    new_sl = (entry - trail_distance) if side == "SHORT" else (entry + trail_distance)

    # Only ratchet — never widen
    if (side == "SHORT" and new_sl < sl) or (side == "LONG" and new_sl > sl):
        modify_stop_loss(trade["oanda_trade_id"], new_sl)
        execute("UPDATE gd_trades SET sl_price=%s WHERE trade_ref=%s",
                (new_sl, trade["trade_ref"]))
        _log_journal(trade["trade_ref"], strategy, "TRAIL_SL_UPDATE", new_sl, {
            "old_sl": sl, "favorable_excursion": favorable, "trail_factor": trail_factor,
        })
```

**Parameters to backtest:**
- `trail_sl_factor` — 0.3, 0.5, 0.7
- Trigger condition: only after BE armed (sketch above) vs trail from entry

**Expected effect:**
- A subset of TP-runners now stop out as partial wins (slightly negative effect on max P&L)
- Many BE-bounce-to-scratch trades convert to small wins (positive effect)
- Net effect: depends heavily on Gold/Oil micro-structure

**Backtest cost:** Higher. Requires bar-level price tracking inside backtest engine for trailing. ~2 hours to code, ~5 hours to validate. **Most expensive of the calibration changes.**

**Dependencies:**
- BE-armed state must be persisted per trade (verify in `gd_trades` schema)
- Modify `modify_stop_loss` flow to handle frequent updates (rate-limit broker calls?)

**Rollout risk:** Medium-high. **Frequent SL modifications could trigger broker rate limits or fee implications.** Test in demo first.

**Today's trade applied:** With BE armed at $4082 (per #5) and trail factor 0.5:
- At $4082 (BE armed): SL = entry $4097.27
- At $4080: favorable = $2, trail = $1, new SL = $4096.27
- At $4075: favorable = $7, trail = $3.50, new SL = $4093.77
- Progressively locks in gain. Even on bounce-back to entry, exits at $4093+ for a small win.

---

### #7 — Partial TP at 50%

**Idea:** When price reaches 50% of TP distance, take half of the position off (lock in partial profit), let the other half run to full TP.

**Hypothesis:** Partial TPs are a common pro-trader practice. Splits expectancy: half-risk-free win + half-runner. Reduces variance of outcomes.

**Code sketch:**
```python
def check_partial_tp(trade, current_price, side):
    if trade.get("partial_tp_taken"):
        return  # Already done

    entry = float(trade["entry_price"])
    tp = float(trade["tp_price"])
    halfway = entry + 0.5 * (tp - entry)  # signed; works for both LONG and SHORT

    reached = (current_price <= halfway) if side == "SHORT" else (current_price >= halfway)
    if not reached:
        return

    # Close half the position
    half_units = trade["units"] // 2
    result = close_partial(trade["oanda_trade_id"], half_units)
    if result.get("success"):
        # Update DB: remaining units, mark partial taken, log
        execute("UPDATE gd_trades SET units=%s, partial_tp_taken=true WHERE trade_ref=%s",
                (trade["units"] - half_units, trade["trade_ref"]))
        _log_journal(trade["trade_ref"], strategy, "PARTIAL_TP", current_price, {
            "units_closed": half_units,
            "units_remaining": trade["units"] - half_units,
            "fill_price": result["fill_price"],
        })
        notify.partial_tp(trade["trade_ref"], result["fill_price"], half_units)
```

**Parameters to backtest:**
- Partial split: 50/50, 30/70, 70/30
- Partial trigger: 50% of TP, 30%, custom by R-multiple

**Expected effect:**
- Maximum trade P&L: halved (e.g., $989 TP → $500 partial + $500 max remainder)
- Trade variance: lower (more consistent outcomes)
- Win rate: higher (partial counts as partial win on stalls)
- Total expectancy: depends on backtest

**Backtest cost:** High. Backtest engine needs partial-fill modeling. ~3 hours to code, ~6 hours to validate. **Highest cost of the 7.**

**Dependencies:**
- DWX EA or OANDA API support for partial closes (verify)
- Schema: `partial_tp_taken` flag in `gd_trades` (currently doesn't exist)
- Backtest engine: track per-leg P&L

**Rollout risk:** High. Multi-leg trade tracking is complex. Defer until #1, #3, #5, #6 are validated.

**Today's trade applied:** At 50% to TP ($4075.77, today's near-bottom), partial TP fires:
- Close half: 23/2 = 11 units at $4075.77 → +$235 locked in
- Remaining 12 units rides to TP or BE-stop
- Total realized: $235 + (remaining outcome)

---

### #8 — Engulfing Close-Strength Filter

**Discovered live by user's eye:** the `OIL-AS-f5e9710a` LONG entry on 2026-06-11 at $92.95 was triggered by an M3 engulfing candle that wicked to $93.00 then closed at ~$92.80 — a clear wick-rejection pattern visible on the 5m chart, but the strategy's body-only engulfing detector accepted it. Trade went immediately negative and is sitting at -$180+ unrealized at time of writing.

**Idea:** Reject engulfing candles whose body sits in the middle of the range. A "true" entry-grade engulfing has the close in the upper third (bullish) or lower third (bearish) of the candle's high-low range, NOT in the middle with a long rejection wick.

**Hypothesis:** The current detector at `backend-oil/scanner/scheduler.py:211-214` (and equivalents) checks:
- `cc > co` (green for bullish)
- `cb <= pb + tol` (current body bottom engulfs prev body bottom)
- `ct >= pt - tol` (current body top engulfs prev body top)

None of these check WHERE the close sits relative to the candle's HIGH-LOW range. A green spike candle with long upper wick that closes 60% up still satisfies all three — but visually it's a failed breakout, not a successful engulfing.

**Code sketch:**
```python
# After existing engulfing checks pass, before computing entry/SL/TP:
candle_range = c["mid_high"] - c["mid_low"]   # using mid prices for parity
if candle_range > 0:
    if sweep_dir == "bullish":
        # Close should be in upper threshold% of candle range
        close_position = (cc - c["mid_low"]) / candle_range
        if close_position < EDGE_FILTERS["engulfing_close_strength_threshold"]:
            _log_signal(strategy, direction, ..., taken=False,
                        skip_reason=f"engulfing_close_too_weak:{close_position:.2f}")
            continue
    else:
        close_position = (c["mid_high"] - cc) / candle_range
        if close_position < EDGE_FILTERS["engulfing_close_strength_threshold"]:
            continue
```

**Parameters to backtest:**
- `engulfing_close_strength_threshold`: try 0.55, 0.60, 0.65, 0.70, 0.75
- Whether to apply on M3 (current) only or also require confirmation on next M3 close

**Expected effect:**
- Total trades: -10% to -20% (catches weak engulfings)
- PF: +20% to +35% (rejects the wick-rejection class)
- Win rate: +5 to +10pp
- The tighter the threshold, the fewer trades but the cleaner each one

**Backtest cost:** Low. ~30 min to add to engulfing detector, ~3 hours to validate across all 4 systems on 6+ months of data. Same complexity as #1.

**Dependencies:** None new — `c["mid_high"]`, `c["mid_low"]`, `cc` (close) already computed in the engulfing check.

**Rollout risk:** Low. Pure additive filter. If `engulfing_close_strength_enabled: False`, behavior is unchanged.

**Today's `OIL-AS-f5e9710a` applied:** Approximate values from chart inspection — engulfing candle high ≈ $93.00, low ≈ $92.50, close ≈ $92.80. close_position = (92.80 - 92.50) / (93.00 - 92.50) = **0.60**. Filter at threshold 0.65 would have skipped. Threshold 0.55 would have allowed.

**Caveat:** the deterministic high/low/close numbers for that exact M3 candle aren't in `gd_signals` — only entry_price post-slippage. Confirming the filter would have caught this requires pulling the M3 candle data the live scheduler saw at 14:45 UTC server time. Backtest cost includes that data verification step.

---

### #9 — R:R Upper Bound Filter (Skip Distant-TP Setups)

**Discovered from R:R distribution analysis 2026-06-11:** Today's `OIL-AS-59a94823` LONG entry at $91.51 with SL $91.08 and TP $94.32 had R:R **6.53:1**. While the existing gate at `backend-oil/scanner/scheduler.py:259` enforces `tp - entry >= risk * 0.8` (i.e., R:R lower bound of 0.8), there is no upper bound. R:R = 6.53 means the TP is 6.5× as far away as the SL — statistically harder to reach because price needs to sustain a long directional move without retracing through the BE level back to SL.

**Idea:** Add an upper bound to R:R: skip setups where `(tp - entry) / risk > MAX_RR`. Suggested MAX_RR = 4.0.

**Hypothesis:** When SL is unusually tight relative to TP distance, two things tend to happen:
1. **Tight SL gets stopped on noise** — sweep_wick + sl_buffer 0.03 puts SL well within typical M3 noise.
2. **Distant TP rarely hits** — needs sustained directional move, often retraces first.

The combination is "lottery-ticket geometry": occasional huge wins offset by frequent small losses. Net expectancy depends entirely on the win rate, which historically for distant-TP setups is poor.

**Code sketch:**
```python
# After computing entry, sl, tp, risk:
rr = (tp - entry) / risk if direction == "long" else (entry - tp) / risk
if rr > EDGE_FILTERS["max_rr_threshold"]:
    _log_signal(strategy, direction, entry, sl, tp, taken=False,
                skip_reason=f"rr_too_high:{rr:.2f}")
    continue
```

**Parameters to backtest:**
- `max_rr_threshold`: try 3.0, 4.0, 5.0, 6.0
- Whether to apply per-system (Macro Asia-window setups have wider TP than Micro rolling-window) or globally

**Expected effect:**
- Total trades: -5% to -10% (catches the rare extreme-R:R setups)
- PF: small improvement (+5% to +15%) — these are low-frequency but heavy-tail trades
- Win rate: small improvement
- Median trade P&L: more concentrated near typical R:R band

**Backtest cost:** Low. Single-line gate addition, ~1 hour to validate.

**Dependencies:** None.

**Rollout risk:** Low.

**Today's `OIL-AS-59a94823` applied:** R:R = 6.53. Filter at threshold 4.0 would have skipped. Threshold 5.0 would have skipped. Threshold 6.5 would have allowed (boundary).

**Interaction with #1 (range exhaustion):** Highly correlated. When most of the day's range is already covered, TP at the opposite range edge becomes structurally distant from entry. Both filters target the same trade class through different lenses. Backtest must measure overlap to avoid double-skipping.

**Note on the existing 0.8 lower bound:** the gate `tp - entry < risk * 0.8` enforces R:R >= 0.8 but is evaluated PRE-SLIPPAGE. Post-slippage R:R can drop below 0.8 (today's `OIL-AS-f5e9710a`: pre-slippage R:R ~0.83 → post-slippage 0.69). #9 doesn't fix this asymmetry — see candidate #16 below.

---

## Audit findings: Candidate filters #10–#17

Surfaced 2026-06-11 by an explicit "find any structural pattern we missed" audit run against all four scheduler files + both backtest strategy modules. Each is verified against the actual code, not memory or assumption. Numbered to extend the #1–#9 list above. Severity tags reflect what would surprise me most if shipped to live without backtest verification.

### #10 — Spread-Inside SL (Oil Macro guaranteed-slippage on stop) — HIGH

**Verified:** `backend-oil/config.py:29` → `sl_buffer = 0.03`. Typical BCO_USD spread observed today: $0.10–0.13. **SL is structurally inside the bid-ask spread** at entry — every stop-out fills with at least `(spread − sl_buffer) ≈ $0.07–$0.10` of additional slippage. The backtest's `slippage(br)` only models entry slippage, not exit slippage on SL. So today's tight-SL / structure-TP decoupling makes every Oil Macro SL ~$8 worse per unit than backtest assumes — at 113 units, that's ~$900 extra loss per SL trade vs backtest expectation.

**Fix:** spread-aware SL floor. `sl_buffer_effective = max(cfg["sl_buffer"], 1.5 × current_spread)` where `current_spread = m3_candles[-1]["ask_close"] - m3_candles[-1]["bid_close"]`.

### #11 — Non-deterministic Slippage (random term, no seed) — CRITICAL FOR PARITY

**Verified:** `backend/config.py:85`, `backend-oil/config.py:51`, `backend-oil-micro/config.py:59` → `slippage(br) = 0.03 + br*0.003 + np.random.uniform(0, 0.02)`. **The `np.random.uniform` call is not seeded.** Two backtest runs of the same input data produce different P&L. The parity harness already accounts for this somewhat (`np.random.seed(42)` in test_12_replay), but live is genuinely random — so backtest ≠ live by design, and the parity harness's reproduction of "what live would have done" is itself non-reproducible without a seed convention.

**Severity for parity work:** this is the only finding that AFFECTS the parity harness's correctness. Every other filter is upstream. A flaky slippage term means re-running the parity harness on the same data could shift parity_pct by 1-3 percentage points run-to-run. Need to seed before measuring filter effects, or the noise will swamp the signal.

**Fix:** Drop the random term entirely (`return 0.03 + br * 0.003`), OR seed it with a deterministic per-trade seed (e.g. hash of bar timestamp). Either change requires a parity-harness rerun to establish the new baseline.

### #12 — Engulfing-of-Doji (no body-magnitude check) — MEDIUM

**Verified:** All four engulfing detectors check `cb <= pb + tol AND ct >= pt - tol` but never verify the previous bar has a meaningful body. A doji with `po ≈ pc` trivially satisfies the body containment because `pb ≈ pt` — any non-doji "engulfs" it. **Engulfing of a doji is structurally a continuation candle, not a reversal.**

**Fix:** Require `prev_body = abs(pc - po) >= 0.3 × current_body` AND `prev_body >= ENGULFING_TOLERANCE × 2`. Skip dojis explicitly.

**Distinct from #8:** #8 checks the CURRENT candle's close strength; #12 checks the PREVIOUS candle's body magnitude. Both filters can ship together.

### #13 — Engulfing Wick-vs-Body Asymmetry — MEDIUM

**Verified:** Engulfing detector uses `ct = max(co, cc), cb = min(co, cc)` — pure body. A bullish engulfing candle could have a 2× body wick on top (rejection from above) and still pass: `cc > co AND cb <= pb + tol AND ct >= pt - tol` is satisfied by a hammer-at-the-high. **That's the OPPOSITE of a continuation signal** — buyers got rejected from above, then closed weakly.

**Fix:** For bullish engulfing, require `(c["mid_high"] - ct) <= 0.5 × body` (upper wick ≤ half body). Inverse for bearish. Body = `abs(cc - co)`.

**Overlaps with #8:** #8 checks close-position-in-range, #13 checks upper-wick-vs-body ratio. Both target wick rejections from different angles. Backtest must measure overlap.

### #14 — `skip_first_bar` Doesn't Prevent prev=sweep-bar Pollution — LOW-MEDIUM

**Verified:** `start_idx = 2 if cfg["skip_first_bar"] else 1` makes the first candidate `j=2`, meaning `prev = relevant_m3[1]`. But `relevant_m3` is filtered by `sweep_time < ts <= window_end` — the M3 bar AT or just-after the sweep close is `relevant_m3[0]`. So `relevant_m3[1]` is the M3 bar from the sweep-recovery move itself. **We're using the rejection bar as the engulfing predecessor — circular.** Almost any continuation candle "engulfs" the small body of a rejection bar.

**Fix:** Require `prev` to be a **completed reversal-direction bar**:
- For bullish-sweep (long entry), `prev` must be bearish (`pc < po`).
- For bearish-sweep (short entry), `prev` must be bullish (`pc > po`).

That way the engulfing has something REAL to reverse, not just any prior bar.

### #15 — Cooldown Bypass via Skip-Reason Whitelist — LOW

**Verified:** 5-min cooldown only triggers if `taken=True OR skip_reason in {"order_error", "sl_too_close"}`. Any other skip reason (DD pause, engulfing not found, etc.) bypasses cooldown entirely. The same sweep can re-evaluate every 3 minutes. Combined with `_traded_sweeps` not always being pre-marked (Oil Macro adds it AFTER successful execution, not before), there's a window where an exception-skipped trade isn't blacklisted and the next cron tick can retry the same sweep.

**Fix:** Match the Micro pattern (Oil Micro adds `sweep_key` to `_traded_sweeps` BEFORE `execute_signal` at `backend-oil-micro/scanner/scheduler.py:410`). Pre-add to blacklist, roll back only on confirmed-no-trade. Already partially done in Micro; replicate in Macro.

### #16 — R:R Lower Bound 0.8 is Too Low — MEDIUM

**Verified:** All 4 systems use `risk * 0.8`. With WR backtests of ~80%, R:R 0.8 is profitable in aggregate, but single trades are losing-asymmetric — sub-1R wins offset by full-R losses. In a streak of poor regime (today's 5/7 SLs), this is the first thing that breaks.

**Fix:** Raise lower bound to 1.0 (absorbs slippage erosion from #11) or 1.2 (cleaner, removes the "barely passing" trades). Combined with #9's upper bound 4.0, valid range becomes [1.0–1.2, 4.0]. **Calibration change — backtest required.**

### #17 — Oil Macro Live ≠ Backtest Risk Threshold — CRITICAL DRIFT BUG

**Verified directly in code:**
- `backend-oil/scanner/scheduler.py:285` (live): `if risk < 0.01 or risk > asia_range * 0.8: continue`
- `backend/strategies/alpha_sweep.py:111` (backtest, used for both Gold + Oil Macro): `if risk < 0.3 or risk > ar * 0.8: continue`

**The live Oil Macro takes trades the backtest never simulated.** A 10c-risk trade (after `min_sl=0.10` floor) passes live but fails backtest's 0.3 floor. This is a 6th confirmed live↔backtest drift bug.

**Fix:** Change live `risk < 0.01` to `risk < 0.3` to match backtest. One-line change.

**Important:** this isn't an "edge filter" in the same sense as #1-#16 — it's a **straight-up parity bug fix**. Should ship BEFORE the parity harness's filter-effect measurements, otherwise the harness's "before/after filter" baselines are themselves drifted.

---

## Cross-cutting design notes

### State persistence
Filters #2, #5, #6, #7 require per-trade or per-day state:

- `_taken_sweeps_today` (#2) — module-level dict, reset at scheduler restart or 00:00 UTC. Risk: scheduler restart loses state mid-day.
- `be_armed` (#5, #6) — needs DB column on `gd_trades` (currently inferred from sl_price == entry_price; should be explicit).
- `partial_tp_taken` (#7) — DB column required.
- Fixes ahead of these need schema migration.

### Telegram notification UX
Skip events should be visible but not noisy:
- `notify.signal_skipped(symbol, strategy, direction, reason)` — already exists for `tp_already_passed` etc.
- Add filter-specific reasons: `range_exhausted`, `trend_extended`, etc.
- Daily recon Telegram should aggregate skip counts per filter so impact is visible.

### Per-system enable flags
Each filter should be configurable per system. Example:
```python
EDGE_FILTERS = {
    "range_exhaustion_enabled": True,
    "range_exhaustion_threshold": 0.7,
    "first_sweep_only_enabled": False,  # let #1 cover this case
    "tp_feasibility_enabled": True,
    "tp_feasibility_factor": 0.7,
    "anti_trend_extension_enabled": True,
    "anti_trend_extension_atr_mult": 2.0,
    "be_trigger_pct": 0.35,  # was 0.50
    "trail_sl_enabled": False,  # ship after others validated
    "trail_sl_factor": 0.5,
    "partial_tp_enabled": False,  # ship last
    "partial_tp_split": 0.5,
}
```
Default values mirror current behavior so disabling = no behavior change.

### Filter ordering at runtime
When multiple filters are enabled, evaluate in this order to fail fast on cheapest checks:
1. `first_sweep_only` (state check, no compute)
2. `range_exhaustion` (single ATR + today_range)
3. `anti_trend_extension` (ATR + recent move)
4. `tp_feasibility` (ATR + time math)

Log which filter caused the skip so we can attribute backtest deltas correctly.

---

## Recommended rollout sequence

Each step gates on backtest results. **Do not ship to live until parity harness verifies live & backtest match for the same input.**

### Phase 0: Parity Harness (PREREQUISITE)
**✅ SHIPPED** as of 2026-06-11. See `docs/PARITY_HARNESS.md` for the operator guide and `docs/PARITY_HARNESS_PLAN.md` for the design.

The harness lives at `tests/harness/test_22_parity.py` + `tests/harness/parity/`. It runs in ~25s across all 4 systems, fails the build on catastrophic drift (parity<50% or direction-flip>5), and emits a JSON artifact per run. v1 baseline numbers are recorded in PARITY_HARNESS.md.

For each EDGE_FILTER below, the workflow is:
1. Add the filter to the live signal-gen path.
2. Run the parity harness — observe the new skip events on the live side.
3. Mirror the filter on the backtest signal-gen path.
4. Re-run the harness. Confirm parity stays at or above the v1 baseline.
5. If parity drops, the filter is implemented asymmetrically — fix before shipping.

### Phase 1: Filter #1 (Range Exhaustion) — solo
- Implement filter
- Backtest with thresholds 0.6, 0.7, 0.8, 0.9
- Pick best threshold
- Verify parity harness passes
- Ship to live with `range_exhaustion_enabled: True`, monitor for 1 week

### Phase 2: Filter #5 (BE 50% → 35%) — solo
- Backtest BE values 0.30, 0.35, 0.40, 0.45 with #1 already shipped
- Validate
- Ship

### Phase 3: Filter #3 (TP Feasibility)
- Stack on top of #1 and #5
- Backtest, validate, ship

### Phase 4: Filter #4 (Anti-Trend-Extension)
- Test for redundancy with #1; only ship if it adds independent value
- Validate, ship

### Phase 5 (optional): Filter #6 (Trailing SL)
- Higher complexity, schema change required
- Demo-test SL modification rate-limits
- Ship if backtest justifies

### Phase 6 (optional): Filter #7 (Partial TP)
- Highest complexity, multi-leg tracking
- Defer until prior phases stable for 1+ months

### Phases 7+: Filter #2 (First-Sweep-of-Day)
- Likely redundant with #1 — defer; ship only if backtest shows independent edge.

---

## Success metrics

When evaluating each filter in backtest:

| Metric | Goal | Current baseline |
|---|---|---|
| Profit factor (PF) | +20%+ | ~3.5 (Gold Micro) |
| Win rate | +5pp+ | ~58% (Gold Micro estimated) |
| Average winner $ | preserved | varies |
| Average loser $ | reduced | varies |
| Max drawdown $ | reduced | varies |
| Total trades | -10% to -30% (acceptable cost) | varies |
| Expectancy per trade | +25%+ | varies |

A filter that reduces total trades but doesn't improve expectancy is **net negative** (less data, no edge gain). Don't ship.

A filter that improves PF but reduces total trades by >40% is **suspicious** (possibly curve-fit). Walk-forward verification required.

---

## What this initiative is NOT

- **NOT** a full strategy rewrite — Alpha-Sweep core (sweep + engulfing + bias) stays unchanged.
- **NOT** a regime detector — too easy to curve-fit. Rule-based filters with clear physical interpretation.
- **NOT** ML-driven — adds opacity without proven edge in this strategy size.
- **NOT** a position-sizing change — DD halving handles that already.
- **NOT** intended to ship all 7 — likely 3-4 will validate. Others get shelved.

---

## Open questions for the parity harness phase

1. Where should EDGE_FILTERS state live? (Module-level dict vs DB row vs new `gd_strategy_state` table)
2. How does the parity harness assert that live skip-decisions match backtest skip-decisions for the same input bar?
3. Should the parity harness re-run on every commit, or only on demand?
4. What's the minimum bar dataset for meaningful backtest? (Suggest: 6-12 months of M3 + H1 across both Gold and Oil)
5. Should harness output include skip-reason histograms so we can verify filter effects empirically?

---

## References

- Trade that surfaced this: `docs/trades/GD-MI-14e2fed1.md` (postmortem to be written when trade closes)
- Parity gap memory: `[[project-live-backtest-parity-gap]]`
- Backtest engine: `backtest/` (verify which file owns the signal-gen path)
- Live signal-gen: `backend-micro/scanner/scheduler.py:_run_micro_sweep` and equivalents
- Naming origin: this doc, 2026-06-11
