# Loss-Reduction Filter Research — Post-Hoc

Baseline BT: fib_v2_intraday_a_plus_d (run `b6604240-14f4-464f-86b4-0d0e32755838`), 27,950 trades over 22 years XAU, Model B 1.5% sizing.

**Approach**: post-hoc filter on existing trade ledger. NO strategy code changes. For each trade:
1. Look up its entry_timestamp
2. Compute filter value from bars STRICTLY BEFORE that timestamp (causal)
3. Accept/reject the trade
4. Recompute headline over the surviving subset

Zero look-ahead. No re-BT. Standalone script: `research-baseline/candidate_filters/loss_reduction_filters.py`.

## Results

| Filter | Trades | WR | Net $ | vs base | PF | MaxDD R |
|---|---:|---:|---:|---:|---:|---:|
| **BASELINE** | 27,950 | 48.92% | **+$850,710** | — | 1.590 | −73.0R |
| A · momentum EMA5 slope aligned | 4,952 | 48.28% | +$141,258 | −83% | 1.551 | −57R |
| B · ATR14 < 0.5× 20d median (skip) | 27,921 | 48.92% | +$848,477 | −0.3% | 1.591 | −73R |
| **C · H1 body aligned with side** | **10,417** | **60.60%** | +$726,189 | −14.6% | **2.999** | **−22.9R** |
| A+B | 4,944 | 48.30% | +$142,373 | −83% | 1.559 | −57R |
| A+C | 2,712 | 56.97% | +$160,262 | −81% | 2.485 | −26R |
| B+C | 10,404 | 60.58% | +$722,821 | −15% | 2.994 | −23R |
| A+B+C | 2,707 | 56.96% | +$160,476 | −81% | 2.495 | −26R |

## Verdicts

### Filter A · momentum EMA5 slope aligned — **REJECTED**

Requiring EMA5 slope in the trade's direction cuts 82% of trades AND 83% of $. Dropped 11,282 winners vs 11,716 losers — nearly 1:1. **Strategy is retrace mean-reversion; it needs momentum AGAINST direction at signal time.** Filter is inverted to actual edge.

### Filter B · ATR compression skip — **REJECTED (no signal)**

Only drops 29 of 27,950 trades. Threshold (ATR14 < 50% of 20d median) never triggers meaningfully on XAU M15 spanning 22 years. Effectively a no-op. Would need looser threshold OR different volatility metric.

### Filter C · H1 body aligned with signal direction — **KEEP**

- WR jumps 49% → **61%**
- PF **doubles** 1.59 → **3.00**
- Max drawdown **cut 68%** (−73R → −22.9R)
- $ hit: −14.6% ($850k → $726k)

Risk-adjusted return dramatically better. The 14.6% net drop is offset by ability to size up: with DD cut ~3× we could raise Model B `risk_pct` from 1.5% → ~3% and retain (or exceed) baseline net$ with same equity floor.

## Follow-ups (not yet done)

1. Run Filter C at 2.5% and 3% risk_pct to test if $ recovers past baseline
2. Test C variations: last-2 H1 aligned, H1 close > mid instead of body direction
3. Check filter's Sharpe / annual returns / positive-year count
4. Verify no season/year regime bias in which trades C keeps

## Filter C characterisation (what it keeps)

- 10,417 kept: 6,313 winners + 4,104 losers = **60.6% WR**
- 17,533 dropped: 7,360 winners + 10,173 losers = 42% WR
- Filter is doing exactly what filter should do: keeping high-quality subset

## Method note (causality guarantee)

- Filter A: uses M15 slope[t < entry_ts] — bar[k-1] and earlier
- Filter B: uses D1 ATR14 from prior-closed daily bar (D_i where D_i < entry_ts.date)
- Filter C: uses last H1 bar with timestamp < entry_ts

No filter uses ANY bar at/after entry_timestamp. Slope/ATR/H1 body values are computable in real-time at signal decision moment.
