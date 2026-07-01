# Loss-Reduction Analysis — Fib V2 Intraday A+D (Model B $10k)

Data source: BT run `b6604240-14f4-464f-86b4-0d0e32755838` (fib_v2_intraday_a_plus_d, 22 years XAU M15, +$850,710 net).

## Headline

- **27,950 trades, +$850,710 net, +8,279R** over 22 years
- **48.9% win rate**, avg trade +$30
- **Winners:** 13,673 → +$2,291,916 total (avg +$168, max +$36k)
- **Losers:** 14,277 → −$1,441,206 total (avg −$101, min −$2.3k)

## Loss composition — where the money bleeds

| Bucket | Count | Sum $ | % of $ loss |
|---|---:|---:|---:|
| Full SL (<-0.9R) | **11,905** | **−$1,393,330** | **96.7%** |
| Moderate (−0.5 to −0.2R) | 784 | −$21,130 | 1.5% |
| Severe (−0.9 to −0.5R) | 339 | −$17,733 | 1.2% |
| Shallow (0 to −0.2R) | 1,249 | −$9,013 | 0.6% |

**97% of $ loss = full-SL hits.** Everything else is rounding.

## Exit reason split

**Losers:**
| Reason | N | Sum $ |
|---|---:|---:|
| SL | 11,898 | −$1,392,775 |
| SL_BE (partial fired + BE) | 2,188 | −$41,316 |
| TIMEOUT | 191 | −$7,115 |

**Winners:**
| Reason | N | Sum $ | Avg R |
|---|---:|---:|---:|
| **TP** | 2,255 | **$1,490,412** | +6.92 |
| TIMEOUT | 2,212 | $568,558 | +2.83 |
| SL_BE (partial saved) | 9,206 | $232,946 | +0.27 |

**Partial-TP mechanism WORKS.** 9,206 trades that would have been full losses became small wins via partial fill. Without partial-TP, those would ALL be full-SL loss = **−$1.4M added** — the entire strategy would net near zero.

## "What if we could cut worst-X% losers" scenarios

| Cut worst % losers | Trades cut | $ saved | New net $ | Boost |
|---:|---:|---:|---:|---:|
| 1% | 142 | +$24,537 | $875,247 | +2.9% |
| 5% | 713 | +$109,910 | $960,620 | +12.9% |
| **10%** | **1,427** | **+$207,254** | **$1,057,964** | **+24.4%** |
| 20% | 2,855 | +$385,991 | $1,236,701 | +45% |
| 25% | 3,569 | +$473,412 | $1,324,122 | +55% |
| 50% | 7,138 | +$876,235 | $1,726,945 | +103% |

Cutting the worst 10% of losers alone would boost lifetime net by **+$207k = +24%**.

## Levers to actually reduce losses (data-driven)

1. **Add momentum filter at entry** — only trade when short-lookback EMA slope matches direction. Would kill retrace-fail cases where price never gives back the move.
2. **ATR-compression skip** — if 24h ATR is below N-day median, skip. Compression traps = high full-SL rate.
3. **H1 confluence** — require H1 fib zone alignment in addition to M15. Cuts count but improves quality.
4. **Tighten BE trigger** — SL_BE losses at −$41k are trades where partial fired then market retraced through entry. Moving BE to +0.1R instead of exactly entry captures small profit on that 2,188-trade cohort. Rough estimate: recover ~$25-30k.

## Filters to prove or reject via re-BT

Priority order:
- **1.** Momentum EMA slope filter (M15 EMA20 slope in direction of trade) → re-BT, target: kill 20% of full-SL, keep 80% of TP
- **2.** BE + tiny-profit trigger (SL moves to entry + 0.15R after partial) → re-BT, target: −$20k of SL_BE loss becomes +$20k
- **3.** ATR compression skip (if 24h ATR < 50% of 20-day rolling median, skip entry) → re-BT
- **4.** H1 confluence gate (only enter if H1 fib zone also active) → re-BT, expect much fewer trades but higher quality

None of these should touch the strategy core — all bolt-on filters at `_signal_bar_matches` return-True gate.
