# A+D — P&L & Trade Reference (21yr XAUUSD)

> **⚠️ 2026-07-11 — $ NUMBERS INFLATED ~1.5×.** Confirmed: the engine over-counts partial-TP
> trades (`outcome = full_tp_R + partial_bonus`, but only half the position runs). **Physical
> edge = netR +3,397 / PF 1.34, not the certified +7,655 / PF 1.49 (~half).** Every $ figure
> below (risk-cliff, prop) is on the inflated convention — **divide by ~1.5–2× for reality**
> (winner-heavy = worse). Broker balance is physical/correct; BT projections are not.
> See `[[partial-tp-pnl-overcount]]`. Numbers below kept as-is pending a fix + re-baseline.


**Strategy:** Fib V2 Intraday A (long) + D (short), production strict, M15, lb=3, ext=2.618,
PTP+1R, Model-B EquitySizer. Live code = BT mode (certified 0-delta).
**Data:** OANDA XAU M5 → M15, 485,374 bars, **2006-03-19 → 2026-06-30 (20.3 yr)**.
**Generated:** 2026-07-11. Scripts: `research/cobrax/{trade_stats,baseline_risk,nostrict_risk,prop_account_sim,full_stats_sim}.py`.
**Nature:** WR < 50% but profitable — edge is asymmetry (avg win ≫ avg loss). Deep-DD, high-variance;
tolerated live by Model-B skim (never fully wipes). See `[[baseline-risk-cliff]]`, `[[strict-after-drop-upgrade]]`.

---

## 1. TRADE STATS (R-space, per-trade net R incl cost + partial-TP)

| metric | A+D combined | A — LONG | D — SHORT |
|---|---|---|---|
| Trades | **27,965** | 10,649 | 17,316 |
| **Wins** | **13,639** | **5,457** | **8,182** |
| Losses | 14,326 | 5,192 | 9,134 |
| Scratch (0R) | 0 | 0 | 0 |
| **Win rate** | **48.8%** | **51.2%** | **47.3%** |
| Net R | +7,655.2 | +3,446.4 | +4,208.8 |
| avg R (expectancy) | +0.2737 | +0.3236 | +0.2431 |
| **Profit factor** | **1.488** | **1.622** | **1.415** |
| avg win | +1.711 R | +1.646 R | +1.754 R |
| avg loss | −1.095 R | −1.067 R | −1.110 R |
| payoff ratio | 1.56 | 1.54 | 1.58 |
| best trade | +36.20 R | +16.06 R | +36.20 R |
| worst trade | −2.30 R | −2.28 R | −2.30 R |
| median R | −0.038 | +0.036 | −0.095 |
| partial-TP taken | 15,197 (54%) | 5,672 (53%) | 9,525 (55%) |
| avg bars held (M15) | 27.4 | 23.0 | 30.2 |
| longest win streak | 18 | 18 | 14 |
| longest loss streak | 23 | 15 | 23 |

**Win split:** long wins 5,457 (40% of wins) · short wins 8,182 (60%) · total 13,639.

### Exit-reason mix
| reason | A+D | A (long) | D (short) |
|---|---|---|---|
| SL (full stop, −1R) | 11,337 | 3,965 | 7,372 |
| SL_BE (partial booked → BE) | 9,874 | 3,150 | 6,724 |
| TIMEOUT (hold-cap) | 5,079 | 3,098 | 1,981 |
| TP (full target) | 1,675 | 436 | 1,239 |

*Full TP is only 6% — the +1R partial does the work; most trades exit via SL or partial+BE.*

---

## 2. TRADE FREQUENCY (count unchanged by any sizing/throttle — signals only)

| period | A+D | A (long) | D (short) |
|---|---|---|---|
| per year | ~1,379 | ~525 | ~854 |
| per month | ~115 | ~44 | ~71 |
| per trading day | ~5.5 | ~2.0 | ~3.4 |
| per calendar day | ~3.8 | ~1.4 | ~2.4 |

*D fires ~1.6× more than A. "Per day" is an average — some days 0, active days more.*

---

## 3. P&L — REAL EquitySizer (Model-B, $5k start, 20yr exact path)

`final $ / min-equity ($ and % of start) / max-DD%`. Skim banks profit to a separate account,
so ruin exposure is EARLY near the start balance.

### STRICT (production / live)
| risk | final $ | min-eq | max-DD |
|---|---|---|---|
| 1.5% | $766k | $1,567 (31%) | 94.6% |
| **2.0% (LIVE)** | **$1.18M** | **$999 (20%)** | 98.0% |
| 2.5% | $1.76M | $538 (11%) | 99.3% |
| 3.0% | $2.63M | $289 (5.8%) | 99.8% |
| 3.5% | RUIN (−$2,378) | — | >100% |

### NO-STRICT (built, causal, BT=live 0-delta; NOT deployed)
| risk | final $ | min-eq % |
|---|---|---|
| 1.5% | $855k | 17% |
| 2.0% | $1.37M | 7.8% |
| 2.5% | $2.16M | 3.8% |
| 3.0% | **RUIN** | — |

*No-strict = +6.1%R / +11.5%$ real causal upgrade, but shifts the ruin cliff LEFT ~0.75-1% risk.
20yr: strict 27,965 tr / 7,655R → no-strict 30,276 tr / 8,123R. BT=live parity: 30,276 trades 0-delta.*

**Risk-cliff verdict:** live 2% has ~20% cushion; 3% nearly ruins (5.8%); 3.5% ruins. Model-B skim
= real exposure is early. Live de-risked 3%→2% (2026-07-10).

---

## 4. PROP / DD-THROTTLE (make A+D fit prop firms; funded 5K account model)

**DD-throttle** = sizing overlay: `risk = base% × throttle(dd) × balance`, taper to 0 at `cap`.
Edge-preserving (same trades/R-sequence, only $ size scales). Caps max-DD to target.

### Throttled prop-account results (5K, monthly payout, static 4,500 floor, 20yr)
| config | $/mo (mean) | %mo+ | maxDD | worstDay | blowups | fit |
|---|---|---|---|---|---|---|
| flat 0.5% | $805 | 79% | 17% | 5.2% | 25 | ❌ |
| flat 1.0% | $1,399 | 63% | 26% | 10.2% | 102 | ❌ |
| 0.5% + cap 8% | $667 | 75% | 7.7% | 4.1% | **0** | ✅ |
| 1.0% + cap 10% | $1,252 | 73% | 9.9% | 7.8% | **0** | ✅* |
| 1.0% + cap 8% | $1,074 | 69% | 8.0% | 7.5% | **0** | ✅ |

\* cap 10% min-balance hit **$4,503** (0.1% above floor) — unsafe intraday; **prefer cap 8%.**

### Full stats — base 1% + cap 10% (illustrative best-case; use cap 8% live)
| metric | value |
|---|---|
| monthly payout: mean / **median** / std | $1,252 / **$588** / $1,724 |
| monthly %: mean / median / max | 25.0% / **11.8%** / 194% |
| percentiles (p5/p50/p95) | $0 / $588 / $4,949 |
| % months profitable | 73% (27% flat) |
| 20yr total payout | $305,572 |
| per-year: mean / **median** / best / worst | $14,551 / **$12,308** / $41,185 (2013) / $1,738 (2006) |
| positive years | 21/21 |
| realized max-DD | 9.9% (0 blowups) |
| Sharpe / Sortino (ann.) | 2.52 / 11.94 |
| bootstrap annual $ (p5/median/p95) | $6,651 / $14,355 / $25,769 |
| throttle: avg mult / % throttled | 0.58 / 88% |

**Honest read:** quote the **MEDIAN** ($588/mo, ~$12k/yr per 5K), not the fat-tail mean.
No-daily firms only (worst-day 7.8% > GFT's 4% daily). Best fit: FundedNext Stellar, FXIFY, The5ers.

---

## 4b. TARGET EXPERIMENTS — what DOESN'T work

**Fixed R:R 1:2 (TP=+2R) KILLS the edge** (`research/cobrax/rr12_sim.py`, 21yr, live cost $0.65):
| variant | WR | net R | PF | best trade |
|---|---|---|---|---|
| Pure 1:2 (2R TP, no partial) | 38.1% | **−6,019** | **0.72** (LOSER) | +2.0R |
| Code + 2R TP (keep PTP+1R) | 51.7% | +2,982 | 1.19 | +2.5R |
| **Baseline (fib TP 2.618) — KEEP** | 48.8% | **+7,655** | **1.49** | **+36.2R** |

**Why:** A+D's edge lives in the FAT RIGHT TAIL — the fib-2.618 target lets winners run to +36R.
A fixed 2R cap chops the tail (best +36.2R → +2.0R), avg-win falls +1.71R → +1.28R, netR −61%.
Pure 1:2 has NO edge (PF 0.72). **The variable fib target is load-bearing. Do NOT switch to fixed R:R.**
(Counter to retail "cut winners at 2R" advice — fatal here.)

---

## 5. CAVEATS (all sims)
1. **Close-based M15** — intraday/floating MAE not modeled → blowups a LOWER bound, DD optimistic.
2. **Model-B / prop payout** — prop numbers withdraw-to-5000 monthly = NO compounding (floor, not ceiling).
3. **20yr AVG** includes best regimes; forward-realized lumpier (27-28% flat months).
4. **min-eq / streaks** = one historical ordering; bootstrap covers annual variance only.
5. Trade stats are **R-space**; $ depends entirely on sizing (sections 3-4).
6. Prop cap 10% ≈ kisses floor → **use cap 8%** for real safety margin.
