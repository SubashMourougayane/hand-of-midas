# SDR-002 ORB Causality + Spread Audit

Generated: 2026-06-29

## Verdict

The `ema8_aligned + orb_reversal + entry_session in {asia_late, post_close}` candidate is broken by a causality bug.

The spread model is not the immediate problem. The current DWX demo feed shows XAUUSD spread around `$0.09-$0.10`, while the historical model charged `$0.30 / risk_units`, which is more conservative than the current live snapshot.

The problem is `orb_reversal`.

## Root Cause

`add_orb_context()` computes the New York 09:00-09:30 opening range, then writes that ORB state onto every bar of the same New York date.

That means bars from 00:00-07:59 New York time can see the future 09:00-09:30 opening range.

The SDR-002 candidate specifically selects:

```text
entry_session in {post_close, asia_late}
```

Those sessions are New York hours 00-07, before the NY ORB exists.

So the candidate was filtering Asia/post-close trades using future NY opening-range information.

## Evidence

Candidate:

```text
ema8_aligned == True
orb_reversal == True
entry_session in {asia_late, post_close}
```

Non-causal historical result:

```text
Trades: 1,362
Net: +760.44R
WR: 82.89%
PF: 3.93
Max DD: -5.20R
Positive months: 82/82
```

Causal same-day ORB availability check:

```text
ORB known before entry: 0 trades
ORB not yet known before entry: 1,362 trades
```

Therefore:

```text
Causal surviving trades: 0
Causal surviving net: 0R
```

## Parent Rule Damage

When ORB is only allowed after it is known:

```text
2-flag ema8 + orb_reversal
Before guard: 2,508 trades, +850.92R, WR 71.7%, PF 2.10, DD -12.60R
After guard:  1,085 trades,  +56.52R, WR 57.1%, PF 1.11, DD -40.96R
```

```text
3-flag ema8 + orb_reversal + avoid_after_hours
Before guard: 1,802 trades, +842.95R, WR 77.7%, PF 2.96, DD -7.71R
After guard:    379 trades,  +48.55R, WR 58.3%, PF 1.30, DD -13.83R
```

The apparent edge was mostly created by future ORB state.

## Spread Check

DWX current snapshot:

```text
Bid: 4049.33
Ask: 4049.42
Spread: $0.09
```

Last 5,000 M1 bars:

```text
Mean spread:   $0.0977
Median spread: $0.10
95th pct:      $0.10
99th pct:      $0.10
Max:           $0.10
```

By session, the last 5,000 M1 bars are also stable around `$0.10`.

This sample is short and from demo, so it is not enough for production, but it does not explain the unrealistic PF. The ORB causality bug does.

## Required Fix Before Any SDR-002 Promotion

1. `add_orb_context()` must not assign same-day ORB state to bars before the ORB window has closed.
2. For same-day NY ORB, `orb30_state` must be `missing` until at least 09:30 New York time.
3. If we want Asia/post-close to use an ORB, it must be explicitly defined as previous-day ORB, not silently same-day future ORB.
4. Rebuild the feature matrix after the guard.
5. Rerun the full sweep from scratch.

## Conclusion

Reject the SDR-002 Asia/post-close ORB candidate as currently measured.

Do not promote it.

The true next research branch is:

```text
Causal SDR-002 = rebuild ORB features with strict time availability, then rerun permutation search.
```

