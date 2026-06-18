# Postmortem — GD-AL-4af2d62d

> **Verdict:** <!-- skill: verdict -->🐛 Bug detected — BE never armed despite price reaching 60.8% to TP<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Gold Macro SHORT entered at $4348.67. Broker bars confirm price reached MFE $4331.09 (60.8% to TP) — past the 50% BE trigger ($4334.21) by $3.12. BE check (per-minute scheduler tick on `get_current_price()`) never fired, no `BREAK_EVEN` journal event. Trade then reversed; user force-closed manually on JM web at 16:11 UTC, exit $4361.96, **net −$160.32** (gross −$159.48 + commission −$0.84). DB backfilled. If BE had armed: ~+$3.60 scratch instead of −$160 loss → 99% of the loss is automation failure, not strategy failure. Filter #29 (bar-aware BE) candidate in flight.<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Macro
- **Instrument:** XAU_USD
- **Strategy:** alpha_sweep
- **Side:** SHORT 12 units
- **Entry:** $4348.67 · **SL:** $4366.07 · **TP:** $4319.75
- **Duration:** 1:33:33.404124

## Risk Math

- Risk: $17.40/unit × 12 = $208.80 max loss
- Reward: $28.92/unit × 12 = $347.04 max gain
- R:R: 1.66:1
- 50% to TP level (BE trigger): $4334.21

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-17 14:42:02 | 2026-06-17 20:12:02 | 2026-06-17 17:42:02 |
| EXIT | 2026-06-17 16:15:35 | 2026-06-17 21:45:35 | 2026-06-17 19:15:35 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$4334.21** was NEVER reached during trade

## What happened AFTER exit?

- TP level $4319.75 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-17.40 | $-208.80 |
| If hit TP | $28.92 | $+347.04 |
| **ACTUAL (DB)** | — | **$+0.00** |

## Bug-smell checklist (deterministic)

- ⚠️ Journal has EXIT_AMBIGUOUS events — heuristic fallback fired (DWX OnTradeTransaction may not have written closed_orders.json)

## Pattern vs recent peers

Last 10 closed trades for Gold Macro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-AL-2025e3d2 | SHORT | $4333.26 | $4335.18 | MAX_HOLD (deferred) | $-105.60 |
| GD-AL-d0b6bbee | SHORT | $4335.72 | $4321.66 | EXPERT | $+182.78 |
| GD-AL-88faa516 | SHORT | $4332.46 | $4311.47 | MAX_HOLD (deferred) | $+398.81 |
| GD-AL-cccf04c2 | SHORT | $4335.16 | $0.00 | MANUAL_CLOSE_DETECTED | $+0.00 |
| GD-AL-12932834 | SHORT | $4338.91 | $0.00 | MANUAL_CLOSE_DETECTED | $+0.00 |
| GD-AL-a6853136 | SHORT | $4337.29 | $0.00 | MANUAL_CLOSE_DETECTED | $+0.00 |
| GD-AL-12c63d16 | SHORT | $4342.02 | $4347.48 | STOP_LOSS_RECOVERED | $-160.37 |
| GD-AL-b23ccc45 | SHORT | $4338.74 | $4346.23 | STOP_LOSS_RECOVERED | $-234.36 |
| GD-AL-6da58d64 | SHORT | $4326.30 | $4342.46 | MAX_HOLD | $-404.00 |
| GD-AL-f0cd7edf | LONG | $4459.87 | $4470.06 | MAX_HOLD | $+295.51 |

Recent W/L: 3/7
Recent net P&L (excluding this trade): $-27.23

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-17 14:42:02 | ENTRY_FILLED | 4348.6700 | sl=4366.07, tp=4319.75, units=12, oanda_id=2059765552, risk_pct=4.0, risk_mult=1.0 |
| 2026-06-17 16:11:52 | EXIT_AMBIGUOUS | — | reason=no_open_no_closed_record, streak=1, oanda_id=2059765552 |
| 2026-06-17 16:12:52 | EXIT_AMBIGUOUS | — | reason=no_open_no_closed_record, streak=2, oanda_id=2059765552 |
| 2026-06-17 16:13:52 | EXIT_AMBIGUOUS | — | reason=no_open_no_closed_record, streak=3, oanda_id=2059765552 |
| 2026-06-17 16:14:52 | EXIT_AMBIGUOUS | — | reason=no_open_no_closed_record, streak=4, oanda_id=2059765552 |
| 2026-06-17 16:15:36 | EXIT_MANUAL_WEB | — | note=BE bug — needs JM-web backfill for exit_price + pnl, reason=user closed manually on JM web because BE never armed, mfe_observed=4331.09, be_50_trigger=4334.21 |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
Entry was a valid Gold Macro Alpha-Sweep SHORT: 14:42 UTC fired during the 08:00–19:00 UTC scan window (London/NY overlap). R:R 1.66 is within the 1.5–3 band the strategy targets. Entry price $4348.67, SL $4366.07 ($17.40 risk, ~0.40%), TP $4319.75 ($28.92 reward, ~0.66%) are all proportional. The strategy generated a valid signal — **execution layer broke down at the BE management stage, not the entry stage**. Bias-filter and sweep+engulfing alignment cannot be verified without the backtest signal trace; assumed valid since the live engine fired the signal.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
**🐛 Primary bug: BE check never armed despite price reaching $3.12 below trigger.** Live debug evidence:

- VPS bars file (`bars_XAUUSD_ecn_M3.json`): bar `2026.06.17 17:45:00` (server GMT+3 = 15:45 UTC, ~1h03 after entry) had **low=$4331.09 high=$4355.38**. Spread-adjusted ask_low ≈ $4331.19 (spread $0.10).
- BE 50% trigger (ask) = $4334.21. The 17:45 M3 bar's ask range covered the trigger by $3.02.
- Position monitor scheduler runs `position_monitor_job()` every 1 min (verified via APScheduler `get_jobs()` — `interval[0:01:00]` confirmed). It calls `check_alpha_sweep_breakeven()` at line 775 of `backend/scanner/scheduler.py`.
- `check_alpha_sweep_breakeven()` at `backend/scanner/live_engine.py:531-582` reads `get_current_price()` (live MT5 ask/bid) — NOT bar history. SHORT branch at line 568-578.
- **Hypothesis:** the dip below $4334.21 was sub-minute (a wick within the M3 bar that resolved before the next per-minute tick). `get_current_price()` returns the live MT5 last quote at the moment of the BE check — if the wick was a single-tick spike, the per-minute snapshot would miss it.
- **Cannot definitively confirm hypothesis without tick data** — bars file is M3 OHLC only, not tick-by-tick. The `gd_journal` has 0 `be_progress` debug events for this trade (debug-level may be filtered out before persistence). No `be_skip_already_armed`. No `be_modify_failed`.

**Secondary bug: 4× EXIT_AMBIGUOUS streak (16:11–16:14 UTC), broker had no position for ~4 minutes before user manually closed.** This is THE [[bug-dwx-ontradetransaction-dual-instance]] pattern — broker's manual close didn't fire OnTradeTransaction in our VPS MT5, so `closed_orders.json` was never written. `closed_orders.json` confirms: latest XAUUSD entry was ticket `2057074646` from 04:05:38 server, NOT our `2059765552`.

**Tertiary observation: trade was already closed on broker by 16:11 UTC** (orphan reconciler streak started). User stated "i closed the trade manually" at ~16:15 — but broker shows close was earlier than that. Possibility: user closed it on JM web sometime around 16:11, reconciler detected the orphan but waited 4 streak cycles before action. User then said "closed it" at 16:15 when DB still showed open. Force-update at 16:15:35 used `NOW()` for `exit_time` — actual close time was likely **16:11 UTC** ± small.

**Backfill needed from JM-web statement:**
- exit_price (broker fill at manual close)
- pnl_usd (gross close P&L; commission/swap separate)
- exit_time correction (NOW() in DB is later than real broker close)
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
The peer table reveals a **disturbing pattern**: of the last 10 Gold Macro trades, **3 are `MANUAL_CLOSE_DETECTED` ($0 P&L)** — meaning user already had to intervene 3 times in recent history. Those entries (cccf04c2, 12932834, a6853136 — all 2026-06-14) suggest a multi-event day where automation was failing AND user was force-closing manually. **This trade extends that pattern** — the same failure class (BE not arming, user has to step in) is recurring.

Net W/L = 3/7 over recent peers; recent net P&L is −$27 (with three $0 manual-closes that are effectively unknown gains/losses). The strategy isn't broken at the entry stage (peers show clean wins like d0b6bbee +$182 and 88faa516 +$398). **The breakdown is at the trade-management stage** — BE arming and SL/TP execution.

This trade is NOT an outlier per the peer table — it's the same failure mode happening again. If we count manual-close trades as failed-automation events, that's 4/10 broken executions in 2 weeks.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
**The counterfactual table understates the harm.** Both rows show `$0` actual because exit_price is NULL (backfill pending). True counterfactual:
- **What WOULD have happened if BE armed correctly:** SL moves to entry−$0.30 = $4348.37 at 15:45 UTC (when MFE breached). Trade then reverses to MFE high, hits BE-SL at $4348.37 → P&L = +$0.30/unit × 12 = **+$3.60** (essentially scratch, but **risk-free from 15:45 onward**)
- **What ACTUALLY happened:** BE never armed. Trade reversed against position. User force-closed at ~16:11 UTC with broker price ~$4362–$4365 (estimate). P&L likely **−$170 to −$200** (need JM web for exact)
- **Variance from BE-armed scenario: ~$175 worse** — the entire "broken automation" cost.

The strategy's offer was: **trail SL to BE at 50%, then either ride to TP for +$28.92/unit or scratch at +$0.30/unit if it reverses.** That's the protection mechanism. Without BE, the offer collapsed to: take +$28.92 if TP hit, else lose up to $17.40. That's a fundamentally different risk profile — and the strategy's edge math was computed under the BE-protected scenario.

**Implied edge interpretation:** Single-trade reads are weak. But the recurring-failure pattern (4/10 broken executions) means the live edge is materially below the backtested edge. Backtest assumes BE works on every trade; live shows BE skipped on a meaningful fraction. **Live P&L vs backtest gap is partly this bug, not just slippage.**

Was the SL too wide? No — $17.40 is normal for the strategy. The problem is BE didn't arm, so the full $17.40 stayed exposed long after it should have been retired.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
**Status: 🐛 BUG — concerning + recurring (4 broken executions in 2 weeks).**

1. **Backfill from JM web statement (TODAY, 5 min):** open JustMarkets web, find ticket `2059765552` close, copy exit_price + pnl_usd + actual_close_time. Update DB:
   ```sql
   UPDATE gd_trades SET exit_price = <X>, pnl_usd = <Y>, exit_time = <Z>
   WHERE trade_ref = 'GD-AL-4af2d62d';
   ```
2. **Investigate BE per-minute snapshot vs M3-low gap (HIGH priority, this week):** the working hypothesis is sub-minute price wicks bypass `position_monitor` (1-min interval × `get_current_price()` snapshot). Validate by:
   - Adding `BE_PROGRESS` debug events to `gd_journal` on every position_monitor tick (capture `current_ask` + `target_50` + `distance`). Today's bug-event has zero such events — that's blind. **File:** `backend/scanner/live_engine.py:548` (LONG `be_progress` log) and `:569` (SHORT). Switch from `_log.debug` to `_log_journal_safe(...)` for live observability.
   - Once a few trades have `BE_PROGRESS` rows, query: did any `min(current_ask) ≤ target_50` happen for trades where BE never armed? If yes → **BE check has a bug** beyond the snapshot hypothesis. If no → snapshot is the issue and we need bar-aware BE check (track lowest bid since entry).
3. **Fix candidate (FILTER #29? — needs BT validation, not mid-session):** **Bar-aware BE check.** Instead of relying solely on `get_current_price()`, also pull last completed M3 bar's bid_low. If that low ≤ target_50, arm BE retroactively. This catches sub-minute wicks. Per-strategy ship per [[feedback-selective-ship-pattern]].
4. **Track for future trades:** every Gold Macro / Gold Micro / Oil Macro / Oil Micro trade closing without BE armed when MFE breached the trigger — log as a new bug-class metric in daily recon. If rate stays > 10% post-fix, the snapshot hypothesis is wrong.
5. **Cross-reference:** the manual-close-detected pattern (3 prior trades on 2026-06-14) deserves its own bug investigation — was that the SAME root cause or a different orphan flow?
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
