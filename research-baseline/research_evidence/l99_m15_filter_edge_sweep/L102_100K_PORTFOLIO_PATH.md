# L102 100K Portfolio Path

## Objective

Find a path toward `$100k/year` without curve fitting, while keeping performance near the current Supply/Demand profile:

- current WR: `64.11%`
- requested WR band: `59.11%` to `69.11%`
- current PF: `1.68`
- requested PF band: `0.68` to `2.68`

## What Was Scanned

Existing research artifacts were scanned for portfolio/sleeve candidates:

- SupplyDemand top-3 union expansion
- Meta-stack portfolio
- Long/short monthly reset portfolio
- Short overlay practical selector
- XAU NY ORB dynamic monthly reset
- XAU NY ORB monthly max-margin runs
- Revenue expansion variants

Output scan:

`l102_portfolio_100k_candidate_scan.csv`

## Result

There is **no current small-capital portfolio** that cleanly produces `$100k/year` while preserving the requested WR/PF profile and staying away from curve-fit / excessive-risk behavior.

There are three different categories:

1. **Clean edge, but needs capital**
2. **High paper PnL, but too much risk**
3. **Robust portfolio, but still too small**

## Category 1 - Clean Edge, Needs Capital

The cleanest currently known candidate remains the SupplyDemand Top-3 strict union.

| Metric | Value |
|---|---:|
| Trades | `1,040` |
| Net R | `255.14R` |
| Avg R/year | `31.89R` |
| WR | `63.75%` |
| PF | `1.67` |
| Max DD | `-12.69R` |
| Positive years | `8 / 8` |

This keeps the desired WR/PF profile.

To reach `$100k/year`:

```text
100,000 / 31.89R = $3,135 risk per trade
```

Capital required:

| Risk % | Capital Needed |
|---:|---:|
| 1% | `$313k` |
| 2% | `$157k` |
| 5% | `$63k` |

This is the only clean way found so far to preserve the profile and reach `$100k/year` average.

Problem:

It is capital-intensive. With a `$5k` account, this is not feasible without reckless sizing.

## Category 2 - High Paper PnL, Too Much Risk

The XAU NY ORB monthly reset / max-margin rows can print `$90k-$342k`, but they do not satisfy the quality profile.

Examples:

| Candidate | PnL | WR | PF | Risk Issue |
|---|---:|---:|---:|---|
| XAU ORB dynamic monthly reset Monday filter | `$100,981` | `46.46%` | `2.08` | max stop risk about `96.8%` |
| XAU ORB max-margin leverage 50 | `$146,921` | `52.54%` | n/a | max risk about `48.4%` |
| XAU ORB max-margin leverage 100 | `$342,674` | `52.54%` | n/a | max risk about `96.8%` |

These rows are useful as a warning:

```text
Yes, $100k can be printed in a spreadsheet.
No, this is not the same as a robust tradable edge.
```

They fail the requested WR band and rely on extremely aggressive risk.

Verdict:

`Reject as base. Keep only as stress/upper-bound reference.`

## Category 3 - Robust Portfolio, Still Too Small

The long/short monthly reset portfolio is more practical, but much smaller.

Best row:

| Metric | Value |
|---|---:|
| Variant | `more_trades_long_winner + max_pnl_short_38` |
| Trades | `430` |
| Net PnL | `$12,428.99` |
| WR | `63.26%` |
| PF | `3.63` |
| Max DD | `-7.01%` |
| Positive years | `7 / 8` |

This has acceptable WR and drawdown, but PF is above the requested band and PnL is far below `$100k`.

To turn `$12.4k` into `$100k`, risk would need to be scaled about `8x`.

That would likely push drawdown into unacceptable territory unless capital is also scaled.

Verdict:

`Research-only. Useful portfolio sleeve, not $100k engine.`

## Practical Interpretation

The current data says:

```text
$100k/year is possible only with larger capital, excessive risk, or more independent sleeves.
```

If we refuse curve fitting and refuse reckless risk, the only honest route is:

1. keep SupplyDemand top-3 union as one sleeve,
2. keep ORB/A+ or meta-stack as a second sleeve,
3. add a true short-side sleeve,
4. add cross-asset sleeve only if cost stress survives,
5. use drawdown-aware sizing,
6. target `$100k/year` at portfolio level, not one-strategy level.

## Required Annual R

At different risk sizes:

| Risk Per Trade | R/year Needed For `$100k` |
|---:|---:|
| `$250` | `400R/year` |
| `$500` | `200R/year` |
| `$1,000` | `100R/year` |
| `$2,000` | `50R/year` |
| `$3,135` | `31.89R/year` |

Current clean SupplyDemand expansion:

```text
31.89R/year
```

So it can hit `$100k/year` only around `$3,135` risk per trade.

## PDF Integration

The PDF is helpful, but as a roadmap:

- ORB + VWAP + Volume Profile context
- FVG degree proxy
- IFVG trap shorts
- OB/FVG confluence
- drawdown-aware sizing

It does not create a verified `$100k/year` edge by itself.

The next non-curve-fit experiments should be:

1. **IFVG trap short sleeve**
   - goal: add independent short-side R
   - must pass yearly/OOS/MC/cost tests

2. **ORB + VWAP + VAH/VAL filter**
   - goal: keep ORB revenue while improving WR/PF
   - Volume Profile should be context, not standalone

3. **M1-safe FVG degree proxy**
   - goal: filter chaotic FVGs and keep systematic imbalances
   - must be tested only pre-entry

4. **Portfolio drawdown-throttled sizing**
   - goal: scale only when portfolio drawdown risk allows
   - reject max-margin style risk

## Final Verdict

Current evidence does **not** support a `$100k/year` small-account strategy under the requested constraints.

Current evidence **does** support:

```text
A 30R/year clean SupplyDemand sleeve.
A 7-13k dollar portfolio sleeve under $5k reset assumptions.
A high-risk ORB upper bound that can reach $100k but fails risk/WR quality.
```

To reach `$100k/year` honestly, we need either:

- about `$63k-$313k` capital depending on risk percentage, or
- several additional independent sleeves that each contribute meaningful annual R, or
- accepting risk levels that are not compatible with robust trading.

Promotion verdict:

```text
Do not promote any $100k small-account configuration yet.
Continue research through independent-sleeve expansion.
```
