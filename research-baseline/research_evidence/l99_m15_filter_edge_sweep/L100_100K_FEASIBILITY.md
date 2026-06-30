# L100 100K Per Year Feasibility

## Question

Can the current `m15_2c_1atr` Supply/Demand research universe realistically produce `$100k/year` without curve fitting while keeping performance close to the current balanced candidate?

Current balanced candidate:

- WR: `64.11%`
- PF: `1.68`
- Net: `111.36R`
- Average annual R across 8 calendar years: `13.92R/year`

Accepted quality band from the request:

- WR within `+/- 5%`: `59.11%` to `69.11%`
- PF within `+/- 1`: `0.68` to `2.68`

## Main Finding

The current single candidate is far too small for `$100k/year` unless risk per trade is very large.

At `13.92R/year`, the required risk per trade for `$100k/year` average is:

```text
100,000 / 13.92 = $7,184 risk per trade
```

Approximate capital needed:

| Risk % | Capital Needed |
|---:|---:|
| 1% | `$718k` |
| 2% | `$359k` |
| 5% | `$144k` |

## Best Current Expansion

I tested unioning robust candidates that already passed the primary gates and stayed inside the WR/PF band.

The cleanest expansion is the **Top-3 strict OR union**.

It combines:

1. `base_body_low+cost_le_0p05+ema8_aligned+ny_main_or_overlap`
2. `avoid_after_hours+body_ge_45+cost_le_0p05+dir_demand+orb_reversal`
3. `avoid_after_hours+body_ge_70+cost_le_0p05+orb_reversal`

## Top-3 Union Metrics

| Metric | Value |
|---|---:|
| Trades | `1,040` |
| Net R | `255.14R` |
| Average R/year | `31.89R` |
| WR | `63.75%` |
| PF | `1.67` |
| Max DD | `-12.69R` |
| Train net R | `55.80R` |
| Train PF | `1.47` |
| Train WR | `60.78%` |
| OOS net R | `199.35R` |
| OOS PF | `1.77` |
| OOS WR | `64.99%` |

This keeps the WR/PF profile close to the current candidate and more than doubles annual R.

## Yearly Breakdown

| Year | Trades | Net R | WR | PF |
|---:|---:|---:|---:|---:|
| 2019 | `12` | `1.59R` | `58.33%` | `1.31` |
| 2020 | `132` | `27.11R` | `62.12%` | `1.53` |
| 2021 | `70` | `10.44R` | `58.57%` | `1.39` |
| 2022 | `92` | `16.65R` | `60.87%` | `1.48` |
| 2023 | `75` | `1.04R` | `53.33%` | `1.03` |
| 2024 | `158` | `39.38R` | `63.92%` | `1.70` |
| 2025 | `296` | `81.32R` | `65.20%` | `1.77` |
| 2026 | `205` | `77.61R` | `69.76%` | `2.25` |

Weak point: `2023` is barely positive and has poor PF/WR. This is still not a clean `$100k every year` system.

## PnL Translation

Top-3 union average:

```text
31.89R/year
```

| Risk Per Trade | Avg Yearly PnL |
|---:|---:|
| `$250` | `$7,973/year` |
| `$500` | `$15,946/year` |
| `$1,000` | `$31,893/year` |
| `$2,000` | `$63,786/year` |
| `$3,135` | `$100,000/year average` |

Approximate capital required:

| Risk % | Capital Needed |
|---:|---:|
| 1% | `$313k` |
| 2% | `$157k` |
| 5% | `$63k` |

## Bigger But Dirtier Expansion

The Top-10 strict OR union reaches:

- Trades: `1,417`
- Net: `274.97R`
- Average: `34.37R/year`
- WR: `61.12%`
- PF: `1.50`

But train WR falls to `58.02%`, below the requested band, and 2023 remains weak:

- 2023 net: `4.13R`
- 2023 PF: `1.09`
- 2023 WR: `54.55%`

So Top-10 is more revenue, but lower quality. It is not the clean answer.

## Verdict

The current Supply/Demand sleeve can be expanded from about `14R/year` to about `32R/year` without obviously destroying PF/WR.

But `$100k/year` is still not realistic from this sleeve unless:

1. risk per trade is around `$3.1k`, or
2. account size is around `$63k` at 5% risk, `$157k` at 2% risk, or `$313k` at 1% risk, or
3. we add multiple independent strategy sleeves.

The honest answer:

```text
This sleeve can be a contributor.
It is not a standalone $100k/year engine.
```

Next research should focus on independent R sources, not squeezing this same edge harder:

- NY ORB long/short sleeve
- short-side-only supply strategy
- M5 intraday reclaim model
- trend-day continuation model
- cross-asset tests on Brent, NAS100, S&P, EURUSD

The target is not one 400R/year curve-fit monster. The target is a portfolio of independent 30R-80R/year sleeves that survive stress independently and together.

## PDF Addendum

The external PDF `/Users/subash/Desktop/Quantizing XAUUSD Trading Strategy.pdf` was reviewed after this feasibility pass.

It is useful as a research roadmap, not as a promoted edge. It reinforces the portfolio direction:

- ORB as the primary intraday timing engine
- London-New York overlap and DST-aware session handling
- VWAP / Volume Profile as context
- FVG / IFVG / OB as structural confluence
- drawdown-aware sizing
- walk-forward validation

Most of those concepts are already covered in local research. The genuinely useful new ideas are:

1. an M1-safe FVG degree proxy,
2. a standalone IFVG trap short sleeve,
3. ORB + VWAP + VAH/VAL filtering,
4. portfolio-level CVaR/drawdown-aware sizing.

See:

`L101_PDF_STRATEGY_INTEGRATION.md`
