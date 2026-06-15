# Investigation — Bar-vs-Wallclock Drift in MAX_HOLD

**Status:** open · **Priority:** medium · **Started:** 2026-06-16

## Trigger

Live trade `GD-AL-88faa516` (Gold Macro SHORT, entered 2026-06-16 19:18 UTC) hit MAX_HOLD around 23:18 UTC. JustMarkets's XAUUSD nightly maintenance break overlapped, so `close_trade()` returned `Market closed`. The 1-minute scheduler kept retrying, each failure firing `notify.error(...)` to Telegram. User received the same alert every minute from 22:48 UTC onwards.

The immediate fix (notification muffling — see [`notify.max_hold_deferred`](../backend/notify.py)) is in flight. While analyzing it we surfaced a **second-order issue**: live and backtest don't agree on what "MAX_HOLD" means in time.

## The drift

### Backtest — counts bars

`backend/execution/fill_model.py:88`:

```python
for b in range(bar_start + 1, min(bar_start + max_bars, len(df))):
    bars_held += 1
    ...
# 207: max bars reached — exit at last bar's close
last_b = min(bar_start + max_bars - 1, len(df) - 1)
```

The backtest df contains only bars the broker actually emitted. Maintenance breaks and weekends are **invisible** — the index just jumps from the last pre-close bar to the first post-open bar. The simulator walks 80 contiguous **dataframe** bars and exits at bar #80's close.

### Live — counts wallclock

`backend/scanner/live_engine.py:328` (and identical pattern in the 3 sibling backends):

```python
bars_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 180  # M3 = 180s
if bars_held >= 80:
    ...force close
```

Live divides elapsed wallclock seconds by 180 (one M3 bar). It has **no concept of broker session boundaries** — a Friday-evening entry whose 80-bar window crosses the weekend will report `bars_held = 1500` Sunday afternoon, even though the broker emitted ~0 bars during that span.

### Where they diverge

| Entry timing | Backtest MAX_HOLD trigger | Live MAX_HOLD trigger | Drift |
|---|---|---|---|
| Mon 10:00 UTC, no break | bar #80 close (~14:00 UTC) | wallclock 14:00 UTC | 0 |
| Mon 22:00 UTC, hits 23:00-00:00 break | bar #80 close (skips break, ~03:00 UTC next day) | wallclock 02:00 UTC (during/before break) | ~1 hour, market closed |
| Fri 18:00 UTC | bar #80 close (Mon ~14:00 UTC) | wallclock 22:00 UTC Sun (during weekend close) | up to 60 hours, market closed |

The defer fix masks the *symptom* — live now silently retries until reopen instead of erroring — but the conceptual gap remains. **The trade closes at a different bar in live than in backtest** for any entry whose 80-bar window crosses a session boundary.

## Why the defer fix is still the right first step

1. The damage in production was a Telegram-spam loop, not a P&L loop. The defer fix kills the spam.
2. With defer in place, live now closes at "first bar after broker reopens" — which is **closer** to backtest semantics ("bar #80 after entry, ignoring closed-market gaps") than the pre-fix behavior was.
3. The remaining drift only fires when `bar_start + max_bars` would land inside a closed-market window. For weekday-midday entries (the bulk of trades), drift is zero.

The fix doesn't *formally* close the parity gap. It narrows it from "spammy and could exit at a bad maintenance-window price" to "silent and exits at first-bar-after-reopen — which is what backtest already does in df-space anyway."

## Open questions to measure

These are the things we don't know yet. They need data, not opinion.

1. **How often does this fire in production?** Of the trades closed via MAX_HOLD across all 4 systems, what fraction had their `bar_start + max_bars` land inside a broker-closed window?
2. **What's the P&L delta?** For trades that did cross a closed-market boundary, what would the close price have been at "exact wallclock 80×180s" vs "first bar after reopen"? Does the defer behavior bias toward gainers or losers?
3. **Backtest semantics under the same condition** — if we replay the same trade in backtest with bars that include the maintenance gap, what does it do? Does it skip the gap correctly, or does the bar walker over-count?
4. **Filter #5 / Filter #6 wallclock dependencies** — are BE-arming and trail-after-BE driven by bar count or wallclock? If wallclock, they have the same drift.
5. **Scan-window guards** — `08:00-19:00 UTC` cron in `scheduler.py:888` is wallclock. Backtest scans bar-by-bar without a wallclock filter. Are entry windows aligned, or is there a similar bar-vs-wallclock skew at the entry side?

## Audit checklist (do not ship without measuring first)

Following [[feedback-filter-measurement-gate]] — every behaviour change needs a 21-year backtest pre/post. Even "fix the parity drift" must clear the gate.

- [ ] Replay a known maintenance-break-crossing trade in both backtest + live's intended new behavior; compare exit price and P&L.
- [ ] Grep for `(datetime.now() - entry_time)` and `total_seconds()` patterns across all 4 backends — list every place live uses wallclock for a strategy decision.
- [ ] For each, ask: does backtest count bars or wallclock at the same decision point? Catalog the matching backtest line.
- [ ] If they disagree, propose a fix that aligns live to backtest (because backtest is the shipping-decision authority — see [[feedback-replay-vs-real-backtest]]).
- [ ] Run a real `run_backtest()` pre/post any wallclock→bar-count conversion. Compare PF, total P&L, # MAX_HOLD exits.
- [ ] Tally MAX_HOLD frequency in production over the last 30 days using the journal — establish the size of the population this affects.

## Candidate fix (sketch, not committed)

Replace the wallclock formula with a bar count that polls the broker for actual emitted bars since entry:

```python
# instead of:
bars_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 180

# do:
bars_held = count_bars_since(symbol, entry_time, timeframe="M3")
```

`count_bars_since` would query M3 bars from MT5 / OANDA bridge and count those after `entry_time`. This makes live's "bars held" structurally identical to backtest's `b - bar_start`.

**Caveat:** this is a non-trivial behavior change. Per the measurement gate, we don't ship it without a 21-year backtest comparison. It also adds a per-tick broker call, so latency/throughput needs measurement.

## Related fixes already in flight

- **MAX_HOLD market-closed defer (notification only)** — 6-file change muffling spam during maintenance breaks, 1-time defer ping per trade, paired-up `MAX_HOLD (deferred)` close confirmation. Awaits sign-off. **Does not address the parity gap.**

## Related memory + docs

- [[project-live-backtest-parity-gap]] — the architectural risk this is an instance of
- [[project-parity-harness]] — the harness that should have flagged this; doesn't currently
- [[feedback-filter-measurement-gate]] — every behavior change needs a 21yr backtest
- [[feedback-replay-vs-real-backtest]] — backtest is shipping authority; replay tools mislead
- `docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md` — prior parity-class bug in the same family (bar-walker disagreement between live and backtest)

## What this investigation needs

- Time to add a parity test for the maintenance-break case to `tests/harness/test_22_parity.py`
- A grep audit across all 4 backends for wallclock-driven strategy decisions
- A real backtest pre/post on any proposed code change
- User sign-off before any of the above lands ([[feedback-no-auto-ship]])

---

_Owner: Subash. Opened 2026-06-16 during the GD-AL-88faa516 MAX_HOLD spam incident. Defer-fix branch is the immediate Telegram-noise fix; this investigation is the deeper "are we computing the same thing in live vs backtest" question that the defer-fix surfaces but does not solve._
