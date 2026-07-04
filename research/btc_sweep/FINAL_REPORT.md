# BTC Optimal Strategy — Final Research Report

**Date:** 2026-07-04 · **Branch:** `research/btc-sweep`
**Data:** BTCUSDT 1m spot (Binance public dumps), 2019-10 → 2026-05, 6.7yr, 3.50M bars.
Integrity: monotonic, 0 dups, 0 NaN, 18 gaps/6.7yr. `research/data/btc/BTCUSDT_M1.parquet`.
**Rigor:** strict causality (harness hard-tested 0 look-ahead, all features shift(1)-lagged),
cost = 12 bps round-trip, adversarial battery (delay/WF/bootstrap/B&H). No phantom numbers.

## Headline result

**BTC intraday (M5) has NO tradeable edge — honest zero.** BTC's edge lives on
**higher timeframes, long-biased trend/momentum.** The optimal survivor:

### ★ WINNER — H4 Momentum-Long
`H4 · 20-bar ROC > +5% (lagged) → long · SL 1.5×ATR · TP 2R · 30-bar (5-day) horizon`

| Metric | Value |
|---|---|
| Trades | 383 (58/yr) over 6.6yr |
| Net | +134 R |
| PF | **1.63** |
| MAR | 1.27 |
| Positive years | 5/8 |
| +1-bar delay | PF 1.54 (survives — not fragile) |
| Walk-forward | IS PF 1.58 / **OOS PF 1.71** (edge holds out-of-sample) |
| Bootstrap P(net≤0) | **0.000** |
| **vs Buy&Hold** | strat **+266% @ 15% maxDD** vs B&H +755% @ **77% maxDD** |
| **Risk-adjusted (ret/maxDD)** | **17.6 vs 9.8 — beats B&H ~1.8×** |

The strat gives up raw return but cuts max drawdown from a portfolio-ending 77%
to a survivable 15%, and wins decisively on risk-adjusted terms. That is the real
value of a systematic BTC long overlay vs just holding.

## Full survivor set (all passed adversarial core checks: delay + WF-OOS + bootstrap)

| Strategy | PF | MAR | OOS PF | P(net≤0) | trades/yr | pos yrs |
|---|---|---|---|---|---|---|
| H4 mom-L thr5% sl1.5 tp2R  | 1.63 | 1.27 | 1.71 | 0.000 | 58 | 5/8 |
| H4 mom-L thr10% sl1.5 tp3R | 2.12 | 0.69 | 3.80 | 0.000 | 21 | 5/8 |
| H4 macross-L 20/100 tp4R   | 1.79 | 1.54 | 1.77 | 0.011 | 13 | 7/8 |
| D1 mom-L thr20% sl1.5 tp3R | 2.45 | 1.34 | 2.93 | 0.003 | 9  | 5/6 |

Robustness signal: the H4-momentum-long edge is positive across a *wide* band of
thresholds/stops/TPs (not a lucky single config) — the hallmark of a real edge.

## Structural finding (why it works)

**Long works, short doesn't.** Every short-side config across every timeframe lost
or was marginal; longs were consistently positive. BTC is a secular long-drift asset
with momentum persistence on H4+. Trend/momentum LONG rides that; shorts fight it.

## What was rejected (honest)

- **All M5 intraday** (180 configs, 4 families): gross PF ≈ 1.02 (coin-flip) even at
  ZERO cost → no edge; cost just confirms the loss. The XAU fib/EMA/breakout survivors
  do NOT transfer to BTC M5.
- **Mean-reversion** (opposite hypothesis, 8 configs): PF 0.64–0.82, also fails.
- **Donchian breakout** on HTF: too few triggers on BTC (mostly ZERO/degenerate).
- **All shorts**: no edge.

## Caveats / next steps before live

1. **Low frequency** (9–58 trades/yr) — fails the intraday 200/yr gate BY DESIGN; this
   is a swing/position overlay, not a scalper. Size accordingly.
2. **5/8 positive years** on the top pick — the 3 down years were chop (2019 stub, plus
   two sideways stretches). The macross variant is steadier (7/8) at lower frequency.
3. **Spot data / no funding** — a perp implementation carries funding cost not modelled;
   spot or dated-futures avoids it. 12bps cost is conservative for spot.
4. **Recommend**: ensemble the H4-mom-L + H4-macross-L (freq + smoothness) as the
   production BTC long overlay; port to bt_engine with the same causal discipline as Fib V2.

Artifacts: `research/btc_sweep/{sweep.py, sweep_htf.py, adversarial.py, FINDINGS.md}`,
`htf_leaderboard.csv`, `adversarial_results.csv`, `MASTER_LEADERBOARD_BTC.csv`.
