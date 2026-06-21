# A0 — Reference BT intra-H1 lookahead in M3 engulfing search

## What this fix does and does not do

### Does
- Patches `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` line 136 so the M3 engulfing search starts at the H1 sweep bar's CLOSE time (`sbar_ts + 1 hour`), not at its OPEN time (`sbar_ts`).
- Re-runs the full Oil Micro BT with the patched search anchor.
- Reports the new BT P&L vs the previous (lookahead) numbers.

### Does not
- Touch live code, scheduler code, or live engine logic.
- Change any strategy parameters or filters.
- Change Gold Micro signal-gen (different file, separate concern).
- Refactor anything else.
- Change the engulfing window length, sweep detection, bias filter, or any other concept.

If the diff includes anything not in the "Does" list, the fix is wrong. Reject it.

## The bug

### Evidence chain
1. JustMarkets server time = GMT+3 (EET). Confirmed by user via JM web platform.
2. JM CSV data (`data/raw/BCO_USD_*.csv`, `data/raw/XAU_USD_*.csv`) stamps timestamps with `+00:00` suffix but values are in broker-local time (GMT+3). Verified by matching the visible big-red XAU candle at chart-time `2026-06-17 21:00` against CSV row `2026-06-17 21:00:00+00:00` — same OHLC.
3. MT5 H1 bars are open-time labeled (broker convention). The bar timestamped `21:00` covers `[21:00, 22:00)` and is only fully formed at `22:00`.
4. Live cron at any time `T` cannot know the OHLC of the H1 bar timestamped `T` until the bar closes at `T + 1 hour`.
5. The reference signal-gen at `backend-oil-micro/strategies/micro_alpha_sweep_oil.py:136` searches M3 candles starting at `oil_m3.index > sbar_ts` — i.e. inside the still-forming H1 sweep bar.
6. This means the reference can find an "engulfing" on M3 bars that close BEFORE the H1 sweep bar closes — using future-relative-to-live information to enter.

### Independent corroboration
Codex re-implemented the strategy from the spec on the same JM data. With the H1-close anchor (`sbar_ts + 1h`), it got −$22k / 7yr losing PF<1. With the H1-open anchor (matching the reference), it got +$711k / 65% WR. Same strategy, same data — only difference is whether M3 bars before the H1 sweep close are visible to the engulfing search. **The +$2.23M reference number runs on the same lookahead.**

### Why this hasn't been caught
- Live and BT both consume the same CSV; the timezone mislabeling is symmetric.
- Live cron only reads bars whose `bar_ts <= now`, so live cannot reproduce the lookahead.
- The "drift bug #6" memory entry shows the project has a history of catching subtle BT lookaheads that don't surface in live. This is the same class.
- Yearly capital reset masks compound damage from the false BT edge — each year resets to $5K so even huge BT P&L doesn't collapse the next year.

## The fix

Change one line. Bias toward minimal intervention.

**Line 135-136 currently:**
```python
eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
m3_window = oil_m3[(oil_m3.index > sbar_ts) & (oil_m3.index <= eng_end)]
```

**Patched to:**
```python
sweep_close = sbar_ts + timedelta(hours=1)
eng_end = sweep_close + timedelta(hours=cfg["engulfing_window_hours"])
m3_window = oil_m3[(oil_m3.index > sweep_close) & (oil_m3.index <= eng_end)]
```

This makes the BT engulfing search start AFTER the H1 sweep bar's close. The M3 window is still `engulfing_window_hours = 0.75 hr = 45 min` long, just shifted to start at sweep_close instead of sweep_open.

## Acceptance criteria

The fix is accepted if and only if:

1. **Diff is exactly 3 lines changed in 1 file.** If it grows, scope is wrong.
2. **No new constants, no helper functions, no schema changes.**
3. **Re-run BT** via `python scripts/run_oil_micro_full.py` produces a number we can read.
4. **Old number for comparison:** $2,234,838 / 71.19% WR / PF 4.26 (this morning's run, neutral bias, lookahead version).
5. **Number written down in this doc, regardless of outcome** — even if the strategy turns out to lose money, that's the point of the exercise.

## What I will NOT do

- Touch `backend-micro/strategies/micro_alpha_sweep.py` (Gold Micro). Same bug class likely lives there too but Gold Micro fix is its own decision.
- Patch the live engine. Live already has the correct semantics by virtue of cron-tick visibility.
- Add tests. The BT number is the test.
- Commit. Diff sits on disk awaiting user approval.
- "Improve" anything else "while I'm here."

## Rollback

```
git checkout midas-deploy -- backend-oil-micro/strategies/micro_alpha_sweep_oil.py
```

## Sign-off

User reads the new BT number, decides:
- Approve → commit the patch
- Reject → revert
- "Run Gold Micro version too" → separate task

I do not commit without explicit approval.

## Status when this doc was written

Bug confirmed via H1/M3 timestamp analysis on JM XAU data. Patch not yet applied. Next step: apply the 3-line change, run the BT, report the number HERE in this doc.
