# SDR-001 Paper-Live Certification

Date: 2026-06-29

Scope:

- `/Users/subash/SUBASH/GoldDigger/bt_engine`
- SDR-001 live runner path
- DWX bridge readiness
- Dry-run order execution
- DB persistence
- Restart reconciliation

## Verdict

SDR-001 real DWX M1 dry-run certification passed.

DWX live broker-paper execution certification also passed on the connected demo account.

SDR-001 non-dry-run live rehearsal also passed in no-signal mode: it processed fresh M1 bars only, did not replay the DWX backlog, and placed no trade because no SDR setup occurred during the supervised window.

Current DWX status:

```text
DWX bridge alive: yes
account_info.json: fresh
market_data.json: fresh
open_orders.json: fresh
bars_XAUUSD_ecn_M1.json: present, 5000 rows
bars_XAUUSD_ecn_M3.json: present
bars_XAUUSD_ecn_H1.json: present
```

SDR-001 correctly requires `M1`, so the engine should not be run on `M3` or `H1` as a substitute.

## Real DWX M1 Dry-Run Certification

After patching and reloading `DWX_Server.mq5` v2.15, the bridge began writing:

```text
bars_XAUUSD_ecn_M1.json
```

Run:

```text
run_id: f78279db-f167-4938-b641-8292b5a9c028
run_ref: LIVE-20260629-SDR001-0001-f78279db
mode: live
strategy: sdr001
symbol: XAUUSD.ecn
timeframe: M1
dry_run: true
data_provider: dwx-live
bars_processed: 500
closed_trades: 2
```

DB rows written:

```text
bt_runs: 1
bt_trades: 3
bt_signals: 3
bt_journal_events: 5
bt_bar_walk: 61
bt_account_snapshot: 500
```

Trade outcome:

```text
closed trades: 2
open trades at bounded-run stop: 1
wins: 1
losses: 1
closed net_r: -0.2406923820
```

Timestamp audit:

```text
all closed trades exit after entry: yes
signal timestamps use strategy entry time: yes
dry-run fill timestamps use bar time: yes
```

DWX broker-state audit after dry-run:

```text
open_orders.json: {}
pending_orders.json: {}
```

Result:

Pass. The engine read real broker-exported M1 bars, processed a bounded dry-run, persisted signals/trades/journal/bar-walk/account snapshots, and left no real/pending broker orders.

## Live Demo Broker Execution Certification

Account pre-check:

```text
server: JustMarkets-Demo2
currency: USD
balance before: 8985.27
equity before: 8985.27
open_orders.json before: {}
pending_orders.json before: {}
```

Test order:

```text
symbol: XAUUSD.ecn
side: BUY
volume: 0.01 lots
tag/comment: SDR001_LIVE_CERT_MINLOT
SL: 4044.78
TP: 4084.87
```

Open response:

```text
success: true
ticket: 2106794897
open_price: 4064.87
volume: 0.01
retcode: 10009
comment: Request executed
```

DWX open-order mirror after submit:

```text
ticket: 2106794897
symbol: XAUUSD.ecn
type: BUY
volume: 0.01
open_price: 4064.87
sl: 4044.78
tp: 4084.87
magic: 200000
comment: SDR001_LIVE_CERT_MINLOT
```

Close response:

```text
success: true
ticket: 2106794897
close_price: 4065.00
retcode: 10009
comment: Request executed
```

Post-close state:

```text
balance after: 8985.33
equity after: 8985.33
margin after: 0.0
open_orders.json after: {}
pending_orders.json after: {}
```

Result:

Pass. The live DWX command path can open a minimum-lot demo order, mirror it through `open_orders.json`, close it, and return the account to flat state.

## SDR-001 Non-Dry-Run Live Rehearsal

Before running SDR in real broker mode, live safety gates were added:

```text
require demo account: true
max live lot: 0.01
max open positions: 1
max spread: 0.50
kill switch: /Users/subash/SUBASH/GoldDigger/LIVE_DISABLED
```

An MT5 server-time issue was also found and fixed:

```text
DWX bar timestamps are MT5 server time.
JustMarkets current offset inferred: UTC+3.
Live provider now converts MT5 server timestamps back to UTC before closed-bar checks.
```

Run:

```text
run_id: 57a186cc-0581-4788-9666-077b2bed99c0
run_ref: LIVE-20260629-SDR001-0001-57a186cc
mode: live
strategy: sdr001
symbol: XAUUSD.ecn
timeframe: M1
dry_run: false
server_utc_offset_hours: 3
max_live_lot: 0.01
max_open_positions: 1
max_spread: 0.50
bars_processed: 3
```

DB rows written:

```text
bt_runs: 1
bt_account_snapshot: 3
bt_signals: 0
bt_trades: 0
bt_journal_events: 0
bt_bar_walk: 0
```

Post-run broker state:

```text
open_orders.json: {}
pending_orders.json: {}
balance: 8985.33
equity: 8985.33
margin: 0.0
```

Result:

Pass. SDR-001 live mode consumed fresh M1 bars only, stayed flat when there was no signal, and did not place any accidental historical/backlog trade.

## Earlier Controlled SDR Dry-Run Certification

Before the DWX M1 export was patched, I ran SDR-001 through the same live runner using:

- temporary DWX directory,
- M1 bar feed,
- SDR-001 strategy,
- dry-run broker,
- PostgreSQL test DB,
- known historical M1 slice with a real SDR event.

Run:

```text
run_id: e83f150d-08e5-48ce-bb2d-e8b43415612f
run_ref: LIVE-20260629-SDR001-0001-e83f150d
bars_processed: 22
closed_trades: 0
event_entry_timestamp: 2020-01-06 08:50:00+00:00
event_zone_id: 4
event_direction: supply
```

DB rows written:

```text
bt_runs: 1
bt_signals: 1
bt_trades: 1
bt_journal_events: 1
bt_bar_walk: 20
bt_account_snapshot: 22
```

Trade persisted:

```text
symbol: XAUUSD.ecn
timeframe: M1
zone_id: 4
direction: supply
side: -1
entry_price: 1574.15
stop_price: 1578.0971428571427
take_profit_price: 1570.2628571428575
risk_units: 3.9171428571426077
```

Signal persisted:

```text
status: ENTRY_SUBMIT
zone_id: 4
direction: supply
entry_price: 1574.18
stop_price: 1578.0971428571427
risk_units: 3.9171428571426077
```

Journal persisted:

```text
event_type: ENTRY_FILL
symbol: XAUUSD.ecn
side: -1
qty: 1.0
price: 1574.15
tag: sdr001_zone_4
```

Result:

Pass. The live runner created the run, emitted an SDR signal, opened a dry-run trade, and wrote the audit trail.

## Restart-Recovery Smoke

During certification, dry-run mode initially could not test restart reconciliation because the dry-run broker returned no bridge positions. I fixed that so dry-run mirrors `open_orders.json` while still not submitting real orders.

Restart smoke rerun:

```text
run_id: 3b007b3b-25fe-468a-9b0d-6a9fec4d30ff
run_ref: LIVE-20260629-EMA_CROSS-0001-3b007b3b
bars_processed: 1
```

DB rows written:

```text
bt_runs: 1
bt_trades: 1
bt_bar_walk: 1
bt_account_snapshot: 1
```

Recovered position:

```text
symbol: XAUUSD.ecn
side: 1
entry_price: 100.0
stop_price: 90.0
take_profit_price: 120.0
```

Result:

Pass. A broker-side open position is reconstructed, persisted, and bar-walked in dry-run.

## Fixes Discovered During Certification

Four practical paper-live gaps were found and fixed:

1. Dry-run broker now reads bridge positions from `open_orders.json`.
2. Engine now commits bar-walk rows for still-open positions by running the live runner's bar-close persistence callback after bar-walk observation.
3. Dry-run broker fill timestamps now use the current bar timestamp, not wall-clock execution time.
4. Real non-dry-run live startup now skips already-closed DWX backlog bars and ignores historical SDR events before that live start point.
5. Real live broker mode now has safety gates: demo-only, max lot cap, one-position limit, spread guard, and kill-switch file.
6. Real live provider now converts MT5 server timestamps to UTC before closed-bar checks.
7. Bounded live rehearsals can now use `--max-wait` so they wait long enough for fresh M1 bars without running indefinitely.

Regression tests were added for these paths.

## Final Test Suite

```text
cd /Users/subash/SUBASH/GoldDigger/bt_engine
python3 -m pytest
171 passed, 1 warning in 169.62s
```

The warning is the known pandas fragmentation warning in `bt_engine/strategies/sdr001/summary.py`; it is not a trading-logic failure.

## Next Required Action

The next safe step is to leave SDR-001 running on demo with the same gates until the first real SDR signal occurs.

Before that:

```text
confirm MT5 is demo/paper
confirm XAUUSD.ecn symbol spec and min lot
confirm no open orders
keep max_live_lot at 0.01
keep max_open_positions at 1
keep max_spread at 0.50
create /Users/subash/SUBASH/GoldDigger/LIVE_DISABLED to stop live order submission immediately
when a real SDR signal occurs, verify order command, broker response, open_orders mirror, journal rows, and close/cancel handling
```
