# Session Handoff — 2026-07-05 — SMC/ICT Full-Book Campaign

## Theme
Quantised EVERY strategy in "The Trader's Guide to SMC & ICT" (Anoop Upadhyaye, 38pp)
to the literal dot, fully causal, and swept ~53k configs on XAUUSD. Found the single
real edge, proved the rest don't work (incl. all shorts), and produced complete
split+merged numbers vs the live A+D workhorse. Decision: PARK S1, wait 1-week live audit.

## What Happened (chronological)
1. **First pass (ict_ote/):** built ICT Premium/Discount OTE to the dot. Naive version
   (OTE only) = PF 0.98, DEAD. User pushed: "did you miss the institutional core?"
   Added liquidity-sweep + real CHoCH + killzone + H4-trend → PF 1.43-1.61. Mega-sweep
   (27,648 cfg) → certified winner PF 1.47 @ realistic 0.05-ATR slip, MAR 1.96, 7-8/8.
2. **PnL studies:** Model B $5k monthly/yearly skim; capacity-realistic lot-cap; ran
   the winner through the PRODUCTION EquitySizer (1.5% monthly) = $50k/10x from $5k.
   Flagged the $2.7B flat-compound as phantom (frictionless-compounding artifact).
3. **Full campaign (smc_campaign/):** built causal primitives (IDM/OB/OF/FVG/breaker/
   mitigation/QML/MSS/sweep/sessions) — 0 causality leaks (test_causality.py). Vectorised
   fill+sim (exact parity w/ reference loop, maxΔ=0). Swept all 12 strategies (~36k cfg).
4. **Shorts:** user asked to find a short to pair with S1. Swept S1-short (15,552) +
   QML-bearish (1,176, the PDF's designated pg18 uptrend-short). 0 gate-passes. No
   tradeable short on gold — structural.
5. **Combined numbers:** combined_numbers.py — S1 + live A+D, split + merged on ONE
   account, Model B + flat-R, per-year, per-strategy contribution.

## Result — ONE edge in the whole book
**S1 = sweep→CHoCH→OTE, LONG-only.** `15min, k=4, fib0.786, sl0.10, TP3R, sweep_lb6,
need_conf5, h4_trend, killzone`. PF 1.43-1.72, MAR 2.0-2.9, 8/8 pos years, 105-206/yr,
bootstrap P(net≤0)=0.000, OOS>IS, smooth slip-decay. Confirmed by 3 independent sweeps.

All others FAIL: S2/S3/S7/S11 dead (PF~1.0); S4/S5/S6/S8/S9/S10 real-but-too-rare or
phantom-n. SHORTS: 0 gate-passes across ~17k configs (every PDF short method incl. QML).

## Combined numbers (ONE account, 2019-10→2026, Model B $5k/1.5% monthly skim)
| | lifetime $ | mult | maxDD$ | pos yr |
|---|---|---|---|---|
| A+D (live workhorse) alone | $334,063 | 66.8x | -$4,543 | 8/8 |
| S1-long alone | $29,070 | 5.8x | -$1,406 | 8/8 |
| **MERGED A+D + S1** | **$384,644** | **76.9x** | -$4,429 | 8/8 |
- Merged MAR 8.54; S1 IMPROVED risk-adjusted return (uncorrelated 105/yr long sleeve).
- Contribution (merged net +3527R): A +1563 / D +1634 / S1 +329.
- ⚠️ flat-R compound rows = 10^37 fantasy, IGNORE. Model B is the bankable column.

## Decision
**S1 PARKED — not deployed.** Wait **1 week of live A+D real-execution audit** (fills/
slip/spread vs BT) before bolting S1 on. If A+D live == BT, then port S1 to bt_engine +
paper-smoke, then add as a sleeve.

## Files
- research/ict_ote/: structure.py, run_ote.py, run_ote_v2.py, mega_sweep.py, adversarial*.py,
  MEGA_SWEEP_FINDINGS.md, FINDINGS.md, mega_sweep_leaderboard.csv (27,648 rows).
- research/smc_campaign/: primitives.py, framework.py, strategies_fast.py, sweep_engine.py,
  run_all_sweeps.py, run_s1_short.py, run_qml_short.py, s9_smt.py, test_causality.py,
  combined_numbers.py, CAMPAIGN_FINDINGS.md, results/S*_leaderboard.csv.
- Data: /tmp/oanda_{xau,xag}_{m15,m5}.parquet (SMT).

## Numbers to Remember
- S1 winner: PF 1.43-1.72, MAR 2.0-2.9, 8/8, 105-206/yr, long-only.
- Merged A+D+S1 Model B $5k = $384k / 76.9x / MAR 8.54 / 8/8 green.
- 0 causality leaks; fill+sim exact parity; 0 short gate-passes / ~17k configs.

## Next (after 1-week A+D audit)
1. Review live A+D fills vs BT (the workhorse real-execution audit).
2. If clean: port S1 to bt_engine (Fib-V2 causal discipline) + paper-smoke.
3. Then decide S1 as added sleeve. Cross-symbol S1 (BTC/EUR/SPX) optional.
