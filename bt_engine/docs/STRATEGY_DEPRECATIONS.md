# Strategy Deprecations

As of 2026-06-30, `bt_engine` production strategy is `fib_v2_xau_ensemble`
(Fib V2 ENSEMBLE — long_bull_strong + short_bear_strong legs). It runs on
XAUUSD.ecn and EURUSD.ecn.

## Deprecated strategies

| name | status | reason |
|---|---|---|
| `sdr001` | DEPRECATED | Causality bugs in source data (ORB look-ahead). Kept only for parity replay against frozen sleeve1 ledger. |
| `sdr002_clean` | DEPRECATED | Clean variant of sdr001; never produced edge after fix. |
| `ema_cross` | DEPRECATED | Tutorial/smoke strategy, no edge. |

These strategies remain in the registry for backward-compat (existing tests
still call them). The CLI defaults for `bt` and `live` now point to
`fib_v2_xau_ensemble`. Strategy module docstrings carry a `[DEPRECATED
2026-06-30]` marker.

## Replacement

All new development targets `bt_engine/bt_engine/strategies/fib_v2/`. See
`bt_engine/docs/FIB_V2_TRACKER.md` and the plan file at
`/Users/subash/.claude/plans/ok-now-that-we-piped-fog.md`.
