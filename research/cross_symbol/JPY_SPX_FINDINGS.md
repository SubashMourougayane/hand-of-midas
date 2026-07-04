# Cross-Symbol: USD/JPY + SPX500 — Fib V2 A+D (2026-07-05)

Same Fib V2 A+D params as XAU (H1 pivots lb5, regime bull/bear-strong, ext 1.618,
sl 0.02, hold 72h, M5 entry). Data: OANDA practice (token in GoldDigger/.env),
2019-10 → 2026-06. Strictly causal (same harness as XAU/EUR/GBP).

## Verdict: neither survives as A+D. SPX long-only (leg A) is the best non-XAU find.

### USD/JPY
| Leg | n | /yr | net R | PF | MAR | WR | pos yrs |
|-----|---|-----|-------|-----|-----|-----|---------|
| A · Long  | 1063 | 159 | +232.8 | 1.29 | 0.46 | 28.9% | 5/8 |
| D · Short |  525 |  88 | -148.0 | 0.67 | -0.16| 19.2% | 0/6 |
| A+D combo | 1588 | 236 |  +84.8 | 1.07 | 0.09 | 25.7% | 2/8 |
- Short leg BROKEN (0/6 yrs). Combo dead (PF 1.07, 2/8). Regime-driven: +179R in
  2022 (yen collapse) + +102R 2026 carried it; negative 5/8 years.
- Cost-fragile: PF 1.07→0.96 at +2pip.
- $1k/3% monthly reset: skim $21,154 net +$9,741 41% green — but lumpy (2022+$8,580,
  2026+$4,669 vs 4 negative years). NOT an edge, a carry-unwind lever.

### SPX500  ← best non-XAU
| Leg | n | /yr | net R | PF | MAR | WR | pos yrs |
|-----|---|-----|-------|-----|-----|-----|---------|
| A · Long  | 1073 | 160 | +228.9 | 1.29 | 0.55 | 29.2% | **7/8** |
| D · Short |  194 |  35 |  -53.6 | 0.69 | -0.14| 13.9% | 3/5 |
| A+D combo | 1267 | 189 | +175.2 | 1.18 | 0.21 | 26.8% | **6/8** |
- Long leg A is legit: PF 1.29, **7/8 pos years** (only 2022 red), cost+delay robust
  (+10 bar delay PF 1.13, cost-stress flat). Short leg rare+broken (SPX = uptrend).
- Combo PF 1.18 / 6-8 yrs — better than EUR/GBP/JPY, but MAR 0.21 FAILS ≥1.5 gate.
- $1k/3% monthly reset: skim $14,807 net +$7,507 41% green. STEADY per-year
  (7/8 profitable: 2019 +2264, 2020 +1959, 2021 +1674, 2024 +1214, 2026 +1165;
  only 2022 -1578). Far smoother than JPY.

## Cross-symbol ranking (A+D combo, identical params)
| Symbol | combo PF | pos yrs | long-leg PF | deploy |
|--------|----------|---------|-------------|--------|
| XAU    | ~1.31    | 7/8     | strong      | ✅ LIVE |
| SPX    | 1.18     | 6/8     | 1.29 (7/8)  | long-only candidate |
| EUR    | 1.15     | —       | —           | marginal |
| JPY    | 1.07     | 2/8     | 1.29 (5/8)  | no (regime) |
| GBP    | 1.06     | —       | —           | marginal |
| BRENT  | 0.93     | —       | —           | dead |

## Structural pattern (holds across ALL symbols incl BTC)
LONG legs work on secular-uptrend assets (XAU, SPX, JPY-2022, BTC); SHORT legs die.
The XAU A+D edge is special because gold ranges both ways enough for D to pay.
SPX/JPY/BTC are one-directional drift → only the with-trend leg has an edge.

## Next (Monday, parked)
- SPX LONG-ONLY (leg A) deserves the full audit: bootstrap, walk-forward OOS,
  vs buy-and-hold risk-adjusted. Strongest non-XAU result — worth vetting properly.
- If it clears: SPX long-only could be a real second sleeve (equities drift + Fib pullback).
- Data cached in /tmp/oanda_{jpy,spx}_{h1,m5}.parquet (re-fetch via oanda_fetch, token in .env).
Runners: research/cross_symbol/run_{jpy,spx}_ensemble.py + build_frames.py.
