# XAU-SDR-001 Edge Summary

## Core Finding

The base edge is not “supply and demand happens daily, therefore trade everything.”

The edge is:

> Trade only the cleaner reclaim reactions around quantified XAUUSD supply/demand zones.

The broad universe had many signals, but most were noisy. The filtered Sleeve 1 base keeps the cleaner subset.

## Base Numbers

Full sample:

- Trades: `1,032`
- Net: `+256.11R`
- Win rate: `63.86%`
- Profit factor: `1.68`
- Max drawdown: `-12.69R`
- Positive years: `8/8`

OOS 2022-2026:

- Trades: `818`
- Net: `+216.97R`
- Average: `+43.39R/year`
- Win rate: `64.67%`
- Profit factor: `1.75`
- Max drawdown: `-12.69R`
- Positive years: `5/5`

## Stress Result

The base survived:

- cost haircuts,
- Monte Carlo trade-order permutation,
- bootstrap resampling,
- top-winner removal,
- rolling window analysis,
- trade clustering analysis.

The main warning is that the worst 12-month rolling window was only `+0.87R`.

## Practical Translation

At `$1,000` per `R`, the OOS slice averaged roughly `$43k/year`.

At `$2,000` per `R`, the OOS slice averaged roughly `$87k/year`.

At `$2,500` per `R`, the OOS slice averaged roughly `$108k/year`.

Those are research translations, not broker lot-sizing instructions.

