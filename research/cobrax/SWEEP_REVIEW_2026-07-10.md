# COBRAX Stage-1 Sweep — Review (2026-07-10)

**Goal:** find a robust revenue improvement over the headline COBRAX config, without curve-fitting.
**Method:** 384 combos, cost-adjusted (XAU 0.2), IS 2006-2015 pick / OOS 2016-2026 report.
Gate: IS PF & OOS PF ≥ 1.3, OOS ≥80% positive years, n≥300. Rank by OOS net-R (revenue).
**Result:** 43/384 passed the gate. Runner: `research/cobrax/cobrax_sweep.py`. Full grid: `stage1_results.csv`.

## Headline finding — the TARGET is the revenue lever

The deep-OTE ridge `ote(0.62,0.79) / lb3 / edge / sweep` dominates every passer. The one lever
that moves revenue is the **take-profit target**: the headline used next-liquidity (`nl`); a
**fixed RR** target captures more total R.

| target (ote .62-.79, lb3, edge/sweep, cost-adj) | XAU netR (Δ) | XAU PF | XAU WR | NAS netR (Δ) | pos yrs | bootstrap P(≤0) |
|---|---|---|---|---|---|---|
| nl2 (current headline) | 564 | 1.57 | 55% | 159 | 21/21 · 7/7 | 0.0000 |
| **rr2.0** | 740 (**+31%**) | **1.67** | 51% | 165 (+4%) | 21/21 · 7/7 | 0.0000 |
| **rr3.0** | 769 (**+36%**) | 1.58 | 41% | 219 (**+38%**) | 21/21 · 7/7 | 0.0000 |

- **Plateau, not a peak:** smooth in tp_r (rr1.5=655 → rr2=740 → rr3=769 full net), picked on
  IS-alone (rr3 tops IS net too), OOS ≥ IS on XAU → not overfit.
- **Cross-asset:** rr3 improves BOTH XAU (+36%) and NAS (+38%). rr2 best on XAU (PF 1.67, WR 51%,
  OOS PF 1.74) but flat on NAS.
- **Tradeoff:** higher RR → lower WR (rr3 ~40%). More total R per trade, NOT more trades
  (count fixed at 2006 XAU / 664 NAS). Bigger wins, longer losing streaks — matters for drawdown/prop.

## Recommendation
- **rr3** → maximum cross-asset revenue.
- **rr2** → XAU-focused, higher win-rate, smoother equity.
Either beats the current `nl` target. Change is one arg: `tp_mode="rr", tp_r=2 or 3` in the
COBRAX headline. NOT yet applied to the base engine — awaiting Subash's pick.

## What did NOT help (rejected by the gate or dominated)
- Shallow OTE bands (0.5-0.618, 0.5-0.705): fewer passers, lower net than 0.62-0.79.
- lb=2 (looser swings): more trades but PF sags below the ridge.
- lb=8 (tighter): higher PF, far fewer trades → lower total net.
- ce vs edge entry: edge/sweep at lb3 gives more trades + higher net at the top.

## Open (before this becomes a deployable second sleeve)
- Additivity vs Fib V2 (correlation of trade streams) — still THE gate; a revenue bump on a
  redundant sleeve adds nothing.
- Stage-2 refine (sweep_lb / max_hold / fvg_min) around rr2-3.
- Then: parity port + real-sizer $ at the chosen target.
