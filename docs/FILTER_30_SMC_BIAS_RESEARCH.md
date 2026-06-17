# Filter #30 — SMC PDH/PDL Liquidity-Sweep Bias

**Status:** RESEARCH / NOT IMPLEMENTED. Triggered 2026-06-18 by user observation that the current bias filter (V1+V2 candle-shape) is fundamentally different from SMC/ICT liquidity-based bias.
**Pre-requisite:** Filter #28 (`bias_mode='neutral'`) must ship first — F30 is one of the candidate replacements for the disabled V1+V2 filter.
**Cross-references:** [[bias-filter-net-negative]], `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md`, `ICT_RESEARCH_FINAL.md` (VibeTrader repo).

---

## TL;DR

Current bias filter ("V1+V2 candle-shape") just looks at yesterday's daily candle and asks "did it close strong up or down?" Filter #28 BT proved this filter is **net-negative by $3.58M / 21yr across 4 systems**.

Filter #30 proposes a structurally different bias: **SMC liquidity-sweep bias** based on Previous Day High (PDH) and Previous Day Low (PDL). Bias is set DYNAMICALLY when today's price sweeps a previous day's level and rejects, not statically at session open.

**Key claim to test:** SMC bias might be the version of "bias" the strategy actually wants — because both the SMC bias AND our Alpha-Sweep entry are liquidity-sweep-based, so they're in structural alignment instead of fighting (which is what V1+V2 does).

---

## Background — why V1+V2 is structurally wrong for our strategy

### What V1+V2 actually does

`backend/backtest/engine.py:160-183` (Gold Macro, with the same logic mirrored in 3 other engines):

```python
# V1: body strength
body_pct = abs(close - open) / (high - low)
if body_pct >= 0.4:
    v1 = "bullish" if close > open else "bearish"
else:
    v1 = "neutral"

# V2: close position within range
close_pos = (close - low) / (high - low)
if close_pos >= 0.8: v2 = "bullish"
elif close_pos <= 0.2: v2 = "bearish"
else: v2 = "neutral"

# Combine: ANY bearish wins, then ANY bullish, else neutral
```

**This is essentially a trend-following filter on the daily timeframe.** "Yesterday closed strong → today is bullish."

### Our strategy is mean-reversion

Alpha-Sweep is a **liquidity-sweep mean-reversion** setup:

1. Wait for price to wick OUTSIDE the consolidation range (sweep liquidity above/below)
2. Wait for an engulfing candle BACK INSIDE
3. Enter against the sweep direction

**This is anti-trend by design.** A bullish sweep takes liquidity below structure → strategy goes LONG (against sellers). A bearish sweep takes liquidity above structure → strategy goes SHORT (against buyers).

### The structural mismatch

Suppose yesterday closed strong up (V1+V2 → bullish bias).
Today, price wicks ABOVE the rolling-consolidation high and rejects (bearish sweep).

- Strategy says: SHORT (mean-reversion)
- V1+V2 says: bias is bullish, BLOCK SHORT signals
- Result: signal is filtered out

But this is exactly the kind of setup the strategy is designed to catch — "buyers got trapped chasing yesterday's rally; price rejected; sell."

**V1+V2 forces the strategy to align with the prior-day trend, when its actual edge is mean-reverting against that trend.** Filter #28 BT empirically confirms: removing V1+V2 frees up $3.58M / 21yr of legitimate signals that were being incorrectly blocked.

---

## What SMC Bias Does Differently

### Concept (per ICT / SMC literature)

Smart Money Concepts (SMC) traders treat **previous-period extremes** (PDH, PDL, weekly high/low, Asia high/low) as **liquidity pools** — places where retail traders cluster stop-loss orders.

Institutional traders ("smart money") deliberately push price into these pools to grab the stops, then reverse. This is "liquidity sweep" or "stop hunt."

### How it sets bias

**Bullish bias is established when:**
- Today's price drops below PDL (Previous Day Low)
- Then closes back above PDL (rejection / reversal upward)
- Indicates: liquidity below has been taken; sellers exhausted; buyers stepping in

**Bearish bias is established when:**
- Today's price spikes above PDH (Previous Day High)
- Then closes back below PDH (rejection / reversal downward)
- Indicates: liquidity above has been taken; buyers exhausted; sellers stepping in

**Neutral / no bias:**
- No PDH/PDL sweep yet today
- Price has swept BOTH (rare, ambiguous)
- Bias hasn't formed — strategy is allowed to fire either direction (same as F28 neutral)

### Critical timing difference vs V1+V2

| Aspect | V1+V2 (current) | SMC PDH/PDL (proposed F30) |
|---|---|---|
| When set | At session open (00:00 UTC) | Dynamically when sweep+reject occurs |
| Source | Yesterday's daily candle shape | Today's interaction with PDH/PDL |
| Default state | Always set to bull/bear/neutral | "Pending" until sweep happens |
| Updates intraday | No — frozen at open | Yes — flips when sweep occurs |
| Direction inferred | Same as yesterday's daily close | Opposite of swept-and-rejected level |

### Why SMC bias structurally aligns with Alpha-Sweep

Both mechanisms are **liquidity-sweep + reversal** patterns at different timescales:

- **SMC daily bias:** sweep PDL/PDH (daily liquidity) + reject → bias direction
- **Alpha-Sweep entry:** sweep consolidation high/low (intraday liquidity) + engulfing reversal → entry direction

If price sweeps PDL and rejects (bullish daily bias), then later in the day sweeps the rolling consolidation low and rejects (bullish entry signal), **both signals agree** — the day really is "buyers taking control after a stop run."

If price sweeps PDH and rejects (bearish daily bias), and intraday strategy sees a bearish sweep+engulfing, **both agree** — bearish day, sell the bounce.

**This is structural alignment, not trend-following.**

---

## Proposed Implementation

### Bias state machine (per day, per asset)

```
At session start (00:00 UTC):
  state = "PENDING"
  pdh = yesterday_daily_high
  pdl = yesterday_daily_low

For each M3 bar during the day:
  bar_high, bar_low, bar_close = (current bar OHLC)

  # Bullish sweep: dipped below PDL and closed back above
  if bar_low < pdl and bar_close > pdl and state in ("PENDING", "BEARISH"):
    state = "BULLISH"
    bias_set_time = bar_ts
    swept_level = "PDL"

  # Bearish sweep: spiked above PDH and closed back below
  elif bar_high > pdh and bar_close < pdh and state in ("PENDING", "BULLISH"):
    state = "BEARISH"
    bias_set_time = bar_ts
    swept_level = "PDH"

  # Note: state CAN flip during the day if both PDL and PDH get swept on opposite reactions.
  # That's a "double sweep" day — informationally rich but rare.

Lookup at signal time:
  bias = state  # "PENDING" | "BULLISH" | "BEARISH"
```

### Strategy filter integration

In `backend/strategies/alpha_sweep.py:80` (mirror in 3 other systems):

```python
# CURRENT (V1+V2):
if bias != "neutral":
    if sweep_dir == "bullish" and bias != "bullish":
        continue
    if sweep_dir == "bearish" and bias != "bearish":
        continue

# PROPOSED (F30 SMC):
# bias state is one of: "PENDING", "BULLISH", "BEARISH"
# - PENDING (no sweep yet today)        → allow both directions (like neutral)
# - BULLISH (PDL swept and rejected)    → only allow bullish sweeps (long entries)
# - BEARISH (PDH swept and rejected)    → only allow bearish sweeps (short entries)
if bias == "BULLISH" and sweep_dir != "bullish":
    continue
if bias == "BEARISH" and sweep_dir != "bearish":
    continue
# PENDING → no filter (allow both)
```

### Variants to BT-sweep

Per `[[project-filter-sweep-workflow]]`, F30 needs a per-variant grid:

| Variant | PDH/PDL source | Sweep threshold | Reject confirmation | Expected coverage |
|---|---|---|---|---|
| **30-A** | Daily H/L of prior calendar day | Strict (close back inside) | Close beyond level by ≥ 0 | Most conservative |
| **30-B** | Daily H/L of prior session (00-24 UTC) | Strict | Close beyond level by ≥ ATR(D)/4 | Tighter rejection |
| **30-C** | Daily H/L | 0.1 × ATR(D) extension | Close back inside | Slightly looser sweep |
| **30-D** | Daily H/L | Strict | Allow any single M3 close back inside (not just sweep bar) | Looser rejection |
| **30-E** | Asia high/low (00-08 UTC) | Strict | Close back inside | Earlier intraday signal |
| **30-F** | Weekly H/L of prior week | Strict | Close back inside | Lower frequency, higher significance |
| **30-G** | Multi-level: any of (PDH, PDL, Asia H/L) | Strict | First sweep wins | Most aggressive |

**Sweep cycle: 7 variants × 4 systems × multi-seed = ~140 BTs.** ~5-7 hours wall-clock.

---

## Key Hypotheses to Validate

1. **F30 beats F28-neutral.** SMC bias is selective in a way that helps. Hypothesis: cumulative ΔP&L (F30 minus F28-neutral) is positive across all 4 systems.

2. **F30 fixes V1+V2's structural mismatch.** When the strategy fires a sweep signal, the bias agrees more often than V1+V2 does. Measurable: agreement rate %.

3. **Yearly slice consistent.** F30 doesn't concentrate gains in one year; works across 21 years.

4. **Live↔BT parity holds.** If we ship F30, the same intraday calculation must run in the live scanner — that's a nontrivial integration (PDH/PDL needs to be tracked in real-time, not just from CSV history).

5. **Drawdown.** SMC bias might INCREASE DD by allowing more losers on misread sweeps. Need DD stress test.

---

## Risks & Caveats

### Implementation hazards

1. **PDH/PDL ambiguity at session boundary.** Forex markets run 24/5 — when does "previous day" end? OANDA `dailyAlignment=21` already caused drift bug #6 in F28's original keying. F30 must handle this carefully or repeat the same class of bug.

2. **Sweep detection sensitivity.** Wickers vs full breaks vs 1-tick spikes — same problem we documented in `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md` for the broader sweep concept. Need to use closed M3 bars only, no intra-bar look-ahead.

3. **State flip overhead.** If F30 BT is implemented as "walk every M3 bar and update state," it doubles per-day compute. Need vectorized variant or accept ~15min/run penalty.

4. **Live integration.** SMC bias must be computed in `backend/scanner/live_engine.py` and friends — a real intraday state machine, not a daily lookup. Adds complexity vs current daily-bar lookup.

### Research hazards

1. **F30 might just rediscover F28-neutral.** If bias state is "PENDING" most of the day (rarely sweeps PDH/PDL early), the filter is effectively neutral most of the time → F30 ≈ F28-neutral. Hypothesis test: % of signals fired during PENDING vs non-PENDING.

2. **Selection bias from SMC literature.** SMC concepts are popular but have weak public empirical support. We should NOT trust the framework just because it sounds sophisticated. The 21yr BT is the only valid evidence.

3. **Overfitting via variant proliferation.** 7 variants is a lot of configurable knobs — must use the [[feedback-filter-measurement-gate]] discipline: 21yr BT pre/post per variant, no ranking via in-sample, multi-seed required before any ship decision.

---

## Plan of Action

### Phase 0 — Cross-reference existing ICT research
Repository already contains `ICT_RESEARCH_FINAL.md`, `ICT_RESEARCH_LOG.md`, `ICT_STRATEGY_GUIDE.md` (in VibeTrader root). Check whether prior ICT research already evaluated PDH/PDL bias — if so, lift findings into this doc as starting evidence.

### Phase 1 — Implement F30 in BT engine (4 systems)
- Add `compute_smc_bias(daily_df, m3_df) → dict[date → state_machine_log]` helper in `backend/backtest/smc_bias.py`
- Wire into each engine's `run_backtest` via new kwarg `bias_mode="smc_pdh_pdl"`
- Reuse same NeutralBiasDict-style pluggability we built for F28 (already in `backend/backtest/neutral_bias.py`)

### Phase 2 — Run sweep
- 7 variants × 4 systems = 28 BTs
- Single-seed first (replicates F28 Path A path)
- Multi-seed (5 seeds × 28 = 140) for any variants that look promising

### Phase 3 — Compare vs F28 baseline
Three-way comparison per system × variant:
- Production V1+V2 (current shipped)
- F28 neutral (no bias)
- F30 SMC (each variant)

Win condition: F30 > F28-neutral AND F30 > V1+V2 AND yearly slice ≥ 18W/3L per system

### Phase 4 — Live integration (only if BT validates)
- Real-time PDH/PDL state machine in scanner
- Parity harness check: live SMC bias must match BT SMC bias on same data
- Selective ship per system per `[[feedback-selective-ship-pattern]]`

---

## Open Questions Before BT Cycle Starts

1. **Sweep depth threshold:** strict (any wick beyond level) vs N×ATR (filter noise wicks)? Variants 30-A vs 30-C answer this.
2. **Reject confirmation:** must the swept bar's CLOSE be back inside, or can the rejection happen on a later bar within X minutes? Variants A/B/D answer this.
3. **State persistence:** if bias flips mid-day from BULLISH→BEARISH (rare), do we honor the new state immediately or only on next bar? **Default: honor immediately, rare case.**
4. **No-sweep days:** if neither PDH nor PDL is swept all day, state stays PENDING all day. Strategy then runs neutral (allow both directions). **Unstated risk:** PENDING days might be the BAD days the V1+V2 filter was actually catching. F30 BT must measure outcome on PENDING days separately.

---

## Decision Gate

**F30 ships only if:**
- F28 ships first (sets baseline of `bias_mode='neutral'`)
- 21yr BT shows F30 beats F28-neutral by ≥ 5% on PF AND ≥ 5% on total P&L
- Yearly slice 18W/3L or better per system
- Multi-seed std/mean < 10%
- DD stress passes (not worse than F28-neutral baseline by > 2pp)
- Parity harness confirms live = BT

**F30 stashes if any gate fails.** Falling back to F28-neutral is the no-bias default; F30 is a bonus on top.

---

## Cross-references

- `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md` — the parent finding F30 builds on
- `[[bias-filter-net-negative]]` — memory note from F28 single-seed discovery
- `backend/backtest/neutral_bias.py` — reusable NeutralBiasDict pattern
- `[[project-filter-sweep-workflow]]` — branch → BT pre/post → user sign-off → ship-or-stash protocol
- `[[feedback-filter-measurement-gate]]` — every gate change runs 21yr BT; no exemptions
- `[[feedback-selective-ship-pattern]]` — per-system ship decisions
- `ICT_RESEARCH_FINAL.md` (VibeTrader repo) — prior ICT research notes
