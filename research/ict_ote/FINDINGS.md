# ICT Premium/Discount OTE (SMC/ICT Guide) — XAUUSD — NO EDGE

Quantised **exactly** to "The Trader's Guide to SMC & ICT" (Anoop Upadhyaye, 38pp),
fully causal, strict right-side swing confirmation. 2019-10 → 2026-06, cost $0.30/risk_units.

## The strategy, to the dot
- **Structure** (`structure.py`): fractal swings confirmed only after `k` bars close
  to the right (`confirm_ts` = close of the k-th confirming bar). HH/HL/LH/LL
  classified vs prior same-kind confirmed swing. BSL = swing high, SSL = swing low.
- **Impulse leg** = confirmed swing-low→swing-high (long) / high→low (short);
  armed at `arm_ts` = later of the two confirmations (whole leg known before arming).
- **OTE** = swingH − 0.705·(swingH−swingL) in the discount zone (guide's exact 0.705).
- **Confluence**: bullish FVG (`low[i]>high[i-2]`, CE=midpoint) or high-prob OB
  (`|C−O|/(H−L) ≥ 0.70`) formed *inside the leg* and overlapping OTE.
- **Trend**: M15 EMA20/50 alignment (guide step 1: check trend).
- **Entry**: BUY LIMIT at OTE, filled when M5 low taps it within a wait window
  (`limit`), or after a post-tap confirmation close (`confirm`, guide's CHoCH step).
- **TP = BSL** (swing high, fixed price). **SL below SSL** by `sl_buf·ATR`. Target 1:3.
- Invalidation: M5 close beyond the swept swing before fill → cancel.

## Result: dead at every setting
| config | n | /yr | PF | net R | pos yr | WR | avg RR |
|---|---|---|---|---|---|---|---|
| k3 all | 4773 | 711 | 0.90 | −376 | 3/8 | 35% | 2.1 |
| k5 hh+trend rr≥2 long (BEST) | 1133 | 169 | **0.98** | **−17** | 3/8 | 35% | 2.2 |
| k5 hh+trend rr≥2 confirm long | 848 | 127 | 0.90 | −54 | 2/8 | 41% | 1.5 |

- **limit** mode: WR ~34%, RR ~2.2 → gross +0.08R = the exact 1:2.2 breakeven line.
- **confirm** mode: WR lifts to 41% but RR collapses to ~1.5 → gross ≈ 0.
- Either way, the ~0.10R/trade cost turns every config **net-negative**. PF tops out
  at 0.98. Best net is −17R over 8 years, 3/8 positive years. No gate cleared.

## Adversarial (best config)
- **Causal self-test PASS**: every fill sits at/after its fully-confirmed `arm_ts`.
- **Delay is erratic** (+1: −60R, +2: +860R, +3: +105R) — a *real* edge decays
  smoothly with entry delay; this jumps around → the base has no stable directional
  edge, it's catching violent post-tap reversals whose sign is coin-flip.
- (Flip-side "control" printed +517R but it's **invalid** — tp/sl weren't swapped on
  flip, so those brackets are incoherent. Ignored.)

## Verdict
Faithful, causal implementation of the guide's flagship OTE setup has **no edge** on
XAUUSD. Gross geometry is breakeven; cost makes it a loser. Same graveyard as the
prior ICT AM-session / OB / liquidity-sweep gold experiments — narrative, not
statistical. The 0.705 OTE tap is not a predictive level once look-ahead is removed.

Scaffold: `research/ict_ote/{structure,run_ote,adversarial}.py`.
