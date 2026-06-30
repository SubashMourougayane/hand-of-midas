# SDR-001 Sleeve1 ORB Causality Audit

Generated: 2026-06-29

## Verdict

Claude's conclusion is correct: Sleeve1 is contaminated by the same ORB look-ahead class.

The exact counts differ slightly depending on cutoff:

- Claude used NY hour `< 9`, which catches pre-09:00 trades.
- The stricter causal cutoff is `< 09:30 NY`, because the 30-minute ORB is not fully known until 09:30.

Using the correct `<09:30 NY` guard, Sleeve1 has 312 pre-ORB trades.

## Headline Recheck

| Segment | Trades | Net R | WR | PF | Max DD | Years | Months |
|---|---:|---:|---:|---:|---:|---:|---:|
| `all_sleeve1` | 1,032 | +256.11 | 63.86% | 1.68 | -12.69 | 8/8 | 53/80 |
| `claude_cutoff_pre_0900` | 298 | +196.79 | 84.56% | 5.15 | -3.09 | 7/7 | 49/54 |
| `causal_cutoff_pre_0930` | 312 | +202.34 | 83.97% | 4.92 | -3.09 | 7/7 | 49/54 |
| `causal_remaining_post_0930` | 720 | +53.77 | 55.14% | 1.17 | -15.41 | 6/8 | 38/80 |

## Smoking Gun

For the causal `<09:30 NY` cutoff:

```text
Sleeve1 all:             1,032 trades, +256.11R, PF 1.68
Pre-ORB contaminated:      312 trades, +202.34R, PF 4.92
Post-ORB remaining:        720 trades,  +53.77R, PF 1.17
```

So the pre-ORB trades are only about 30% of the count but about 79% of the PnL.

## ORB Flag Counts

| Segment | Trades | orb_reversal true | orb_continuation true | orb_inside true |
|---|---:|---:|---:|---:|
| `pre_0900` | 298 | 278 | 7 | 13 |
| `pre_0930` | 312 | 278 | 7 | 27 |
| `post_0930` | 720 | 347 | 283 | 80 |
| `all` | 1,032 | 625 | 290 | 107 |

## Root Cause

`bt_engine.strategies.sdr001.generator.add_orb_context()` computes the NY 09:00-09:30 opening range and writes that same day's ORB state onto every bar of that New York date.

That lets pre-09:30 trades know whether price is above, below, or inside an ORB that has not formed yet.

This means the engine reproduced the historical baseline faithfully, but the historical baseline itself contains leaked ORB features.

## Implication

The canonical Sleeve1 headline cannot be treated as a clean live baseline:

```text
Old headline:  +256.11R, PF 1.68
Causal residue: +53.77R, PF 1.17
```

That is marginal and likely not enough after realistic live uncertainty.

## Required Action

1. Freeze the contaminated SDR-001/Sleeve1 numbers as historical/research-only.
2. Patch `add_orb_context()` so same-day ORB state is `missing` before 09:30 NY.
3. Rebuild the event matrix from raw bars.
4. Rerun the full rule sweep with all ORB predicates causal.
5. Treat every old rule containing `orb_reversal`, `orb_continuation`, or `orb_inside` as suspect until regenerated.

