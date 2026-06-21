# Labs — Public Brent Oil Strategies, Honestly Tested

> Sister folder to `R&D/`. Different purpose. Same discipline.

## Purpose

Survey publicly-documented intraday strategies for Brent crude oil (or that adapt cleanly to it), code each as a single self-contained Python file, run all of them through the SAME honest backtest engine, and compare results in one table.

The goal is NOT to find a magic strategy. The goal is to learn which classes of strategy have any signal at all on JM 7-year BCO_USD data, given honest fills and honest costs.

## Hard rules — non-negotiable

1. **Live-reproducible.** Every strategy uses ONLY data that would be available at decision time. No lookahead. Every strategy ships with a paired lookahead-audit run.
2. **One fill model for all.** Same gap → SL → TP → max-hold walk. Same `_sl_slip` slippage formula. If two strategies' P&L differ, it must be the signal generator, not different fill assumptions.
3. **Random-baseline check per strategy.** After every run, a random-entry baseline goes through the same fill model. If random earns money → BT is broken, the result is discarded.
4. **No live trading from Labs.** Research code only. Even if a strategy looks great. Promotion to live is a separate decision after a separate validation phase.
5. **One strategy = one Python file.** Self-contained. Has its own docstring naming the source paper / blog / book the concept comes from.
6. **No imports from production code.** Same isolation principle as R&D. Labs reads dev data via `Labs/shared/data.py`, which thin-wraps `R&D/data_split.py`. No `from backend.* import ...`.
7. **Honest reporting.** Every results file includes:
   - Total trades, wins, losses, win rate
   - Profit factor, total P&L, max DD
   - Annual breakdown (yearly-reset basis)
   - Random-baseline comparison
   - Lookahead audit pass/fail
   - Caveats / known limitations

## Structure

```
Labs/
├── README.md                          # this file
├── shared/
│   ├── data.py                        # gateway (wraps R&D/data_split.py)
│   ├── fill_model.py                  # canonical exit walk
│   ├── runner.py                      # strategy → BT → stats
│   ├── safeguards.py                  # lookahead audit + random baseline
│   └── stats.py                       # PF / WR / DD / yearly breakdown
├── strategies/
│   ├── 001_*.py                       # one per strategy
│   └── ...
└── results/
    ├── 001_*.md                       # one results doc per strategy
    └── comparison_table.md            # combined view
```

## Strategy candidates (Sprint 1)

Each one has a one-line public-source citation. Goal: find concept descriptions, re-implement from scratch in our framework. NEVER copy code.

1. **001 — Opening Range Breakout (ORB).** Toby Crabel, "Day Trading with Short-Term Price Patterns" (1990). Wait for the first N minutes of session, breakout of that range = entry.
2. **002 — VWAP mean reversion.** Common institutional execution pattern; many published quant blogs. Fade extensions ≥ X×ATR from VWAP back to VWAP.
3. **003 — Overnight drift (close-to-open).** Branch & Ma 2008 and others document a persistent close → open drift effect on commodity futures.
4. **004 — Donchian channel breakout.** Richard Donchian / Turtle Traders. Buy 20-day high, sell 10-day low, etc. Adapted to intraday timeframe.
5. **005 — Wednesday EIA mean reversion.** Brent-specific. EIA inventory release at 14:30 UTC creates predictable intraday volatility pattern; mean-reverting fade after the immediate spike.

These are not picked because I expect them to work. They are picked because they're conceptually distinct (breakout, mean-reversion, drift, trend, news-event), so the comparison table tells us which CLASS of strategy has any signal on this data.

## What "winning" looks like

A strategy is interesting if and only if ALL of:

- PF > 1.10 across the 7-year dev window (modest is fine — we're hunting signal, not magic)
- Max drawdown < 50% on yearly-reset basis
- Lookahead audit: PASS
- Random baseline run on same fill model: NEGATIVE P&L (proves BT engine isn't biased)
- Non-trivial trade count (> 100 trades over 7 years; otherwise too few samples to trust)

If a strategy passes all five, it goes on a shortlist. The shortlist gets a second look (parameter sensitivity, validation/holdout split). Nothing in Labs goes anywhere near live until that second pass.

## Branch

Labs lives on `feature/rnd-lab` alongside R&D. If a strategy proves out and graduates, that's a separate branch decision.

## What is NOT in Labs

- Any code from `backend/`, `backend-micro/`, `backend-oil-micro/`
- Any imports from external pattern libraries (Mobius, mcpmarket, ICT/SMC packages)
- Any live data API
- Any strategy that requires data outside the dev window
- Any "optimized" parameters from prior work — every strategy starts with parameters from its source citation, no tuning until baseline result is recorded
