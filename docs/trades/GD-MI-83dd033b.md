# Postmortem — GD-MI-83dd033b

> **Verdict:** <!-- skill: verdict -->_pending skill analysis_<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->_pending skill analysis_<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep
- **Side:** LONG 46 units
- **Entry:** $4318.64 · **SL:** $4318.94 · **TP:** $4356.75
- **Exit:** $4322.35 · **Exit reason:** MAX_HOLD · **P&L (DB):** $+170.66
- **Duration:** 4:00:58.930703

## Risk Math

- Risk: $0.30/unit × 46 = $13.80 max loss
- Reward: $38.11/unit × 46 = $1753.06 max gain
- R:R: 127.03:1
- 50% to TP level (BE trigger): $4337.69

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-16 00:57:01 | 2026-06-16 06:27:01 | 2026-06-16 03:57:01 |
| EXIT | 2026-06-16 04:58:00 | 2026-06-16 10:28:00 | 2026-06-16 07:58:00 |

## Excursions (M3 bars during trade window — local MT5)

- No M3 bar data available for the trade window (local MT5 may not be running, or window is outside the 500-bar buffer).

## BE trigger (50% to TP)

- 50% TP level **$4337.69** was NEVER reached during trade

## What happened AFTER exit?

- TP level $4356.75 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-0.30 | $-13.80 |
| If hit TP | $38.11 | $+1753.06 |
| **ACTUAL (DB)** | — | **$+170.66** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 10 closed trades for Gold Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-MI-a94ebe4a | LONG | $4142.40 | $4155.26 | MAX_HOLD | $+90.02 |
| GD-MI-457d1578 | LONG | $4188.20 | $4182.43 | SL | $-155.79 |
| GD-MI-ddf39e75 | LONG | $4206.89 | $0.00 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-dd9bb158 | LONG | $4241.56 | $0.00 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-f2a2f90b | LONG | $4300.32 | $0.00 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-a05fcfee | LONG | $4323.04 | $4323.04 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-1e53d69b | SHORT | $4348.09 | $4348.09 | LIMIT_TTL_EXPIRED | $+0.00 |
| GD-MI-2b152d33 | SHORT | $4337.93 | $4343.78 | SL | $-157.95 |
| GD-MI-32edb995 | SHORT | $4322.81 | $4315.13 | EXPERT | $+161.28 |
| GD-MI-5794d040 | LONG | $4318.68 | $4309.53 | SL | $-384.30 |

Recent W/L: 2/8
Recent net P&L (excluding this trade): $-446.74

## BT Parity Replay

- **Fired in BT?** ❌ NO
- **Drift reason:** No same-direction BT signal in window. Nearest BT trade: LONG at 2026-06-15T20:24:00+00:00 (+273min from live entry)

### Nearest BT signals in ±1 day

| BT date | dir | entry | exit | reason | P&L | Δmin |
|---|---|---:|---:|---|---:|---:|
| 2026-06-15T20:24:00+00:00 | LONG | $4332.02 | $4318.68 | `sl` | $-77.83 | +273 |
| 2026-06-16T07:15:00+00:00 | SHORT | $4325.50 | $4326.33 | `tp_partial+sl` | $+83.19 | -377 |
| 2026-06-15T11:09:00+00:00 | SHORT | $4325.87 | $4347.50 | `sl` | $-157.84 | +828 |
| 2026-06-16T16:12:00+00:00 | SHORT | $4343.73 | $4315.72 | `tp_partial+tp` | $+570.95 | -914 |
| 2026-06-15T09:27:00+00:00 | SHORT | $4305.12 | $4315.44 | `sl` | $-161.95 | +930 |


## Journal events (chronological)

- No journal events for this trade.

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
_pending skill analysis — was the entry signal what the strategy is supposed to do? Asia consolidation real or trending? Sweep + engulfing + bias all aligned? R:R reasonable for this strategy (typically 1.5–3)? Entry timing within intended scan window?_
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
_pending skill analysis — DB ↔ broker P&L (compare to wallet if user mentioned it), Telegram delivery, stale state across systems, schema overflow indicators, OnTradeTransaction firing. Flag anything the deterministic checklist couldn't see._
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
_pending skill analysis — interpret the recent-peers table above. Outlier or typical setup? Streak context? Cluster of failures? Net P&L direction? Don't restate the table — extract meaning._
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
_pending skill analysis — narrative on the counterfactual table above. What trade-off did the strategy make? Was BE timing optimal (too early / too late / right)? If MAE never threatened SL, is SL too wide? What's the implied edge interpretation?_
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
_pending skill analysis — 1–3 concrete next steps. Is this normal/concerning/bug? What to verify on broker side? What to fix in code (file + line)? What to track for future trades?_
<!-- /skill: recommendations -->

## 6. BT Parity Replay judgment

<!-- skill: bt_replay_judgment -->
_pending skill analysis — interpret the BT Parity Replay table above. Did BT fire the same signal? If yes: did exit_reason and direction match live? Why does PnL differ (capital schedule, slippage, broker costs)? If no: is this drift acceptable (cron lag, F27 fill timing) or a bug (signal-gen divergence, gate mismatch)? Cite specific numbers from the replay block._
<!-- /skill: bt_replay_judgment -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
