# ICT Extra PDFs + Classic Indicators — Research Findings (2026-07-05)

Tested "to the dot" against 3 more PDFs + classic-indicator families, on top of the
original 12-strategy SMC campaign. Same causal harness (research/smc_campaign),
XAUUSD 2019-10 → 2026-06, cost $0.30/risk_units, full gauntlet
(base PF/MAR, delay+1/2/3 reprice, cost-stress $0.30-0.80, bootstrap P(net<=0),
IS19-23/OOS24-26, 8-year, Model B $5k).

## Verdict: NOTHING new beats or complements S1. S1 remains the sole XAU edge.

### PDFs read line-by-line
1. **HowToTrade "ICT Trading Strategy"** — single-candle HTF liquidity sweep → LTF
   CHoCH → OB/FVG-midpoint entry → SL past OB, TP next opposite swing.
2. **innercircletrader.net "Complete ICT 2022 Model"** — mark NY-midnight→London-open
   range; London (or NY if London quiet) sweeps range hi/lo → LTF MSS+displacement →
   PD-array (FVG/OB/breaker) entry in premium/discount at OTE → SL past sweep, TP
   opposite range boundary (~1:3).
3. **HowToTrade "14 Most Important ICT Concepts"** — pure glossary (liquidity, FVG, OB,
   breaker, BOS, CHoCH, MSS, displacement, inducement, OTE, PO3, killzones,
   premium/discount, BPR). Every concept already a primitive; no new strategy.

### ICT 2022 model — built (ict2022_model.py) + 1728-combo mega-sweep (ict2022_sweep.py)
Knobs swept: scenario(london/ny/both) × entry(fvg_ce/ote) × sl_buf(0.05-0.50) ×
min_sweep_atr(0/0.10/0.25) × mss_look(12/24/48) × tp(range/2R/3R/4R) × wait(48/96).
- **2 / 1728 pass the full gate** — both `both/fvg_ce/sl0.10/mss24/TP3R-or-4R/wait96`:
  PF 1.40, MAR 1.76-1.80, 8/8yr, delay+1 1.37-1.44. **REJECT as phantom**: 0.1%
  survival = multiple-comparisons artifact; both strictly WORSE than S1 (PF 1.72,
  MAR 2.89); the adjacent config (mss48) has delay+1 PF 0.96 → knife-edge, not a basin.
- Best-*quality* family = NY-only/4R (PF 1.8, MAR 2.2-2.5, delay+1 1.3) but only
  82/yr → fails ≥150/yr freq gate. Real-but-rare, same bucket as S8 MMXM.
- delay+1 instability + cost-fragility (PF→1.0 at $0.50) across the grid = microstructure
  artifact, NOT structure. Confirms [[ict-am-session-no-edge]] on the session-range family.
  CSV: results/ICT2022_sweep.csv.

### S1 session-frequency gauntlet (s1_session_gauntlet.py)
Tested widening S1's killzone (frozen params, only session filter varies):
kz_base(NY2-11) PF 1.72 MAR 2.89 8/8 · all_session PF 1.41 MAR 1.48 7/8 ·
london_only PF 1.47 MAR 0.54 · ny_only PF 1.70 MAR 1.80 7/8 · london+ny PF 1.66 MAR 2.78 8/8.
**Killzone (NY2-11) is already optimal.** Every widening = more trades, worse edge,
erratic delay+1. Frequency-via-sessions REJECTED. Only non-overfit path to more S1 $
is more symbols (SPX/EUR), not sessions.

### Classic indicators (classic_batch.py) — VWAP / trendline / SMA
FIRST RUN HAD A LOOK-AHEAD BUG (market fill at bar-i open while knowing close[i] →
phantom +66,000R PF 4.79). Big-numbers mandate caught it. FIXED (fill at bar i+1 open):
- **VWAP reclaim/reject**: PF 0.83-0.96, all losing. DEAD causally. (The earlier
  [[vwap-mss-survivor]] was a different MSS-based construction; this version fails.)
- **Trendline (regression-channel) breakout**: PF 0.80-0.95, worst -3,242R. DEAD.
- **SMA 50/200 golden cross**: PF 0.89-1.08, MAR 0.37. DEAD (as predicted).
- **SMA 9/21, 20/50**: negative MAR, overtrading noise. DEAD.
- **S1 ∧ below-VWAP**: base PF 1.80/MAR 2.83/8-8 looks great BUT **delay+1 → PF 0.89**
  (fatal), redundant with S1's own discount logic (631/699 overlap), and Model B $28k
  < raw S1 $29k. REJECT — phantom, VWAP restates S1's fib-discount premise.

### Not tested (deferred / out of scope)
- HMM regime filter — heavier build; deferred.
- Arbitrage — needs multi-venue data we don't have; stat-arb = S9 SMT (already done, mediocre).

## Bottom line across ALL PDFs + classic indicators
The single durable causal XAU edge = **S1: sweep→CHoCH→OTE-0.786, killzone NY2-11,
3R, long-only, limit-fill.** PF 1.72, MAR 2.89, 8/8yr, delay-robust. Everything else
across 4 PDFs + VWAP/trend/SMA/all-variations dies on delay, cost, frequency, or
redundancy. The "institutional millions" narrative reduces to this one structure.
