# Labs Sprint #1 — Comparison Table

> **Honest summary across 5 publicly-documented strategies, run through the same fill model on the same JM 7-year dev window for Brent (BCO_USD).**

## Bottom line

**No strategy in this sprint passes the "interesting" bar.** All five are net losers with PF < 1.10 (the threshold defined in the Labs README). All five passed lookahead audit + random baseline → results are honest, not artifact.

That is itself a finding: the four major strategy CLASSES (breakout, mean-reversion, drift, trend-following) at their published defaults do not have edge on Brent intraday over JM 2019-2023.

## Comparison

| ID | Strategy | Class | Trades | WR % | PF | P&L | Max DD % | Trusted | Verdict |
|---|---|---|---:|---:|---:|---:|---:|:---:|---|
| 001 | ORB (Crabel 1990) | Breakout (intraday) | 1,099 | 35.1 | **0.753** | −$34,704 | 97.7 | ✅ | Loser |
| 002 | VWAP Mean Reversion | Mean-reversion (intraday) | 1,101 | **13.1** | **0.196** | **−$252,061** | **100** | ✅ | Catastrophic |
| 003-L | Overnight Drift LONG | Drift (positional) | 1,097 | 51.2 | 1.008 | +$364 | 70.8 | ✅ | Break-even |
| 003-S | Overnight Drift SHORT | Drift (positional, inverse) | 1,097 | 44.7 | 0.817 | −$8,757 | 59.9 | ✅ | Loser |
| 004 | Donchian 20/10 H1 | Trend-following (intraday) | 958 | 45.3 | 0.882 | −$7,563 | 59.4 | ✅ | Loser |
| 005 | Wed EIA Mean Reversion | Mean-reversion (event) | 87 | 35.6 | 0.282 | −$10,033 | 47.0 | ✅ | Loser |

## Promotion bar (defined in Labs/README.md)

A strategy is INTERESTING if and only if all of:
- PF > 1.10 ❌ none pass
- Max DD < 50 % yearly ❌ four out of five fail (only 003-L is borderline)
- Lookahead audit PASS ✅ all five
- Random baseline NEGATIVE ✅ all five
- Trade count > 100 ✅ all but #005

**0 of 5 strategies pass.**

## Honest patterns observed

1. **Mean reversion strategies (002, 005) are catastrophic on Brent.**
   13% and 36% WR respectively. When Brent extends, it CONTINUES.
   The mean-reverting microstructure that works on (some) equity indices
   doesn't exist on BCO_USD at these timeframes.

2. **Trend-following (004) loses too**, but only by ~12% PF deficit, not
   the 80%+ deficit of mean-reversion. There's a hint that trend-following
   on Brent is closer to break-even at the right horizon. The 20-bar H1
   lookback might be wrong. **Worth a follow-up sprint.**

3. **Overnight drift LONG is essentially break-even** (PF 1.008, ~$0.30
   per trade). Real but too small to overcome real-world transaction
   costs on small accounts.

4. **2020 was the only exception year** for some strategies — strong
   trends from COVID disruption helped trend-followers and hurt
   mean-reverters. 2021-2023 normalised conditions reversed both.

5. **Lookahead bugs were found in 2 of the 5 strategies** during the
   sprint (ORB's `len(scan_df) < 2` guard, VWAP's `+ 5` warmup buffer).
   Both fixed before reporting. **The discipline gates worked.**

## What this rules out

- Off-the-shelf published Brent intraday strategies at default
  parameters → not exploitable on JM 7-yr data.
- The hypothesis "the original Oil Micro lookahead was hiding a real
  edge that any published intraday strategy could find" → false. We
  tested 5 different concepts and none has edge.

## What this does NOT rule out

- **Tuned versions** of any strategy above. We deliberately did not
  optimize. With proper walk-forward on a held-out period, some might
  show edge.
- **Different timeframes.** All 5 strategies use M3 or H1. Daily, 5-min,
  or tick-level might behave differently.
- **Different instruments.** XAU_USD (Gold) might respond to mean-
  reversion at the same parameters that fail on BCO_USD.
- **Combinations.** A "Donchian breakout filtered by overnight-drift
  positive bias" might work even though neither does alone.

## Recommended next sprint (if user wants)

1. **Donchian parameter sweep** with proper walk-forward — the only
   strategy showing any structural edge (PF 0.882 with no tuning).
2. **Trend-continuation EIA** — same setup as #005 but reversed
   direction. Mean-rev failing badly suggests trend-continuation is
   the right side.
3. **XAU_USD on the same 5 strategies** — does Gold respond differently?
4. **Breakout + momentum filter** — only take ORB breaks where the
   prior hour's momentum is in the breakout direction.

These are research directions, NOT commitments. User decides.

## Caveats — what to remember

- **No optimization yet.** All strategies tested at literature-default
  parameters. Tuning could change things — for the better OR worse.
- **No validation/holdout split.** All numbers are on the dev window
  (2019-09-26 → 2023-12-31). 2024-2026 data is sealed; if any strategy
  graduates to "looks promising," running on validation/holdout is the
  next gate.
- **No transaction costs beyond slippage.** We applied the
  `0.0325 + bar_range × 0.01` slippage formula on SL fills only. We did
  NOT apply commission ($7/lot RT) or swap (~$3/night). Adding those
  pushes 003-L from PF 1.008 firmly into negative.
- **Yearly capital reset** convention used (yearly $5K, 4% risk, 5,000
  unit cap) — same as production. P&L is sum of independent yearly
  accounts, NOT compounded.

## Files

```
Labs/
├── README.md                          # the contract
├── shared/
│   ├── data.py                        # sealed gateway wrapper
│   ├── fill_model.py                  # canonical exit walk
│   ├── runner.py                      # strategy → BT → stats
│   └── safeguards.py                  # lookahead audit + random baseline
├── strategies/
│   ├── 001_orb_brent.py
│   ├── 002_vwap_mean_reversion_brent.py
│   ├── 003_overnight_drift_brent.py
│   ├── 004_donchian_breakout_brent.py
│   └── 005_eia_wednesday_meanrev_brent.py
└── results/
    ├── 001_orb_brent.md
    ├── 002_vwap_mean_reversion_brent.md
    ├── 003_overnight_drift_brent.md
    ├── 004_donchian_breakout_brent.md
    ├── 005_eia_wednesday_meanrev_brent.md
    └── comparison_table.md            # this file
```

## Reproduce all 5

```bash
cd /Users/subash/SUBASH/GoldDigger
for f in Labs/strategies/00*.py; do
  echo "=== $f ==="
  python "$f"
done
```

Deterministic; same numbers every run.
