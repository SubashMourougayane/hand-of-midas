# Phase 0 — Calibration: what stop-run + reversal looks like ON THIS DATA

> Written 2026-06-21 IST by the assistant under D-004 override.
>
> **This is a CALIBRATION doc, not a marking pass.** Zero marks have been written. The user must read this and either approve, reject, or edit the calibration framing BEFORE any mark gets saved.
>
> Per D-004 risk #1 (vision model bias toward trained patterns) and risk #2 (contamination from prior broken strategy): the assistant has been exposed to ICT/SMC content during training and to the production strategy parameters. Anything written below could be unconsciously echoing either source. The user is the failsafe.

---

## What I looked at

Sample of 4 PNGs (chronologically spaced across the dev window) from `R&D/phase_0_observations/screenshots/`:

| Date | Day | Bars | Range | Regime context |
|---|---|---:|---:|---|
| 2019-09-27 | Fri | 417 | $1.98 | Pre-COVID, normal vol |
| 2019-10-01 | Tue | 416 | $1.68 | Pre-COVID, normal vol |
| 2020-04-14 | Tue | 420 | $2.94 | Mid-COVID, prices ~$30 (oil glut) |
| 2022-03-04 | Fri | 420 | $9.34 | Russia/Ukraine spike, prices ~$115 |
| 2023-05-25 | Thu | 419 | $3.26 | Normalised, prices ~$76 |

I deliberately stopped at 5 charts (not all 41). The point of calibration is to **describe what I'm looking for**, not to find more examples that fit. If I look at all 41 first, I'm pre-pattern-matching against my own emerging "definition" — which is the bias the override doc explicitly warned about.

---

## What I think looks like a "real" institutional stop-run + reversal — IN MY OWN WORDS

A stop-run-plus-reversal, by my reading, has FIVE visible features on the M3 chart:

### 1. A consolidation BEFORE the sweep

Some price band (let's call it 30 minutes to 4 hours) where price oscillates inside a clear high and low. The consolidation should LOOK contained — multiple touches at both ends rejecting back toward the middle. Not just "price was sideways"; specifically, "price tried to break and was rejected, more than once, on at least one side."

What I am NOT calling consolidation:
- A 1-hour drift with a single touch at each extreme
- A trending bar sequence whose retracements I could call a range if I squint
- The first hour of the trading day before any session has set a level

### 2. A wick that POKES through a range edge

The sweep candle has a **clearly visible wick** that extends beyond the consolidation high (or low) by an amount that looks deliberate — comparable to the consolidation's typical bar size, not just a 1-tick noise probe.

What I am NOT calling a sweep:
- Price drifts above the high and stays there (that's a breakout, not a sweep)
- A small wick that's within the noise of the consolidation's prior wicks
- A wick that pokes and then price keeps trending (no rejection)

### 3. The sweep candle CLOSES BACK INSIDE the range

Critical: the sweep candle's BODY closes inside the previous range. The wick's the lie; the close is the truth. If the candle pokes above the range and closes above the range, that's a breakout — different setup, not what we're after.

### 4. A reversal candle WITHIN THE NEXT FEW BARS (5-15 M3 bars = 15-45 minutes)

Within ~30 minutes of the sweep, I expect to see a clear reversal candle: an engulfing, a strong opposite-direction body, or a momentum shift. Not "eventually price reverses an hour later" — that's hindsight pattern matching. The reversal should be timely and visible.

### 5. The follow-through has structure

After the reversal candle, price moves in the reversal direction by something at least comparable to the consolidation's range — not just a tiny bounce that gets absorbed. This is the part where you'd actually be in the trade making money.

---

## What I think looks like a FAKE stop-run (the "I want to mark this but shouldn't" trap)

These are patterns I noticed myself starting to flag as setups, then realised were probably noise:

### Trap A: tiny wick after low-volatility morning

In the 2019-09-27 chart, between roughly 08:00 and 11:00 UTC, price ranged ~$0.30 in a tight band, then a wick poked just outside and price reversed. **It looks like the pattern. It is also exactly what random walk does in a low-vol period.** Without volume confirmation, without prior range significance (was that range a real level or just where price happened to pause?), I can't distinguish this from noise. Reject.

### Trap B: fake reversal at intraday high

2020-04-14 around 11:00 UTC — price ran to a local high, reversed sharply on what could be called an "engulfing." But the prior structure shows a downtrend with multiple lower-highs. The "reversal" is just a continuation of an already-established downtrend. The wick poked nothing of significance. Reject.

### Trap C: high-vol day, every wick looks like a sweep

2022-03-04 (Russia spike, $9.34 daily range) — almost every hour has wicks that LOOK like sweeps. They're not. When the underlying noise is $1+ per hour, a 50-cent wick is sub-noise. **High-vol days are easier to mark and harder to be right.** The pattern needs to scale to the volatility, not be evaluated in absolute dollars.

### Trap D: the "good enough" candle

I keep wanting to mark candles that have 3 of the 5 features but not all 5. ("Wick is small but the reversal is strong, so probably real.") This is exactly how the broken strategy generated 2,645 trades over 7 years. Loose criteria + lots of opportunities = fake edge. **If a candle doesn't have all 5 features clearly, it's not a candidate.**

---

## What I CANNOT see from M3 charts alone

Things I want to know that aren't visible to me on these PNGs:

1. **Volume.** Real institutional sweeps come with a volume signature — a spike on the sweep bar, followed by reversal-direction volume. The PNGs show OHLC only. I don't have volume here.
2. **Order book / depth-of-market.** Where are the resting limit orders? A "stop run" only makes sense if there were stops to run.
3. **Prior-day or prior-week structure.** A sweep of the previous day's high/low is a textbook ICT setup. From an M3 chart of one day, I can't see "what was Wednesday's high" without adding context.
4. **News calendar.** A price move around 12:30 ET on a non-empty calendar day has a different meaning than the same move on a quiet day.

I'm flagging these so the user knows my visual analysis is GENUINELY LIMITED and any marks I make are constrained by what's visible on the M3-only PNG.

---

## My proposed marking criteria (DRAFT — needs user sign-off)

If we proceed to marking, I'll mark a candle as a **candidate stop-run** if and only if it meets ALL of:

1. ✅ Prior consolidation visible: ≥ 30 minutes of bounded price action with at least 2 rejected touches on the swept side
2. ✅ Sweep wick: extends beyond the consol edge by ≥ 30% of the consol's range (so a $0.50 consol needs at least a $0.15 wick)
3. ✅ Body closes inside the consol range (the close is on the inside of the swept edge)
4. ✅ Within 15 M3 bars (45 minutes) after the sweep, a clear reversal candle (engulfing or strong opposite body)
5. ✅ Follow-through: price moves at least 50% of the consol range in the reversal direction within the next hour

Plus a confidence score 1-5 where:
- **5** = textbook, all 5 features unambiguous
- **4** = all 5 present, but one of them is borderline (e.g., wick is right at 30%)
- **3** = 4 of 5 strong, 1 weak — borderline accept
- **2** = 4 of 5 — borderline reject
- **1** = 3 of 5 — reject

Per the user's "mark conservatively" instruction, I'll only save marks at **confidence ≥ 4**. Anything 3 or below is rejected.

---

## What I want the user to push back on

These are my self-flags — places I might already be biased:

- **The "5 features" framing has 5 things in it, and the broken strategy has 5 parameters (min_range, sweep_threshold, sl_buffer, tp_structure_buffer, engulfing_window_hours).** Coincidence? Or am I unconsciously reproducing the broken strategy's structure with different words?
- **My "30 minutes to 4 hours" consolidation duration is pulled from where exactly?** I think I'm pattern-matching against ICT-content-typical consolidation durations, not from the actual data.
- **My "30% of consol range" sweep threshold is just made up.** It's a number that sounds reasonable. It is not derived from anything observable in the 5 PNGs I looked at.
- **My "follow-through ≥ 50% of consol range" is borrowed from the spec's `reward >= risk * 0.80`.** That's clearly contamination.

If you tell me to throw out this calibration doc and start over with stricter discipline, that's fair. If you tell me to proceed with these criteria, that's also fair — but with eyes open about the contamination risks above.

---

## What happens next (pending user approval)

If you approve this calibration:

1. I look at all 40 clean dev-window PNGs (skipping 2019-09-26 mixed-cadence)
2. I apply the 5-feature criteria + confidence ≥ 4 threshold
3. I write each candidate mark to `manual_marks.jsonl` with:
   - sweep_ts (M3 timestamp of the sweep candle's open)
   - direction (long or short)
   - confidence (1-5)
   - notes (free-text: which features were present, what the consol size was, what the follow-through was)
   - screenshot_path (for audit trail back to the exact PNG I saw)
4. I stop at 20 candidates OR 40 days reviewed, whichever first
5. You review and reject/keep/edit each

If you reject this calibration:

- Tell me what's wrong with it
- I rewrite or we abandon B1 and you mark yourself

**I will not save any mark until you explicitly approve this calibration doc.**

Sign-off section (filled in by user):

```
[ ] Approve as written — proceed to marking
[ ] Approve with edits — see notes:
[ ] Reject — start over
[ ] Reject — abandon B1, do A
```
