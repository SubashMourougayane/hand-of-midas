# SDR-001 BT Engine Causality Hardening

Date: 2026-06-29

## What Changed

SDR-001 feature generation is now time-aware for live/replay use.

The core event universe is unchanged:

- Zone detection is unchanged.
- Retest/confirmation logic is unchanged.
- Entry/SL/1R outcome logic is unchanged.
- Raw full-sample parity still passes.

The hardened area is the forward feature layer.

## Fix 1: Entry Context Uses Previous Closed M5

Before:

- `add_event_rule_features()` merged M5 context on `entry_timestamp`.
- M5 bars are left-labelled.
- A row stamped `10:05` represents the `10:05-10:09` candle.
- At a `10:05` entry, that candle has not closed.
- Therefore `entry_ema8`, `entry_close`, `entry_close_location`, and ORB state could use information from the entry bar itself.

After:

- Feature context is attached with `timestamp < entry_timestamp`.
- Exact timestamp matches are not allowed.
- New column: `entry_context_timestamp`.
- Existing fields such as `entry_atr`, `entry_ema8`, `entry_close`, `entry_close_location`, `orb30_state`, and `orb15_state` now come from the prior fully closed M5 bar.

## Fix 2: ORB Context Is No Longer Painted Over The Whole Day

Before:

- Once a day's ORB was computable, `add_orb_context()` wrote that ORB state onto every bar of that NY date.
- That allowed pre-ORB trades to know same-day ORB state.

After:

- `orb15_state` is `missing` until the first 15-minute ORB window has closed.
- `orb30_state` is `missing` until the first 30-minute ORB window has closed.
- Rows before those times do not receive ORB high/low/state.
- Live validation still blocks ORB forward flags until we separately promote a clean ORB rule.

## Existing SDR-002 Clean Candidate

`sdr002_clean` remains based on:

```text
closed_m15_ema8_aligned
intraday_stack_24h
ny_main_or_overlap
cost_le_0p05
body_ge_45
base_body_low
```

It does not use ORB flags.

## Verification

Passed:

```text
python3 -m pytest bt_engine/tests/unit/strategies/sdr001/test_strategy.py -q
15 passed

python3 -m pytest bt_engine/tests/parity/test_raw_data_parity.py -q
1 passed

python3 -m pytest bt_engine/tests/parity/test_incremental_parity.py -q
1 passed
```

## Guard Tests Added

- Exact-entry M5 context is ignored; previous closed M5 is used.
- M15 EMA context is strictly previous closed M15.
- Intraday stack excludes future zones and excludes the current zone.
- ORB state remains `missing` before the ORB window is complete.
- ORB forward flags are rejected for live use.

## Remaining Policy

Do not use `orb_reversal`, `orb_continuation`, or `orb_inside` in live rules until a separate ORB candidate is explicitly recut and promoted under the causal ORB model.
