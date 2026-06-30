# SDR-001 DWX M1 Export Resolution

Date: 2026-06-29

## Objective

Prepare the SDR-001 live engine for a real paper-live dry-run using broker-exported XAUUSD M1 bars.

The SDR-001 engine has now passed real DWX M1 dry-run certification. This document records the original blocker and the fix.

## Current DWX Bridge Status

DWX folder checked:

`/Users/subash/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX`

Files currently present:

| File | Status |
|---|---|
| `account_info.json` | present |
| `market_data.json` | present |
| `open_orders.json` | present |
| `bars_XAUUSD_ecn_M3.json` | present |
| `bars_XAUUSD_ecn_H1.json` | present |
| `bars_XAUUSD_ecn_D1.json` | present |
| `bars_XAUUSD_ecn_M1.json` | present, 5000 rows |

## Original Blocker

The live DWX bridge was active, but it was not exporting `bars_XAUUSD_ecn_M1.json`.

SDR-001 should not be paper-live certified using synthetic M1 bars derived from M3 data. That would change the entry timing and invalidate the "to the dot" close-based live execution audit.

## Source Search Result

Local search did not find the DWX server EA source/config on this Mac at first.

Expected historical VPS path:

`C:\hand-of-midas\mql5\DWX_Server.mq5`

The `midas-deploy` branch contains the DWX server source:

`https://github.com/SubashMourougayane/hand-of-midas/blob/midas-deploy/mql5/DWX_Server.mq5`

Local patched checkout:

`/Users/subash/SUBASH/hand-of-midas/mql5/DWX_Server.mq5`

## Patch Applied Locally

The EA previously exported only `M3`, `H1`, and `D1`:

```mql5
WriteSymbolBars(g_symbols[i], PERIOD_M3, 100, "M3");
WriteSymbolBars(g_symbols[i], PERIOD_H1, 30, "H1");
WriteSymbolBars(g_symbols[i], PERIOD_D1, 5, "D1");
```

The local checkout now exports `M1` as well:

```mql5
WriteSymbolBars(g_symbols[i], PERIOD_M1, 5000, "M1");
WriteSymbolBars(g_symbols[i], PERIOD_M3, 100, "M3");
WriteSymbolBars(g_symbols[i], PERIOD_H1, 30, "H1");
WriteSymbolBars(g_symbols[i], PERIOD_D1, 5, "D1");
```

The EA version string was bumped from `2.14` to `2.15` so MT5 logs can confirm the patched bridge is running.

MT5 log confirmed the patched bridge is running:

```text
[DWX] Server started v2.15 (M1 bars + Filter #27 + poll-cancel + retcode-accept + per-cmd-response + history-retry)
```

## Required Fix

Completed: compile and reload the patched DWX server EA so it exports XAUUSD.ecn M1 bars.

Output:

`bars_XAUUSD_ecn_M1.json`

Recommended history depth:

At least 1,500 M1 bars, preferably 5,000 M1 bars if the bridge remains stable. SDR-001 can run with less for streaming, but deeper M1 history gives safer warmup for M15/H1-derived state and zone expiry checks.

If the EA uses a timeframe list, add:

`PERIOD_M1`

for:

`XAUUSD.ecn`

If the EA writes named output files, the normalized symbol file must be:

`bars_XAUUSD_ecn_M1.json`

## Acceptance Test Result

After compiling/reloading the DWX server EA in MT5:

1. Confirmed this file appears and updates:

   `bars_XAUUSD_ecn_M1.json`

2. Confirmed it contains 5000 M1 bars for `XAUUSD.ecn`.

3. Real paper-live dry-run completed:

   ```bash
   python3 -m bt_engine.runner.cli live --strategy sdr001 --symbol XAUUSD.ecn --timeframe M1 --dry-run --max-ticks 500 --poll-interval 0.2
   ```

4. Certification evidence:

   - `run_id`: `f78279db-f167-4938-b641-8292b5a9c028`
   - `bars_processed`: 500
   - `closed_trades`: 2
   - `bt_runs`: 1
   - `bt_trades`: 3
   - `bt_signals`: 3
   - `bt_journal_events`: 5
   - `bt_bar_walk`: 61
   - `bt_account_snapshot`: 500
   - `open_orders.json`: `{}`
   - `pending_orders.json`: `{}`

## Current Certification State

Resolved. Real MT5/DWX M1 dry-run certification passed.
