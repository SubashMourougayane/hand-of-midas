# Postmortem — GD-MI-cce2a254

**System**: Gold Micro
**Instrument**: XAU_USD
**Strategy**: micro_alpha_sweep
**Side**: SHORT 30 units
**Entry**: $4204.66  |  **SL**: $4204.36  |  **TP**: $4174.30
**Exit**: $4174.30  |  **Exit reason**: TP  |  **P&L (DB)**: $+910.80
**Duration**: 1:03:57.959077

## Risk Math

- _Risk math computed from ORIGINAL SL ($4223.90); current stored sl_price is $4204.36 after BE move._
- Risk: $19.24/unit × 30 = $577.20 max loss
- Reward: $30.36/unit × 30 = $910.80 max gain
- R:R: 1.58:1
- 50% to TP level (BE trigger): $4189.48

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-10 07:00:02 | 2026-06-10 12:30:02 | 2026-06-10 10:00:02 |
| BREAK_EVEN armed | 2026-06-10 07:44:00 | 2026-06-10 13:14:00 | 2026-06-10 10:44:00 |
| EXIT | 2026-06-10 08:04:00 | 2026-06-10 13:34:00 | 2026-06-10 11:04:00 |

## Excursions (M3 bars during trade window — local MT5)

- **MFE** (max favorable): $43.18/unit × 30 = $+1295.40
  - At server 2026.06.10 11:03:00 ($4161.48)
- **MAE** (max adverse): $3.38/unit × 30 = $+101.40
  - At server 2026.06.10 10:09:00 ($4208.04)

## BE trigger (50% to TP)

- 50% TP level **$4189.48** was crossed
- First crossing: server 2026.06.10 10:42:00 (UTC 2026-06-10 07:42:00, IST 2026-06-10 13:12:00)
- Bar high/low: $4193.48 / $4187.97
- BREAK_EVEN journal event fired 121s after crossing — ⚠️ 121s delay — slower than expected polling

## What happened AFTER exit?

- TP level $4174.30 was reached at server 2026.06.10 11:06:00 (UTC 2026-06-10 08:06:00)
  → That's 2.0 minutes after our exit

## Counterfactual P&L scenarios

_Note: original SL at entry was $4223.90; current stored sl_price is $4204.36 (probably moved by BE)._

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-19.24 | $-577.20 |
| If hit TP | $30.36 | $+910.80 |
| If exited at MFE bottom | $43.18 | $+1295.40 |
| **ACTUAL (DB)** | — | **$+910.80** |

## Bug-smell checklist (deterministic)

- ✅ No bug smells detected — DB ↔ price levels reconcile cleanly

## Pattern vs recent peers

Last 7 closed trades for Gold Micro:

| trade_ref | side | entry | exit | reason | P&L |
|---|---|---:|---:|---|---:|
| GD-MI-c5ad6dbd | LONG | $4260.27 | $4257.65 | SL | $-73.36 |
| GD-MI-61765355 | SHORT | $4450.19 | $4449.89 | SL | $+4.80 |
| GD-MI-ab99992e | SHORT | $4463.53 | $4472.19 | MAX_HOLD | $-121.24 |
| GD-MI-89b7373d | LONG | $4466.49 | $4454.87 | SL | $-197.54 |
| GD-MI-e34af01e | LONG | $4465.74 | $4457.13 | SL | $-232.47 |
| GD-MI-a089bbcf | LONG | $4487.86 | $4484.28 | SL | $-293.81 |
| GD-MI-4641b527 | SHORT | $4488.28 | $4494.66 | SL | $-299.86 |

Recent W/L: 1/6
Recent net P&L (excluding this trade): $-1213.48

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-10 07:00:02 | ENTRY_FILLED | 4204.6600 | sl=4223.9, tp=4174.3, units=30, oanda_id=2032606267, risk_pct=4.0, risk_mult=1.0 |
| 2026-06-10 07:44:00 | BREAK_EVEN | 4204.3600 | old_sl=4223.9, source=scheduler, trigger_price=4189.45 |
| 2026-06-10 08:04:00 | EXIT_FILLED | 4204.3600 | reason=SL, pnl_usd=9.000000000005457, oanda_id=2032606267 |
| 2026-06-10 08:42:44 | PNL_CORRECTED | 4174.3000 | see=docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md, wrong={'pnl_usd': 9.0, 'exit_price': 4204.36, 'exit_reason': 'SL'}, reason=phantom_fill_bug_be_ambiguity, correct={'pnl_usd': 910.8, 'exit_price': 4174.3, 'exit_reason': 'TP'}, delta_usd=901.8 |

---

_This file is the deterministic facts layer. The trade-postmortem skill appends judgment + analysis below this line._
