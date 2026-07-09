# Certification Candidate — Fib V2 Intraday "strict-after drop"

**Date:** 2026-07-10
**Change:** drop the `strict-after` gate in `fib_v2_intraday/strategy.py` — allow entry
evaluation ON the setup-confirm bar (bar K) instead of only bar K+1.
**Status:** CANDIDATE. Gate (a) BT=live parity PASSED. Gates (b) independent reviewer +
(c) formal un-freeze of [[fib-v2-certified-frozen]] still required.
**Deploy constraint:** ≤ 1.5% risk ONLY (see §5 — craters at 3%).

---

## 1. What changed (one line of code)
`FibV2IntradayBase._signal_bar_matches`: the block that blocked entry when
`bar.timestamp == setup.setup_confirm_ts` is removed → the confirm bar is now a
valid entry-scan bar. Strict-after was a **research-parity choice**
(`searchsorted(side='right')`), NOT a causality requirement.

## 2. Causality — KNOWN_AT audit (no time travel)
Per-trade assertions over all 10,268 trades (10.5yr .ecn), incl. all **1,745
same-bar (confirm-bar) entries** — the exact trades the drop unlocks:
- A1 `setup_confirm_ts ≤ signal_bar_ts` — 10268/10268 ✓ (0 violations)
- A2 `signal_bar_ts < fill_ts` (STRICT) — 10268/10268 ✓ (0 violations)
- A3 `fill − signal == exactly 1 bar` — 10268/10268 ✓ (0 violations)

Proof: the setup is fully confirmed at bar K's close; the fill is bar K+1's OPEN,
dated strictly after. **Mathematically impossible to time-travel.**

## 3. 15-point causal audit
14 of 15 points UNCHANGED and inherited-valid (the drop touches only point 12).
Point 3 (no phantom fill / next-bar open) is empirically PROVEN by A2/A3 on all
same-bar entries. Point 12 (strict-after) deliberately changed; A1 proves the change
is causal.

## 4. Edge evidence
| Test | Result |
|---|---|
| Delta trades (confirm-bar entries) standalone | PF 1.79, avgR 0.433 (> baseline 1.63 / 0.327) |
| 20yr OANDA net-R | baseline 7,655R (matches cert exactly) → no-strict 8,123R (+6.1%), 21/21 pos |
| Delta vs random benchmark | beats **100%** of random |
| IS/OOS | IS PF 1.53 → **OOS PF 1.71** (OOS > IS, anti-overfit) |
| Bootstrap | P(net≤0) = **0.0000**, 5th-pct +3,080R |

## 5. $ PnL — REAL EquitySizer, 20yr — and the RISK CLIFF
| Risk | baseline | no-strict | delta |
|---|---|---|---|
| **1.5%** $5k | $766,468 | $854,955 | **+11.5%** ✓ |
| 1.5% $10k | $1,564,142 | $1,748,484 | +11.8% ✓ |
| **3.0%** $5k | $2,633,375 | $525,113 | **−80.1%** ✗✗ |
| 3.0% $10k | $5,335,682 | $1,053,919 | −80.2% ✗✗ |

**CRITICAL:** the +2,311 extra trades raise trade-stream variance → LOWER the
growth-optimal risk fraction below 3%. At 3% the no-strict stream is **over-betting**
(past optimal-f) and craters. **Deploy ONLY at ≤ 1.5% risk.** (Current live is 3% —
do NOT flip strict-drop live without also dropping risk to ≤1.5%.)

## 6. Gate (a) — BT=LIVE parity — PASSED (this run)
20yr OANDA M5→M15, no-strict A & D through `run_engine` mode='bt' vs mode='live'
(`BTMirrorLiveBroker`, mirrors fill-at-open):
```
A no-strict: BT 11,520 / 3692.32R == LIVE 11,520 / 3692.32R  → 0-delta ✓
D no-strict: BT 18,756 / 4430.67R == LIVE 18,756 / 4430.67R  → 0-delta ✓
```
"One code, two modes" holds with strict-after dropped.

## 7. Remaining gates before LIVE
- [ ] (b) Independent hostile reviewer (cert standard = 2+; this audit is one)
- [ ] (c) Formal un-freeze of the certified/frozen strategy
- [ ] Risk-curve confirm: 0.5–3% for both variants → pin optimal-f, confirm the 3% cliff;
      also re-examine whether baseline itself should run <3%.

## Verdict
Real, causally-clean **+11.5%-at-1.5%** upgrade to the proven base — the first genuine
base improvement of the 2026-07 research arc. Parity-preserving. **Deployable at ≤1.5%
risk after (b)+(c).** NOT safe at the current 3%.

*Correction on record: an earlier −13.8% figure was a fractional-sizer proxy artifact +
an uncounted skim bank; the REAL EquitySizer gives +11.5% at 1.5%. Always use the real
sizer, not a proxy.*
