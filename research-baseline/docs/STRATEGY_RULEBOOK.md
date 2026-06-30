# XAU-SDR-001 Rulebook

## Identity

- Name: `XAU-SDR-001`
- Full name: `XAU Supply Demand Reclaim`
- Instrument: `XAUUSD`
- Base sleeve: `Sleeve 1`
- Research unit: `R`

## Strategy Idea

The strategy trades quantified supply/demand reclaim events in gold.

It does not try to predict every move. It waits for a previously identified supply/demand reaction area, then trades the reclaim/rejection when the event qualifies.

## Frozen Base Definition

The base is the clean top-3 XAUUSD reclaim candidate:

- Include XAUUSD only.
- Include the clean top-3 signal set.
- Include both demand and supply reclaim opportunities as represented in the frozen Sleeve 1 ledger.
- Exclude cross-asset confirmation.
- Exclude Brent and other markets.
- Exclude top-10 stretch variants.
- Exclude hour blacklist, day sizing, and other experimental filters.

## Why This Became Base

The prior cross-add-on helped slightly, but it was not the core edge.

The clean Sleeve 1 base produced:

- Strong standalone OOS numbers.
- Positive years across the tested period.
- Acceptable drawdown in Monte Carlo permutation.
- Resilience after removing the top winners.
- Better simplicity than the cross-asset combined strategy.

## What Creates The Edge

The edge appears to come from the local behavior after a supply/demand reclaim:

- price returns to a previously reactive zone,
- rejection/reclaim conditions identify a fresh response,
- the trade captures the first continuation leg,
- risk is normalized in `R`,
- many small-to-medium wins overcome controlled losers.

This is not a “one giant trade” model.

## Known Weakness

2023 was only slightly positive. The edge survived that year, but it did not thrive.

That means the strategy should be monitored for regime decay.

## Not Part Of Base

The following remain research-only:

- cross-asset add-on,
- Brent add-on,
- top-10 stretch,
- ORB overlay,
- order-block overlay,
- volume-profile overlay,
- hour filters,
- weekday sizing,
- impulse cap,
- retest-depth filter.

They can be researched later, but they are not part of `XAU-SDR-001`.

