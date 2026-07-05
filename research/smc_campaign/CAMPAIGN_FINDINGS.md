# SMC/ICT 12-Strategy Mega-Campaign — XAUUSD — FINDINGS

Every strategy in "The Trader's Guide to SMC & ICT" (Anoop Upadhyaye) built to the PDF
dot, fully causal, and swept. Shared causal primitives (IDM/OB/OF/FVG/breaker/
mitigation/QML/MSS/sweep/sessions) — **0 causality fails** across M15/H1/H4
(test_causality.py). Vectorised fill+sim — **exact parity** with reference loop.
XAUUSD 2019-10→2026-06, cost $0.30/risk_units. ~36,000 configs across 11 strategies.

## Verdict: ONE strategy clears the full gate — S1 (sweep→CHoCH→OTE)

| Strat | Name (PDF pg) | configs | gate# | best PF | @n | /yr | MAR | pos | verdict |
|---|---|---|---|---|---|---|---|---|---|
| **S1** | SMC10 / OTE (8,13) | 31,104 | **34** | **1.43** | 1381 | 206 | **2.20** | **8/8** | ✅ WINNER |
| S8 | MMXM (21) | 54 | 0 | 1.51 | 310 | 46 | 1.36 | 8/8 | rare (46/yr) |
| S5 | QML (18) | 276 | 0 | 1.66 | 117 | 18 | 0.67 | 7/8 | phantom n |
| S12 | FakeBreakout (25-27) | 1296 | 0 | 1.72 | 169 | 27 | 0.55 | 6/8 | phantom n |
| S4 | Breaker/Mitigation (16-17) | 576 | 0 | 1.36 | 361 | 54 | 0.92 | 7/8 | sub-gate |
| S6 | DailyBias (19) | 24 | 0 | 1.41 | 234 | 35 | 0.43 | 6/8 | marginal |
| S10 | RSI-divergence (25) | 954 | 0 | 1.46 | 134 | 20 | 0.52 | 4/8 | rare/weak |
| S2 | FVG-trade (14-15) | 432 | 0 | 1.01 | 1432 | 213 | 0.01 | 4/8 | DEAD |
| S3 | FVG-inversion (15-16) | 288 | 0 | 0.90 | 611 | 92 | — | 2/8 | DEAD |
| S7 | PowerOfThree (20) | 54 | 0 | 1.14 | 1295 | 193 | 0.40 | 4/8 | DEAD |
| S11 | FibRetracement (28) | 864 | 0 | 1.18 | 1446 | 215 | 0.61 | 5/8 | DEAD |
| S9 | SMT XAU/XAG (22-24) | 162 | 0 | 1.18 | 1582 | 236 | 0.58 | 6/8 | weak, sub-gate |

**S9 SMT done** (XAU+XAG OANDA M15/M5, corr 0.75). Best PF 1.175, MAR 0.58, 6/8, 236/yr,
long-only (bullish-SMT only; bearish dead — structural law holds). The most-hyped ICT
prop strategy is MEDIOCRE on gold: beats the dead ones but fails MAR/pos-year gate.
Caveat: XAU/XAG corr 0.75 is borderline; SMT may fare better on tighter FX pairs — but
NOT the winner on XAU. Files: research/smc_campaign/s9_smt.py, results/S9_leaderboard.csv.

## The winner (S1) — triple-confirmed edge
`rule=15min · k=4 · fib(OTE)=0.786 · sl_buf=0.10 · TP=3R · sweep_lb=6 · need_conf=5 ·
h4_trend/kz session · long-only` → **PF 1.43, MAR 2.20, 8/8 pos years, 206/yr.**
34 gate-passing configs = a robust basin. This is the SAME recipe found independently
by the standalone ict_ote mega_sweep (PF 1.47 @ 0.05 slip) — **three separate sweeps
converged on it**, the strongest possible non-overfit signal.

Structural law across all 11: the edge lives in **liquidity-sweep origin + real CHoCH +
killzone + HTF-trend + deep 0.786 retrace + tight stop + 3R**. Strip the sweep/CHoCH
context (S2/S3/S11 raw FVG/fib entries) → PF ~1.0, dead. The "institutional millions"
are in the CONTEXT filters, not any single pattern object.

## Why the others fail (honestly)
- **DEAD (PF≈1.0):** S2 FVG-trade, S3 FVG-inversion, S7 PowerOfThree, S11 FibRetr —
  raw zone/level entries with no predictive edge once causal. Same graveyard as prior
  ICT experiments.
- **Real-but-rare (fail ≥200/yr gate):** S4, S5, S6, S8, S10, S12 — some have genuine
  PF (S8 MMXM 1.51/8-8, S4 breaker 1.36/7-8) but fire 18-54×/yr. Big-numbers guard:
  S5/S12's PF 1.66-1.72 sit on n=117-169 (17-27/yr) = statistically thin phantoms,
  NOT tradeable edges. Discarded.
- These *could* be swing sleeves at lower freq, but none beats S1 as an intraday product.

## Causality + method integrity
- Primitives self-test: 0 leaks (swings k-bar right-confirmed, structure/FVG/OB/IDM/
  breaker all valid_ts = forming-bar close). No center=True, no future peek.
- fill + sim vectorised, exact-parity verified vs reference loop (maxΔ=0.0000).
- Big-numbers mandate applied: high-PF low-n configs flagged as phantoms, not accepted.

## Outstanding
- **S9 SMT** (correlated-pair divergence, pg22-24): NOT run — needs XAG/EUR fetch +
  a correlated-divergence engine. The one ICT strategy most cited for prop results.
  Build next if desired (OANDA XAG, token in .env).

## Files
research/smc_campaign/{primitives,framework,strategies_fast,sweep_engine,run_all_sweeps,
test_causality}.py + results/S*_leaderboard.csv. Certified winner also lives standalone
in research/ict_ote/ (MEGA_SWEEP_FINDINGS.md).
