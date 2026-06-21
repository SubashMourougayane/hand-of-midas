# 003 — Overnight Drift on Brent: Result

**Source:** Branch & Ma (2008) "Overnight Return, the Invisible Hand Behind the Intraday Returns?" + commodity-futures follow-ups.
**Status:** TRUSTED — break-even, not exploitable.

## Config

Hold from ~21:00 UTC to ~14:00 UTC next session (~17 hours). 5% safety SL.

## Results (both directions)

| Direction | Trades | WR % | PF | P&L | Max DD |
|---|---:|---:|---:|---:|---:|
| LONG | 1,097 | 51.23 | **1.008** | **+$364** | 70.8 % |
| SHORT | 1,097 | 44.67 | 0.817 | −$8,756 | 59.9 % |

## Year-by-year (LONG)

| Year | Trades | WR % | P&L | DD % |
|---|---:|---:|---:|---:|
| 2019 | 68  | 47 | +$119  | 6  |
| 2020 | 259 | 45 | −$2,617 | 71 |
| 2021 | 258 | 55 | +$2,371 | 18 |
| 2022 | 258 | 52 | +$939   | 44 |
| 2023 | 254 | 54 | −$260   | 18 |

## Honest interpretation

LONG overnight on Brent shows a measurable but TINY drift edge. PF 1.008 over 1,097 trades = ~$0.33 net per trade. Slippage + commission on Brent (per JustMarkets ECN: ~$7/lot RT + ~3¢ slippage on this size of trade) would consume the entire edge.

The 2020 catastrophe is COVID — Brent went briefly negative, intraday holds got margin-called. 2021-2022 recovery is positive but barely. Average day = noise.

**The published "overnight effect" is real on Brent at the population level, but at the individual-trade level it's less than transaction costs. Not exploitable on a small account.**

## Verdict

Not promoted. Real signal but too small. A larger account with cheaper execution might extract it; not a candidate for our setup.

## Safeguards
- Lookahead PASS, random baseline PASS, both directions.

## Reproduce
```bash
python Labs/strategies/003_overnight_drift_brent.py
```
