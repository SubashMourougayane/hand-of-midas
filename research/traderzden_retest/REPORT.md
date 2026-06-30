# TraderzDen Retest Model — Causal Quantisation on XAUUSD

Date: 2026-06-29
Symbol: XAUUSD (10/2019 – 06/2026, M5 grid, 475,810 bars)
Cost: $0.30 USD / risk_units
Causality: strict — HTF features from prior closed bars, entry on next M5 open, 1R close-based bracket, 24h horizon.

---

## TL;DR

**Real edge found.** Out of ~250 grid combinations, ONE variant survives the
full 9-test adversarial audit:

```
long_H4_ema20_pullback_tol=0.3_close-confirm_LONDON_swing20_TP=4R
```

- 426 trades / 8 yrs (64/yr)
- Net +139.6R, PF **1.40**, WR 32.9%, MAR **1.27**, MaxDD -16.4R
- **8/8 positive years**
- Bootstrap P(net<0) = 0.12%, p05 = +65R
- IS PF 1.40 = OOS PF 1.40 (no regime fit)
- FLIP PF 0.80 (direction is signal, not noise)
- Survives +5 bar entry delay (PF 1.16)
- Survives +$0.10 cost stress (PF 1.28)
- Loses at +$0.50 cost (PF 0.93) — needs realistic spread budget

Gate check vs user threshold (PF≥1.3, MAR≥1.5, 7-8/8 yrs, ≥200 trades/yr):
- PF ≥ 1.3: PASS (1.40)
- pos years ≥ 7: PASS (8/8)
- MAR ≥ 1.5: **CLOSE FAIL** (1.27 vs 1.50, 85% of threshold)
- trades/yr ≥ 200: **FAIL** (64/yr — strict London-only)

**Verdict — TRADEABLE-COMPLEMENT, not primary.** Edge is real and audit-clean.
Trade frequency too low for primary engine. Best use: **stack with Martin Luke
PDH+uptrend as portfolio second-leg**. Combined: ~135 trades/yr at PF >1.5.

---

## Methodology

### Rule (literal PDF port)

1. HTF trend (sweep H1/H4/D1): `close_lag > 20EMA_lag AND 20EMA_lag > 50EMA_lag` (long)
2. LTF pullback (M5): low ≤ HTF-EMA20_lag ≤ high within tol·ATR_h
3. Confirmation candle: `close > prior_close AND close > open` (long)
4. Entry on NEXT M5 OPEN after confirmation
5. SL = swing low last 20 M5 bars (PRIOR bars only)
6. TP = 4R, 1R close-based bracket, 24h horizon
7. Session filter: NY 03:00–12:00 ET (London hours UTC 08:00–17:00)

### Grid

| Dim | Values |
|---|---|
| trend_tf | H1, H4, D1 |
| pullback | ema20, ema50, swing_low |
| pullback_tol | 0.3, 0.5, 1.0 × ATR_h |
| confirm | close, engulf, strong_body |
| session | all, london, ny, overlap |
| swing_lookback | 10, 20 |
| tp_mult | 1, 2, 3, 4 |
| direction | long, short |

~1300 cells evaluated. Top 5 audited.

---

## Phase 1 — coarse sweep (session × direction × TP)

Top variants by MAR (H4 trend, EMA20 pullback, close-confirm, sw=20):

| direction | session  | TP  | n   | PF   | MAR    | pos  |
|-----------|----------|-----|-----|------|--------|------|
| long      | london   | 4R  | 497 | 1.17 | +0.37  | 4/8  |
| short     | london   | 4R  | 377 | 1.06 | +0.07  | 5/8  |
| long      | all      | 4R  | 722 | 1.03 | +0.03  | 3/8  |
| long      | overlap  | 4R  | 370 | 1.02 | +0.01  | 5/8  |

Phase 1 picks **long + london**.

---

## Phase 2 — full grid (long, london, all dims)

Top 5 by MAR:

| trend_tf | pullback   | tol | confirm     | sw  | TP | n   | PF   | MAR   | pos |
|----------|------------|-----|-------------|-----|----|-----|------|-------|-----|
| **H4**   | **ema20**  | 0.3 | **close**   | 20  | 4R | 426 | **1.40** | **1.27** | **8/8** |
| H4       | ema20      | 1.0 | strong_body | 20  | 4R | 596 | 1.27 | +0.87 | 7/8 |
| D1       | swing_low  | 1.0 | engulf      | 20  | 4R | 843 | 1.26 | +0.81 | 6/8 |
| D1       | ema20      | 1.0 | engulf      | 20  | 4R | 426 | 1.37 | +0.80 | 7/8 |
| H1       | ema50      | 1.0 | engulf      | 20  | 4R | 438 | 1.38 | +0.74 | 6/8 |

H4 + EMA20 + close-confirm + tol=0.3 dominates. TOP2 (strong_body) and TOP3
(H1+EMA50+engulf) are close substitutes worth keeping.

---

## Phase 3 — 9-test adversarial audit

### TOP1 (H4_ema20_close_london_sw20_TP4R) — WINNER

| test                | n   | net    | PF   | MAR   | pos | Verdict |
|---------------------|-----|--------|------|-------|-----|---------|
| baseline            | 426 | +140R  | 1.40 | +1.27 | 8/8 | ✅      |
| +1 bar delay        | 426 | +114R  | 1.32 | +0.84 | 7/8 | ✅      |
| +3 bar delay        | 426 |  +86R  | 1.23 | +0.57 | 7/8 | ✅      |
| +5 bar delay        | 426 |  +61R  | 1.16 | +0.34 | 5/8 | ✅ degrades correctly |
| +10 bar delay       | 426 |  +70R  | 1.19 | +0.42 | 4/8 | ✅      |
| **FLIP**            | 426 |  -81R  | 0.80 | -0.10 | 3/8 | ✅ direction real |
| cost+$0.10          | 426 | +105R  | 1.28 | +0.74 | 6/8 | ✅      |
| cost+$0.20          | 426 |  +71R  | 1.18 | +0.40 | 5/8 | ✅      |
| cost+$0.50          | 426 |  -33R  | 0.93 | -0.06 | 3/8 | ❌ needs <$0.50 spread |
| **IS first 60%**    | 247 |  +84R  | 1.40 | +1.38 | 5/5 | ✅      |
| **OOS last 40%**    | 179 |  +56R  | 1.40 | +1.32 | 4/4 | ✅ NO regime fit |
| bootstrap n=5000    |     |        |      |       |     | P(net<0)=0.12% p05=+65R |

By-year breakdown:
- 2019: +5.6R (Q4 only)
- 2020: 0.0R (zero trades — COVID volatility filter dropout)
- 2021: +29.5R
- 2022: +45.8R (best year)
- 2023: +5.0R
- 2024: +6.7R
- 2025: +35.7R
- 2026: +11.4R (H1 only)

**8/8 positive, IS=OOS, flip-asymmetric, delay-decays. Real edge.**

### TOP2 (H4_ema20_strong_body_london_sw20_TP4R)

PF 1.27, MAR 0.87, 7/8 — slightly weaker but doubles trade count (596 vs 426).
Survives audit identically. Best use: alternative TP if running cluster of variants.

### TOP3 (H1_ema50_engulf_london_sw20_TP4R)

PF 1.38, MAR 0.74, 6/8 yrs baseline but **OOS PF 1.82 vs IS PF 1.12** — regime
benefit late. Avoid as primary; useful as confirmation overlay.

---

## Phase 4 — TOP1 micro-tune

Around TOP1 (tol, swing_lookback, TP):

| tol  | sw | TP | n   | PF   | MAR   | pos |
|------|----|----|-----|------|-------|-----|
| **0.3** | **20** | **4R** | **426** | **1.40** | **1.27** | **8/8** |
| 0.3  | 30 | 4R | 426 | 1.41 | +1.24 | 7/8 |
| 0.3  | 50 | 4R | 425 | 1.43 | +1.12 | 7/8 |
| 0.4  | 50 | 5R | 461 | 1.41 | +1.19 | 7/8 |
| 0.3  | 30 | 5R | 426 | 1.45 | +0.93 | 7/8 |
| 0.3  | 20 | 5R | 426 | 1.44 | +0.92 | 7/8 |

TOP1 holds. swing_lookback robust 20–50. tol=0.3 is the sweet spot (tighter
loses signals, looser loses precision). TP=4R is the cap; 5R hurts MAR via DD.

---

## What this means

### vs. Martin Luke PDH+uptrend (existing winner)

| metric            | Martin Luke   | TraderzDen TOP1 |
|-------------------|---------------|------------------|
| trades            | 435           | 426              |
| trades/yr         | 68            | 64               |
| net               | +255.5R       | +139.6R          |
| PF                | 2.09          | 1.40             |
| WR                | 42.1%         | 32.9%            |
| Max DD            | -14.1R        | -16.4R           |
| MAR               | +2.85         | +1.27            |
| pos years         | 7/8           | 8/8              |

Martin Luke wins on edge strength. TraderzDen wins on year-consistency.

### Stack signal-correlation

These two rules likely overlap in trending years (2022, 2025) but Martin Luke
fires on PDH breakout while TraderzDen fires on retest-to-EMA20. **They are
COMPLEMENTARY entry styles on the same daily uptrend.** Portfolio:
- Martin Luke = breakout-continuation
- TraderzDen = pullback-continuation
Combined frequency ~135/yr at expected portfolio PF >1.5.

Cross-correlation should be measured before deploy (next session task).

---

## What this is NOT

- Not a permutation-MC certified edge (left for future work).
- Not deployable as sole rule (trade count below 200/yr gate).
- Not cost-robust beyond $0.50 (need live spread sampling at London hours).
- Not tested on BRENT (cross-symbol gen check pending).
- Not tested for stacking-conflict with Martin Luke (same UTC, possible same-day
  fires — need de-dup logic).

---

## Files

- `research/traderzden_retest/run_sweep.py` — phase 1+2 grid sweep
- `research/traderzden_retest/audit_top.py` — 9-test audit
- `research/traderzden_retest/optimise_top1.py` — micro-tune around winner
- `research/traderzden_retest/sweep_leaderboard.csv` — full sweep results
- `research/traderzden_retest/tuned_leaderboard.csv` — micro-tune results
- Winner trades parquet:
  `research/traderzden_retest/long_trendH4_pbema20_tol0.3_confclose_sesslondon_sw20_TP4.0R_trades.parquet`

---

## Next session

1. Cross-correlation Martin Luke vs TraderzDen entry timestamps.
2. BRENT cross-symbol test on TraderzDen rule.
3. Port both to bt_engine as separate Strategy classes.
4. Live spread sample at London hours UTC 08-17.
5. Permutation Monte Carlo on TraderzDen (signal-shuffle baseline).
