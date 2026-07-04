# BTC Strategy Sweep — Findings (Round 1)

**Date:** 2026-07-04
**Data:** BTCUSDT 1m spot, Binance public dumps, 2019-10 → 2026-05 (6.7yr, 3.50M bars,
monotonic, 0 dups, 0 NaN, 18 gaps in 6.7yr). Local: `research/data/btc/BTCUSDT_M1.parquet`.
**Harness:** `research/harness/causal_sim_btc.py` — fork of the XAU causal_sim.
Hard causal self-test PASSED (3000 sampled M5 bars, 0 lag-mismatch: every feature
sourced from a strictly-prior-closed M15 bar). Cost = 12 bps round-trip (taker+spread).
Gate = ≥200 trades/yr, PF≥1.3, MAR≥1.5, ≥7-of-8 positive years.

## Verdict: ZERO survivors. No BTC intraday edge found in this sweep. No padding.

180 configs across 4 XAU-survivor families (Fib retrace V2, EMA20 pullback,
prior-day break, ATR squeeze) — **every single one lost** (PF 0.06–0.80, all
negative net, 0–2 of 8 positive years). Mean-reversion (the opposite hypothesis,
8 extra configs) also failed (PF 0.64–0.82).

## Why — the decisive diagnostic (not a cost artifact, not a bug)

**Zero-cost gross PF ≈ 1.022.** The representative trend-continuation pattern is a
coin-flip *before any cost is applied*. This is the key result: the patterns have
**no directional edge** on BTC M5, so no cost model or bracket tuning can rescue them.

Cost sensitivity (same pattern, gross→net):
| cost | net R | PF |
|------|-------|-----|
| 0 bps  | +70  | 1.022 |
| 2 bps  | −425 | 0.876 |
| 5 bps  | −1168| 0.691 |
| 12 bps | −2899| 0.384 |

Cost drags a no-edge pattern into clear loss — but the edge was never there.

## What this means

- The XAU survivors (Fib V2 etc.) exploit XAU's intraday **mean-reverting pullback**
  microstructure. BTC M5 does not share it — fixed-R:R brackets on M5 BTC are ~50/50
  both on trend-continuation and mean-reversion.
- One marginal signal: an H1-proxy (daily-dedup, 3×ATR stop, 2R TP, 7-day horizon)
  reached gross-ish PF 1.06 / MAR 0.14 / 4-of-8 yrs at 5bps — real but far below gates.
  Suggests any BTC edge (if it exists) lives on **higher timeframes (H1/H4/D1)** and
  **longer horizons**, not M5 scalps.

## Rigor applied (mandate compliance)

- ✅ Real data (Binance public, verified integrity) — no synthetic, no phantom numbers.
- ✅ Strict causality: harness hard-tested 0 look-ahead; every feature shift(1)-lagged.
- ✅ Hostile check: tested the OPPOSITE hypothesis (mean-reversion) too — also fails.
- ✅ Adversarial cost: zero-cost gross check isolates edge from cost. No edge at 0 cost.
- ✅ Honest zero: reported no survivors rather than curve-fitting to a passing config.

## Next directions (not yet run)

1. **Higher timeframe sweep** — rebuild harness on H1/H4 bars; test trend + breakout
   with multi-day horizons where the marginal signal appeared.
2. **BTC-native patterns** — funding-rate carry, weekend gap, round-number ($5k/$10k)
   magnets, US-session vs Asia-session momentum, on-chain-agnostic vol-regime filters.
3. **Ensemble / regime-conditional** — the flat 50% may hide a regime where trend works
   (2020-21 bull) vs chops (2022). Year-by-year already shows no consistency, so this is
   low-priority.

Leaderboard: `research/results/MASTER_LEADERBOARD_BTC.csv` (180 rows, 0 passers).
