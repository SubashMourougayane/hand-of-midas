# Friday Day Postmortem — 2026-06-12

_Generated: 2026-06-13T06:56:56.566317+00:00_

Coverage: 2026-06-12 from observability v2 deployment (~14:30 UTC) until midnight UTC. All 4 services.

## Per-service summary

| Service | Lines | Errors | Sigs fired | Executed | Skipped | Sweeps | Exits | Top gate reject |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **gold** | 3,802 | 0 | 0 | 0 | 0 | 196 | 0 | bias_block (196) |
| **oil** | 3,744 | 0 | 0 | 0 | 0 | 173 | 2 | bias_block (173) |
| **micro** | 6,126 | 0 | 3 | 2 | 0 | 992 | 2 | bias_block (589) |
| **oil-micro** | 5,767 | 1 | 1 | 1 | 0 | 573 | 2 | sweep_already_traded (378) |

## Linked trade postmortems (3 closes Friday)

- [GD-MI-da28460d](trades/GD-MI-da28460d.md) — Gold Micro LONG SL **−$369.74** (13:36-13:43 UTC)
- [GD-MI-0b973d80](trades/GD-MI-0b973d80.md) — Gold Micro LONG SL **−$358.83** (14:18-14:23 UTC)
- [OIL-MI-aba3b668](trades/OIL-MI-aba3b668.md) — Oil Micro SHORT MAX_HOLD **+$458.80** (14:54-18:55 UTC)

**Net Friday P&L: −$269.77** (3 trades, 1 win)

## gold detailed breakdown

### Category distribution
- POSITION: 2723
- SCAN: 863
- GATE: 196
- SYSTEM: 19
- BROKER: 1

### Level distribution
- DEBUG: 3467
- INFO: 334
- WARN: 1

### Top (category, message) pairs
- `POSITION/tick`: 907
- `POSITION/be_check_tick`: 907
- `POSITION/reconcile_tick`: 907
- `SCAN/tick`: 221
- `SCAN/asia_range`: 221
- `SCAN/sweep_detected`: 196
- `GATE/bias_block`: 196
- `SCAN/no_sweeps`: 131
- `SCAN/complete`: 90
- `SYSTEM/heartbeat_tick`: 11
- `SYSTEM/service_starting`: 4
- `SYSTEM/service_started`: 4
- `SCAN/daily_close_job_start`: 1
- `POSITION/mean_rev_exit_check_tick`: 1
- `POSITION/max_hold_check_tick`: 1
- `SCAN/cross_market_start`: 1
- `SCAN/mean_rev_start`: 1
- `BROKER/mean_rev_daily_too_few`: 1
- `SCAN/daily_close_job_complete`: 1

### Gate rejection histogram
- `bias_block`: 196

### Broker activity
- `mean_rev_daily_too_few`: 1

### Activity by hour (UTC)
- 08:00      41  
- 09:00     241  ████
- 10:00     237  ████
- 11:00     237  ████
- 12:00     241  ████
- 13:00     241  ████
- 14:00     240  ████
- 15:00     261  █████
- 16:00     309  ██████
- 17:00     321  ██████
- 18:00     345  ██████
- 19:00     361  ███████
- 20:00     180  ███
- 21:00     180  ███
- 22:00     187  ███
- 23:00     180  ███

---

## oil detailed breakdown

### Category distribution
- POSITION: 2724
- SCAN: 836
- GATE: 173
- SYSTEM: 9
- EXIT: 2

### Level distribution
- DEBUG: 3341
- INFO: 402
- WARN: 1

### Top (category, message) pairs
- `POSITION/tick`: 908
- `POSITION/be_check_tick`: 908
- `POSITION/reconcile_tick`: 908
- `SCAN/tick`: 221
- `SCAN/asia_range`: 221
- `SCAN/sweep_detected`: 173
- `GATE/bias_block`: 173
- `SCAN/complete`: 171
- `SCAN/no_sweeps`: 50
- `SYSTEM/service_starting`: 4
- `SYSTEM/service_started`: 4
- `EXIT/ambiguous`: 1
- `SYSTEM/dd_state_update`: 1
- `EXIT/detected`: 1

### Gate rejection histogram
- `bias_block`: 173

### Exit events
- `2026-06-12T16:08:00.188Z` `ambiguous`  trade_ref=OIL-MI-aba3b668 oanda_id=2045748663 reason=no_open_no_closed_record streak=1
- `2026-06-12T18:56:00.476Z` `detected`  trade_ref=OIL-MI-aba3b668 reason=EXPERT fill=86.28 pnl_usd=458.8 oanda_id=2045748663

### Activity by hour (UTC)
- 08:00      41  
- 09:00     240  ████
- 10:00     248  ████
- 11:00     246  ████
- 12:00     280  █████
- 13:00     280  █████
- 14:00     282  █████
- 15:00     280  █████
- 16:00     281  █████
- 17:00     284  █████
- 18:00     282  █████
- 19:00     280  █████
- 20:00     180  ███
- 21:00     180  ███
- 22:00     180  ███
- 23:00     180  ███

---

## micro detailed breakdown

### Category distribution
- POSITION: 2751
- SCAN: 2369
- GATE: 984
- SYSTEM: 10
- SIGNAL: 6
- BROKER: 4
- EXIT: 2

### Level distribution
- DEBUG: 5549
- INFO: 573
- WARN: 4

### Top (category, message) pairs
- `SCAN/sweep_detected`: 992
- `POSITION/tick`: 909
- `POSITION/be_check_tick`: 909
- `POSITION/reconcile_tick`: 909
- `SCAN/consol_range`: 805
- `GATE/bias_block`: 589
- `GATE/sweep_already_traded`: 383
- `SCAN/tick`: 277
- `SCAN/complete`: 275
- `SCAN/no_active_windows`: 20
- `POSITION/state`: 12
- `POSITION/be_progress`: 12
- `GATE/engulfing_window_too_few_m3`: 5
- `SYSTEM/service_starting`: 4
- `SYSTEM/service_started`: 4
- `SIGNAL/fired`: 3
- `GATE/daily_max_loss_hit`: 3
- `BROKER/order_placing`: 2
- `BROKER/order_filled`: 2
- `SIGNAL/executed`: 2

### Gate rejection histogram
- `bias_block`: 589
- `sweep_already_traded`: 383
- `engulfing_window_too_few_m3`: 5
- `daily_max_loss_hit`: 3
- `cooldown_active`: 2
- `open_position_db`: 2

### Broker activity
- `order_placing`: 2
- `order_filled`: 2

### Exit events
- `2026-06-12T13:44:00.482Z` `detected`  trade_ref=GD-MI-da28460d reason=SL fill=4184.63 pnl_usd=-369.74 oanda_id=2045156688
- `2026-06-12T14:24:00.880Z` `detected`  trade_ref=GD-MI-0b973d80 reason=SL fill=4182.84 pnl_usd=-358.83 oanda_id=2045484593

### Activity by hour (UTC)
- 08:00      50  █
- 09:00     280  █████
- 10:00     276  █████
- 11:00     286  █████
- 12:00     298  █████
- 13:00     362  ███████
- 14:00     348  ██████
- 15:00     458  █████████
- 16:00     576  ███████████
- 17:00     600  ████████████
- 18:00     606  ████████████
- 19:00     600  ████████████
- 20:00     486  █████████
- 21:00     200  ████
- 22:00     360  ███████
- 23:00     340  ██████

### Signal fires (samples, max 10)
- `2026-06-12T13:36:00.988Z` direction=long entry=4203.7127 sl=4184.63 tp=4226.1 risk=19.0827 sweep_wick=4186.63 sweep_dir=bullish bias=bullish range_high=4228.1 range_low=4191.99
- `2026-06-12T14:18:01.034Z` direction=long entry=4195.9049 sl=4182.84 tp=4226.1 risk=13.0649 sweep_wick=4184.84 sweep_dir=bullish bias=bullish range_high=4228.1 range_low=4191.99
- `2026-06-12T14:54:00.071Z` direction=long entry=4195.9949 sl=4175.1 tp=4226.1 risk=20.8949 sweep_wick=4177.1 sweep_dir=bullish bias=bullish range_high=4228.1 range_low=4191.99

---

## oil-micro detailed breakdown

### Category distribution
- POSITION: 3199
- SCAN: 1973
- GATE: 573
- SYSTEM: 9
- BROKER: 9
- SIGNAL: 2
- EXIT: 2

### Level distribution
- DEBUG: 5182
- INFO: 578
- WARN: 6
- ERROR: 1

### Top (category, message) pairs
- `POSITION/tick`: 909
- `POSITION/be_check_tick`: 909
- `POSITION/reconcile_tick`: 909
- `SCAN/consol_range`: 819
- `SCAN/sweep_detected`: 573
- `GATE/sweep_already_traded`: 378
- `SCAN/tick`: 281
- `SCAN/complete`: 280
- `POSITION/state`: 235
- `POSITION/be_skip_already_armed_or_invalid`: 207
- `GATE/open_position_db`: 117
- `GATE/bias_block`: 67
- `POSITION/be_progress`: 28
- `SCAN/no_active_windows`: 20
- `GATE/engulfing_window_too_few_m3`: 7
- `BROKER/be_check_no_price`: 6
- `SYSTEM/service_starting`: 4
- `SYSTEM/service_started`: 4
- `GATE/open_position_mt5`: 3
- `SIGNAL/fired`: 1

### Gate rejection histogram
- `sweep_already_traded`: 378
- `open_position_db`: 117
- `bias_block`: 67
- `engulfing_window_too_few_m3`: 7
- `open_position_mt5`: 3
- `cooldown_active`: 1

### Broker activity
- `be_check_no_price`: 6
- `order_placing`: 1
- `order_filled`: 1
- `max_hold_close_failed`: 1

### Exit events
- `2026-06-12T18:55:00.209Z` `max_hold_force_close`  ref=OIL-MI-aba3b668 bars_held=80 max_bars=80 oanda_id=2045748663
- `2026-06-12T18:56:00.539Z` `detected`  trade_ref=OIL-MI-aba3b668 reason=EXPERT fill=86.28 pnl_usd=458.8 oanda_id=2045748663

### ⚠️ Errors
- `2026-06-12T18:55:00.465Z` `BROKER/max_hold_close_failed`  ref=OIL-MI-aba3b668 oanda_id=2045748663 err=

### Activity by hour (UTC)
- 08:00      50  █
- 09:00     358  ███████
- 10:00     290  █████
- 11:00     324  ██████
- 12:00     322  ██████
- 13:00     400  ████████
- 14:00     335  ██████
- 15:00     520  ██████████
- 16:00     519  ██████████
- 17:00     519  ██████████
- 18:00     512  ██████████
- 19:00     360  ███████
- 20:00     398  ███████
- 21:00     200  ████
- 22:00     360  ███████
- 23:00     300  ██████

### Signal fires (samples, max 10)
- `2026-06-12T14:54:00.772Z` direction=short entry=88.2939 sl=89.21 tp=85.24 risk=0.9161 sweep_wick=89.01 sweep_dir=bearish bias=bearish range_high=88.03 range_low=85.11

---
