# Filter #31 — DXY Anti-Correlation Confirmation (Gold-only)

**Status:** RESEARCH / NOT IMPLEMENTED. Parked behind F30 (SMC PDH/PDL bias).
**Triggered:** 2026-06-18 by user observation that gold has structural inverse correlation with the US Dollar Index, and SMC traders use this as a "truth check" — gold UP requires DXY DOWN to be a real move.
**Pre-requisite:** F28 (`bias_mode='neutral'`) shipped first, F30 BT result known. F31 is candidate ONLY if F30 fails to beat F28-neutral and/or F30 ships and we want a stacked confirmation layer.
**Cross-references:** `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md`, `docs/FILTER_30_SMC_BIAS_RESEARCH.md`, `[[bias-filter-net-negative]]`.

---

## TL;DR

Gold (XAU/USD) is denominated in US Dollars. **Structurally:** stronger USD → cheaper gold (and vice versa). The US Dollar Index (DXY) measures USD strength against a 6-currency basket. Long-run XAU/DXY correlation: roughly **-0.5 to -0.7** over multi-year windows.

**The proposed filter:** block any Gold signal that disagrees with current DXY direction. If our strategy says LONG Gold but DXY is rallying, **don't trade** (the signal is fighting the dollar).

**Why this is risky for our strategy:** Filter #28 just proved that static directional pre-filters HURT our mean-reversion strategy by $3.58M / 21yr. F31 is **another static directional pre-filter**. Same structural risk pattern. **Likely outcome:** F31 BT shows similar harm to F28's V1+V2.

**Why test it anyway:** different mechanism (cross-market, not candle-shape). Different prior. Could surprise us.

**Scope:** Only Gold Macro + Gold Micro. Oil systems N/A — Brent's correlation with DXY is much weaker and structurally different.

---

## Background — the Gold ↔ DXY relationship

### What DXY is

US Dollar Index = geometric weighted basket of 6 currencies vs USD:

| Currency | Weight |
|---|---|
| EUR | 57.6% |
| JPY | 13.6% |
| GBP | 11.9% |
| CAD | 9.1% |
| SEK | 4.2% |
| CHF | 3.6% |

So DXY is mostly **EUR/USD inverse** (58% of weight) plus minor contributions.

### Why gold is correlated to DXY (the math)

Gold's "true" value is independent of any currency — it's a real asset. But gold quoted in USD (XAU/USD) reflects:

```
XAU/USD price ≈ (real gold value in some neutral unit) / (USD strength)
```

If USD strengthens (DXY up): same gold buys more dollars → XAU/USD denomination falls → gold price drops.
If USD weakens (DXY down): same gold buys fewer dollars → XAU/USD price rises.

This is **not folklore — it's denomination math.** A move in either gold OR DXY mechanically forces a move in the other unless something offsets it.

### Why correlation is NOT -1.0 in practice

- **Crisis flight-to-safety:** USD AND gold both rally as panic asset. 2008, March 2020 had episodes where DXY +2% AND XAU/USD +2% in same week.
- **Geopolitical demand:** wars, central bank buying, supply shocks (mining strikes) move gold independently of dollar.
- **Real rates:** when real yields rise (USD bonds attract capital), DXY goes up AND gold typically falls — but sometimes gold falls FASTER than DXY rises, breaking proportionality.
- **Asian session disconnects:** US closed, Asian gold demand can move XAU/USD without DXY moving (DXY only meaningful when major currencies trade).

So the "DXY = truth check for gold" rule has **real economic basis but unreliable execution.**

### What SMC / retail teaching says

The user-quoted rule:
> DXY is breaking upward → Gold is going DOWN
> DXY is breaking downward → Gold is going UP
> DXY in tight range → Gold goes SIDEWAYS
> If your Gold chart says UP but DXY is also skyrocketing → don't trade

This is a **directional confirmation filter**: only take Gold signals that agree with DXY's anti-correlation expectation.

---

## Where this conflicts with our strategy (the V1+V2 problem, again)

### Reminder of what F28 proved

Filter #28 BT (2026-06-18, multi-seed in progress): static directional pre-filters (V1+V2 candle-shape) **hurt** the strategy by $3.58M / 21yr because they BLOCK valid mean-reversion entries.

The mechanism:
```
Strategy fires SHORT (mean-reversion sell at swept high)
V1+V2 says: yesterday closed bullish → bias bullish → BLOCK SHORT
Trade not taken. Trade would have won. Filter cost = win.
```

### F31 has the same structural pattern

```
Gold strategy fires LONG (mean-reversion buy at swept low)
F31 checks DXY: DXY rallying → "Gold should go DOWN" → BLOCK LONG
Trade not taken. If trade would have won, F31 cost = win.
```

The TWO filters are different signals but same VICTIM: any time the mean-reversion entry disagrees with the prevailing macro direction, the filter blocks it. By design, **mean-reversion entries usually disagree with prevailing direction** — that's literally what mean-reversion means.

So F31's prior probability of net-helping our specific strategy is **low**, the same way V1+V2's prior should have been low.

### Why test it then

Two reasons:

1. **Different signal class.** V1+V2 is daily-candle-shape (intra-asset). F31 is cross-market correlation. **It's possible** the cross-market signal has predictive power that candle-shape lacked.

2. **Different timing.** F31 can update in real time as DXY moves. V1+V2 was frozen at session open. So F31 might catch dynamic dollar moves that V1+V2 couldn't see.

But: **F30 (SMC bias) is structurally aligned with the strategy** (sweep-based). F30 has a higher prior of working than F31. F31 is the fallback if F30 fails.

---

## Proposed Implementation

### Data dependency (BLOCKING)

**We do NOT have DXY history in the repo.**

Available data in `data/raw/`:
```
BCO_USD_M3.csv     — Brent
XAU_USD_M3.csv     — Gold
XAU_USD_H1.csv     — Gold H1
XAU_USD_D.csv      — Gold daily
EUR_USD_D.csv      — EUR daily
SPX500_USD_D.csv   — S&P 500
USB02Y_USD_D.csv / USB10Y_USD_D.csv — bond yields
XAG_USD_D.csv      — Silver
```

**No DXY proper. No EUR/USD M3. No JPY/GBP/CAD M3.**

To test F31 we have **3 options:**

#### Option A: Use DXY directly (preferred but requires data fetch)
- OANDA does NOT offer "DXY" as a tradeable instrument
- Source: ICE futures (DXY ticker), or third-party (TradingView API, Bloomberg, etc)
- Effort: ~2 hr to set up data ingestion + 21yr backfill from a free historical source (e.g. Stooq, Yahoo Finance via `yfinance` for daily; intraday is harder)
- **Daily DXY likely sufficient** since gold's correlation with daily DXY is the textbook claim. Intraday DXY is finer-grained but adds enormous data overhead.

#### Option B: Use EUR/USD as proxy (quick-and-dirty)
- EUR/USD is 58% of DXY weight, ~-0.95 correlation to DXY
- Inverse: DXY up ↔ EUR/USD down
- Pro: just need to fetch EUR/USD M3 from OANDA (already have EUR/USD daily; M3 would need backfill)
- Con: not the actual DXY, so the filter's "truth" is approximated

#### Option C: Synthesize DXY from a 6-currency basket
- Pull EUR, JPY, GBP, CAD, CHF, SEK historical prices (M3 or H1)
- Compute basket index per ICE methodology
- Pro: most accurate
- Con: highest effort (~6 CSVs × 21yr each, plus weighting math, plus base value normalization)

**Recommendation:** **Option A (daily DXY)** for first pass. If F31 BT shows promise, then upgrade to intraday via Option C.

### Bias rules (variants)

**Variant 31-A — Daily DXY direction lookback:**
```
At each Gold signal:
  prev_dxy_close = DXY close N days ago
  current_dxy_close = today's DXY close (or last available)
  dxy_direction = "up" if current > prev, "down" if current < prev, "flat" if Δ < threshold

  if signal_dir == "long" and dxy_direction == "up":   block  # gold going up but dollar also up — fight
  if signal_dir == "short" and dxy_direction == "down": block # gold going down but dollar also down — fight
  else: allow
```

**Variant 31-B — Intraday DXY (requires intraday DXY data):**
Same as 31-A but uses last N M3 bars of DXY instead of daily.

**Variant 31-C — Rolling correlation gate:**
```
Compute rolling 30-day Pearson correlation(XAU/USD daily, DXY daily)
If correlation today > -0.3 (insufficient anti-correlation): allow ALL signals
Else: apply 31-A rule
```
This is the SAFEST variant — only filters when XAU/DXY are actually behaving as inverses.

**Variant 31-D — Both must agree (strict):**
```
Bullish gold signal requires: DXY trending DOWN over last N hours
Bearish gold signal requires: DXY trending UP over last N hours
Otherwise: skip
```

**Variant 31-E — Only block on SAME-direction (loose):**
```
Bullish gold signal blocked ONLY if DXY also bullish over last N hours
Bearish gold signal blocked ONLY if DXY also bearish over last N hours
DXY in any other state: allow signal
```
Allows trades when DXY is flat or unclear.

### Variant grid

| Variant | DXY source | Lookback | Block rule | Expected coverage |
|---|---|---|---|---|
| 31-A | Daily DXY close | 1 day | Same-direction | Most days have a clear DXY direction → many trades blocked |
| 31-B | M3 DXY close | last 1 hour | Same-direction | Frequent direction flips → few blocks |
| 31-C | Daily DXY + 30d corr | 1 day | Block only when corr ≤ -0.3 | Gates filter on correlation regime |
| 31-D | M3 DXY trend | last 4 hours | Both must agree | Strict: blocks more, but each kept signal has cross-confirmation |
| 31-E | M3 DXY trend | last 4 hours | Block only if DXY same direction | Loosest: blocks only the obvious traps |

**5 variants × 2 Gold systems × multi-seed = ~50 BTs.** Wall-clock ~5 hours.

### Strategy filter integration

In `backend/strategies/alpha_sweep.py` (Gold Macro) and `backend/strategies/micro_alpha_sweep.py` (Gold Micro), after the existing bias check (or after F30's bias check if shipped):

```python
# F31 — DXY anti-correlation confirmation (Gold systems only)
if dxy_filter_enabled:
    dxy_direction = compute_dxy_direction(signal.date, lookback_bars=N, mode=variant)
    if signal.direction == "long" and dxy_direction == "bullish":
        continue  # Gold long blocked by DXY bullishness
    if signal.direction == "short" and dxy_direction == "bearish":
        continue
    # neutral DXY → allow
```

### Live integration considerations (only if BT ships)

1. **Real-time DXY feed.** OANDA doesn't quote DXY. Options:
   - Compute synthetic DXY from EUR/USD/etc tickers (which DO trade on OANDA via Brent broker)
   - Subscribe to a DXY tick feed (TradingView, etc) — more infra
   - Use EUR/USD inverse as proxy for live (Option B)
2. **Latency.** DXY on a 1-min lag is fine. 1-hour lag is dangerous.
3. **Failure mode.** If DXY feed dies, default to "neutral DXY → allow signal" (fail-open). Log loud.

---

## Hypotheses to Test (in order)

1. **F31 has a positive ΔP&L vs F28-neutral baseline.** *Prior: low. Same V1+V2 risk pattern.*
2. **Variant 31-C (correlation-gated) wins over 31-A (always-on).** *Prior: medium. Only filtering when XAU/DXY are actually anti-correlated should reduce harm.*
3. **F31 stacks usefully on top of F30 if both win.** *Prior: very low. Two directional filters compounding rejection rate would block too many signals.*
4. **F31 affects trade count > 30%.** Indicates the filter is meaningfully active. If <10%, F31 is doing nothing.

---

## Risks

### Implementation risks

1. **Data gap.** Need DXY history. Adds project setup time before any BT.
2. **Live feed dependency.** Adds an external data integration that can fail.
3. **Synthetic DXY drift.** If we use EUR/USD as proxy for live but BT uses real DXY, BT↔live parity breaks.

### Research risks

1. **Most likely outcome: F31 is net-negative** (same as V1+V2). The prior is low because the structural mechanism is the same.
2. **Variant proliferation.** 5 variants is enough that one might look good in BT just by chance. Use [[feedback-filter-measurement-gate]] discipline.
3. **2008/2020 distortion.** During crisis weeks, DXY-Gold correlation flips. F31 might appear to "save us" from those weeks in BT but actually has no predictive value for them in real time.
4. **Selection bias from SMC literature.** "DXY rule" is folklore-popular but lightly evidenced. Treat as just-another-filter.

### Strategy fit risks

1. **F31 may BLOCK exactly the kind of dislocation Alpha-Sweep catches.** Big DXY moves often trigger gold liquidity sweeps. F31 would block those signals "because DXY is moving with gold." But our strategy SPECIFICALLY trades the rejection AFTER the sweep. F31 might be filtering out our most profitable setups.

This is the same fundamental risk as V1+V2 (proven net-negative) and the open question on F30 (yet to test). All three filters fight the strategy structurally.

---

## Decision Gate

**F31 ships only if:**
- F28 ships first (sets `bias_mode='neutral'` baseline)
- F30 BT result known (we ship F30 if it wins, otherwise F30 stashes)
- F31 21yr BT shows BOTH:
  - F31 beats F28-neutral on Gold Macro by ≥ 5% on PF AND ≥ 5% on total P&L
  - F31 beats F28-neutral on Gold Micro by ≥ 5% on PF AND ≥ 5% on total P&L
- Yearly slice 18W/3L per Gold system
- Multi-seed std/mean < 10%
- DD stress no worse than F28-neutral by > 2pp
- Variant winner has ≥ 30% rejection rate (filter is doing real work, not just rubber-stamping)
- Live feed integration is solid (no fail-open silent skip)

**F31 stashes if any gate fails.** Falling back to F28-neutral or F30 (if shipped) is the default.

---

## Plan of Action

### Phase 0 — Data acquisition
- Fetch DXY daily history (Stooq or Yahoo Finance via `yfinance`). 21yr daily ≈ ~5,500 rows; trivial to backfill.
- Save as `data/raw/DXY_D.csv` mirroring existing CSV format.
- (Optional) Build EUR/USD-based proxy as a fallback.

### Phase 1 — Implement F31 in BT engine
- Add `data/dxy_loader.py` shared helper
- Add `compute_dxy_direction(timestamp, lookback, mode)` in shared module
- Wire into Gold Macro + Gold Micro engines via `dxy_filter` kwarg (same opt-in pattern as F28's `bias_mode`)
- Default `dxy_filter=None` → existing behavior unchanged

### Phase 2 — BT sweep
- 5 variants × 2 Gold systems = 10 single-seed BTs
- Multi-seed (5 seeds) for any winners → 25 BTs

### Phase 3 — Compare
Three-way (or four-way) comparison per system × variant:
- Production V1+V2 (current shipped — pending F28 ship)
- F28-neutral (no bias)
- F30 (if shipped)
- F31 (each variant)
- F30 + F31 stacked (if both look good individually)

### Phase 4 — Live integration (only if BT validates)
- DXY live feed integration — daily lag acceptable
- Parity harness check (live DXY value matches BT DXY value at same timestamp)
- Selective ship per Gold system

---

## Open Questions

1. **Daily DXY vs intraday DXY:** Daily is the textbook concept; intraday is finer-grained but might be noisy. Test daily first, escalate to intraday if daily looks promising.
2. **Lookback window:** 1 day? 3 days? "Today vs yesterday close"? Variant grid covers, but priors unclear.
3. **What if DXY is "flat"?** Defaulting to "allow" makes F31 less restrictive (good). Defaulting to "block" makes it more restrictive (likely bad).
4. **Stacking with F30:** if both F30 and F31 ship, the union of their rejections might be too aggressive. Need to BT them stacked to see.
5. **2008/2020 anomaly handling:** during crisis weeks, gold and DXY can BOTH rally (flight to safety). F31 would block all Gold longs during those moments. Is that actually harmful? BT will tell.

---

## Why This Is Parked Behind F30

F30 (SMC PDH/PDL bias) has higher prior of working because:
- F30 is **structurally aligned** with our strategy (both are sweep-based)
- F30 doesn't require new data dependencies
- F30 doesn't introduce live-feed integration risk

F31 (DXY confirmation) has lower prior because:
- F31 is **structurally similar to V1+V2** (directional pre-filter)
- F31 needs new data (DXY history fetch)
- F31 needs live feed integration if shipped

If F30 wins BT and ships, F31 becomes a candidate for **stacking on top** of F30 (does adding cross-market confirmation help further?). If F30 fails BT, F31 becomes the next candidate to test as a different mechanism.

If F30 ships AND F31 ships, both stacked, we then have a layered bias system: SMC (sweep-based, our edge) + DXY (cross-market confirmation). That could be powerful — or could over-filter to nothing. Only BT will tell.

---

## Cross-references

- `docs/FILTER_28_BIAS_DISABLE_RESEARCH.md` — parent finding (no-bias > V1+V2)
- `docs/FILTER_30_SMC_BIAS_RESEARCH.md` — sister proposal (SMC sweep-based bias)
- `[[bias-filter-net-negative]]` — F28 single-seed discovery memo
- `[[project-filter-sweep-workflow]]` — branch → BT pre/post → user sign-off → ship-or-stash
- `[[feedback-filter-measurement-gate]]` — every gate change runs 21yr BT pre/post
- `[[feedback-selective-ship-pattern]]` — per-system ship decisions (F31 only relevant for Gold systems)
