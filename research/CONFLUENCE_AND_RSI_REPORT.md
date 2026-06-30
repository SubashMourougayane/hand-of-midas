# Quantising PDF1 (XAUUSD Confluence) + PDF2 (RSI Divergence)

Date: 2026-06-29
Symbol: XAUUSD (10/2019–06/2026, M5 grid)
Cost: $0.30 USD / risk_units
Causality: strict — all features from CLOSED prior bars, entry on next M5 OPEN, 1R close-based bracket, 24h horizon.

---

## TL;DR

**Both strategies FAIL the gate.** No edge survives the 9-test adversarial
audit. Best variant (RSI Div M15 + H1 zone, TP=4R) has PF 1.14, MAR 0.29,
4/8 positive years, IS PF 0.98 vs OOS PF 1.46 — regime luck on out-of-sample,
not real edge.

The user's gate: `PF >= 1.3, MAR >= 1.5, 7-8/8 positive years, >= 200 trades/yr`.
Neither candidate clears.

---

## Strategy A — XAU Confluence (PDF1)

### Rule (quantised literally)
- Time: NY-London overlap, UTC 13:00–17:00.
- ORB15: high/low of [13:00, 13:15) UTC, valid from 13:15.
- VWAP_session: cumsum(typ * vol) / cumsum(vol) per UTC day, lagged 1 M5.
- VAH/VAL_prev: prior-day value-area from M5 volume profile (70% area).
- Long trigger: close > ORH AND close > VWAP_lag AND close > VAH_prev AND
  body > mean(H-L, last 5 closed bars) AND volume > mean(vol, last 3 closed bars).
- Short = mirror.
- SL = ORH − 0.5·ORwidth (long) / ORL + 0.5·ORwidth (short); 1R.
- Entry on NEXT M5 open after trigger bar closes.

### Headline (all TP variants)

| variant            | n   | /yr | net   | WR    | PF   | MAR    | pos    |
|--------------------|-----|-----|-------|-------|------|--------|--------|
| long  TP=1.5R      | 587 |  88 | -213R | 39.2% | 0.55 | -0.15  | 0/8    |
| long  TP=2.0R      | 587 |  88 | -182R | 34.4% | 0.65 | -0.15  | 0/8    |
| long  TP=3.0R      | 587 |  88 | -108R | 29.0% | 0.81 | -0.14  | 0/8    |
| short TP=1.5R      | 566 |  85 | -138R | 42.4% | 0.67 | -0.14  | 1/8    |
| short TP=2.0R      | 566 |  85 |  -81R | 38.7% | 0.82 | -0.11  | 3/8    |
| short TP=3.0R      | 566 |  85 |  +34R | 34.1% | 1.07 | +0.11  | 6/8    |

### Audit verdict (short TP=3.0R, the best variant)

| test               | n   | net   | WR    | PF   | MAR    | pos  |
|--------------------|-----|-------|-------|------|--------|------|
| baseline           | 566 |  +34R | 34.1% | 1.07 | +0.11  | 6/8  |
| +1 bar             | 566 |  +34R | 34.1% | 1.07 | +0.16  | 5/8  |
| +5 bars            | 566 |  -50R | 30.4% | 0.90 | -0.08  | 4/8  |
| **FLIP**           | 566 |  +46R | 34.6% | **1.09** | +0.18 | 6/8 |
| cost+$0.10         | 566 |  -24R | 34.1% | 0.95 | -0.05  | 5/8  |
| cost+$0.20         | 566 |  -81R | 34.1% | 0.85 | -0.10  | 2/8  |
| IS (60%)           | 365 |  +16R | 35.1% | 1.05 | +0.11  | 3/5  |
| OOS (40%)          | 201 |  +18R | 32.3% | 1.11 | +0.28  | 3/4  |

**Verdict — KILLED**: The flipped direction posts the SAME PF as the rule (1.09 vs
1.07). The signal does not encode direction. Adding $0.10 spread takes PF
below 1.0. No real edge.

---

## Strategy B — RSI Divergence (PDF2)

### Rule (quantised literally)
- RSI(14) on close, lagged 1 bar.
- Pivots: right=2, left=2 → confirmed at bar i+2 (acted from bar i+3).
- Bullish: confirmed price LL vs prior confirmed pivot low AND
  RSI Higher Low at that pivot.
- Optional zone filter: pivot price within 0.5·ATR of an older support pivot.
- Confirmation candle: first bullish close > prior close after pivot confirmed.
- Entry on NEXT M5 open after confirmation. SL = pivot low − 0.01 tick.

### M5 results (literal PDF)

| variant                | n     | /yr | net    | PF   | MAR   | pos  |
|------------------------|-------|-----|--------|------|-------|------|
| long zone   TP=4R      |  4192 | 625 |  -116R | 0.97 | -0.05 | 4/8  |
| long nozone TP=4R      |  6247 | 930 |  -118R | 0.98 | -0.04 | 4/8  |
| short zone  TP=4R      |  4428 | 660 |  -561R | 0.87 | -0.11 | 2/8  |

M5 is dead.

### M15 + H1-zone (closer to PDF intent: "1H/4H zones")

| variant                       | n    | /yr | net    | WR    | PF   | MAR   | pos  |
|-------------------------------|------|-----|--------|-------|------|-------|------|
| long M15+H1zone TP=1.0R       | 1153 | 172 |  -120R | 50.8% | 0.81 | -0.13 | 2/8  |
| long M15+H1zone TP=2.0R       | 1153 | 172 |    +5R | 38.1% | 1.01 | +0.01 | 4/8  |
| long M15+H1zone TP=3.0R       | 1153 | 172 |   +87R | 30.9% | 1.10 | +0.23 | 4/8  |
| **long M15+H1zone TP=4.0R**   | 1153 | 172 |  +130R | 26.3% | **1.14** | +0.29 | 4/8 |

### Audit verdict (M15+H1zone long TP=4R, the BEST variant)

| test               | n    | net   | WR    | PF   | MAR    | pos  |
|--------------------|------|-------|-------|------|--------|------|
| baseline           | 1153 | +130R | 26.3% | 1.14 | +0.29  | 4/8  |
| +1 bar             | 1153 | +196R | 27.4% | 1.21 | +0.53  | 7/8  |
| +5 bars            | 1152 | +267R | 28.6% | 1.29 | +0.66  | 7/8  |
| +10 bars           | 1152 | +318R | 29.7% | 1.35 | +0.95  | 8/8  |
| FLIP               | 1153 |  -45R | 22.9% | 0.95 | -0.05  | 3/8  |
| cost+$0.10         | 1153 |  +83R | 26.3% | 1.08 | +0.14  | 4/8  |
| cost+$0.20         | 1153 |  +35R | 26.3% | 1.03 | +0.04  | 4/8  |
| **IS (60%)**       |  742 |  -11R | 24.3% | **0.98** | -0.04 | 2/5 |
| OOS (40%)          |  411 | +141R | 29.9% | 1.46 | +1.99  | 3/4  |

**Verdict — KILLED, despite tempting numbers.**

Three independent fails:
1. **IS loses money.** PF 0.98 over 2019–2023. The entire net of +130R comes
   from 2024-onward gold uptrend. Curve-fit to regime, not a rule with edge.
2. **Direction half-leaks** but rule misses fast entries. Delay +1/+3/+5/+10
   ALL improve PF (1.14 → 1.35). Real edges *decay* with delay. This pattern
   gets better when entered later — meaning the confirmation candle is an
   anti-signal and the "edge" is just being long in a gold rally.
3. **Cost stress**: $0.10 extra spread kills 64% of net (130 → 83R). At
   realistic XAU spread variance ($0.20+ outside Lon-NY overlap) the edge
   evaporates.

Pattern is not deployable.

---

## Why both fail (root cause analysis)

### Confluence (PDF1)
The PDF imagines that VWAP + VAH + ORB + body-momo + vol-surge stack
multiplicatively. Reality: after the +0.30 cost and the post-2020 XAU
microstructure (tight spreads, range-bound NY-London overlap most days),
the multi-filter setup fires ~88 times/yr but the win rate caps at 30%
with no asymmetric R-multiple. **Filters cancel rather than compound.**

The flip-test invariance is the kill: a long that wins 29% of the time and
a short under the SAME setup that wins 35% of the time means the trigger
encodes regime exposure, not directional information.

### RSI Divergence (PDF2)
RSI HL/LH at a "support zone" is a pattern human eyes love but the signal
is statistically empty on XAU intraday. The pivot+zone filter only narrows
to 1153 setups over 6.4 yr (172/yr) — sparse, and the IS period (2019-2023)
loses outright. The 2024-2025 win is the same gold rally that makes
Martin Luke PDH look strong; without the trend filter, RSI Div is a coin flip.

---

## What this means for the project

These rules are NOT going into bt_engine. Martin Luke PDH+uptrend (already
quantised, audited, surviving 9/9 tests) remains the only deployable
candidate.

If user wants more candidates, next-best avenues:
- **Brent cross-symbol test of Martin Luke** — confirms generalisation or
  reveals XAU-specific microstructure.
- **Inside-day breakout on M30** with strict prior-day filter (not tested).
- **NY-lunch (16-18 UTC) mean-reversion under range-day filter** — momentum
  patterns fail here; mean-rev may not.

---

## Files

- `research/confluence_xau/run_confluence.py` — strategy A
- `research/rsi_divergence/run_rsi_div.py` — strategy B M5
- `research/rsi_divergence/run_rsi_div_m15.py` — strategy B M15+H1zone
- `research/audit_confluence_rsi.py` — 9-test audit harness
- Trades parquets: `research/confluence_xau/*.parquet`, `research/rsi_divergence/*.parquet`
- Leaderboard appended at `research/results/MASTER_LEADERBOARD.csv`
