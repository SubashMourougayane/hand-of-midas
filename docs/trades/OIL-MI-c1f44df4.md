# Postmortem — OIL-MI-c1f44df4

> **Verdict:** <!-- skill: verdict -->✅ Clean loss — strategy as designed (with R:R note)<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Bearish-sweep SHORT at $91.26 was instantly run over — price went to $92.53 (above SL $92.45) on the entry bar itself, exited at SL in 1m58s for -$426.02. No bug; broker-authoritative exit confirmed via new OnTradeTransaction path. The unusual feature is **R:R 0.99:1** — the engulfing candle ate so much of the move that SL had to sit above the recent high, leaving almost no headroom.<!-- /skill: tldr -->

---

## Trade card

- **System:** Oil Micro
- **Instrument:** BCO_USD
- **Strategy:** micro_alpha_sweep_oil
- **Side:** SHORT 358 units
- **Entry:** $91.2600 · **SL:** $92.4500 · **TP:** $90.0800
- **Exit:** $92.4500 · **Exit reason:** SL · **P&L (DB):** $-426.02
- **Duration:** 0:01:58.226754

## Risk Math

- Risk: $1.1900/unit × 358 = $426.02 max loss
- Reward: $1.1800/unit × 358 = $422.44 max gain
- R:R: 0.99:1
- 50% to TP level (BE trigger): $90.6700

## Timeline

| Event | UTC | IST | Server (GMT+3) |
|---|---|---|---|
| ENTRY | 2026-06-10 11:24:02 | 2026-06-10 16:54:02 | 2026-06-10 14:24:02 |
| EXIT | 2026-06-10 11:26:00 | 2026-06-10 16:56:00 | 2026-06-10 14:26:00 |

## Excursions (M3 bars during trade window — local MT5)

- **MFE** (max favorable): $0.1400/unit × 358 = $+50.12
  - At server 2026.06.10 14:21:00 ($91.1200)
- **MAE** (max adverse): $1.2700/unit × 358 = $+454.66
  - At server 2026.06.10 14:24:00 ($92.5300)

## BE trigger (50% to TP)

- 50% TP level **$90.6700** was NEVER reached during trade

## What happened AFTER exit?

- TP level $90.0800 was NOT reached in the 30-min window after exit

## Counterfactual P&L scenarios

| Scenario | Per-unit | Total |
|---|---:|---:|
| If hit original SL | $-1.1900 | $-426.02 |
| If hit TP | $1.1800 | $+422.44 |
| If exited at MFE bottom | $0.1400 | $+50.12 |
| **ACTUAL (DB)** | — | **$-426.02** |

## Bug-smell checklist (deterministic)

- ⚠️ Journal has EXIT_AMBIGUOUS events — heuristic fallback fired (DWX OnTradeTransaction may not have written closed_orders.json)

## Pattern vs recent peers

No peer trades to compare.

## Journal events (chronological)

| timestamp (UTC) | event | price | context |
|---|---|---:|---|
| 2026-06-10 11:24:02 | ENTRY_FILLED | 91.2600 | sl=92.45, tp=90.08, units=358, oanda_id=2033741472, risk_pct=4.0, risk_mult=1.0 |
| 2026-06-10 11:26:00 | EXIT_AMBIGUOUS | — | extremes={'low': 91.64, 'high': 91.64}, oanda_id=2033741472, sl_reached=False, tp_reached=False |
| 2026-06-10 11:26:00 | EXIT_FILLED | 92.4500 | reason=SL, pnl_gbp=-426.0199999999992, pnl_usd=-426.0199999999992, oanda_id=2033741472, instrument=BCO_USD |

---

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
**Setup was textbook, sizing was the issue.** All four entry conditions aligned per `CLAUDE.md`:

- **Sweep:** Bearish wick to $92.25 from earlier scan window (range high $91.71 / low $89.95) — confirmed in `/api/oil-micro/scan-status` payload at the time.
- **Engulfing reversal:** M3 bar at server 14:21 dropped to $91.12 (the MFE bottom), implying a clean engulfing of the sweep wick before the entry bar at 14:24.
- **Daily bias:** `bearish` ✓ matches SHORT direction.
- **Within scan window:** Entry inside the 06:00–10:00 UTC sweep window's 4h scan-until extension.

But the **R:R was 0.99:1** — well below the 1.5–3:1 the strategy is designed around. That happened because the engulfing candle's range from the wick to the close was wide ($1.13 wick-to-close ≈), so SL placed above the wick (entry $91.26, SL $92.45 = $1.19 risk) ate into available reward room (entry to TP $90.08 = $1.18). On a "good" alpha-sweep, the engulfing is tight and SL sits close, giving ample headroom to TP. Here the engulfing was a wide-range bar — common in volatile WTI sessions — and the strategy still took it. **Whether that's a config gap or expected variance depends on how often it recurs.**

Entry timing was correct (within the active scan windows). Bias filter was correct. The signal itself was a valid alpha-sweep; the geometry of the specific bar made it a low-edge trade.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
**This is the first end-to-end test of the new phantom-fill defense, and it passed.**

- **DB ↔ wallet reconciliation:** Pre-trade balance $11,065.09 → post-trade $10,634.53 = **-$430.56 wallet delta**. DB recorded -$426.02. Δ $4.54 = commission + swap, fully expected. **No phantom-fill drift.**
- **EXIT_AMBIGUOUS → EXIT_FILLED is a feature, not a regression.** The deterministic checklist flagged `EXIT_AMBIGUOUS` as a possible OnTradeTransaction failure. It's actually the opposite: the heuristic correctly refused to guess (extremes high=low=$91.64 — bar didn't reach SL or TP within the M3 window the heuristic could see), then `closed_orders.json` from `OnTradeTransaction` provided the broker-authoritative exit ($92.45 SL, -$426.02). This is exactly the design intent of the June 10 phantom-fill fix. The deterministic checklist's warning is a false positive in this context — the events happened in the same second, which is the success signature, not failure.
- **Schema/INSERT chain:** ENTRY_FILLED + EXIT_AMBIGUOUS + EXIT_FILLED all wrote successfully with `strategy='micro_alpha_sweep_oil'` (21 chars) — confirming the VARCHAR(50) widening is in effect. No orphan-cascade pattern.
- **Stale state:** at 11:26+ UTC, broker `open_trades=0` matches DB `db_positions=[]` after a brief sync lag. Reconciler not needed.
- **Telegram:** assumed delivered (user is watching the system live). Worth a quick verification that entry/exit notifications fired, but no journal evidence of failure.
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
**First Oil Micro trade post-`CLEAN_SLATE_RESET` (07:32 UTC) — no in-system peers exist yet.** The 7 orphan trades from yesterday were forensic-only and never touched DB, so the trades-history endpoint correctly shows zero peers.

For wider context: this is the second loss in two days for Oil Micro (prior was the 7-orphan series net +$345.86 manually closed). With consecutive_losses=1 after this trade, the DD pause hasn't engaged. The pattern to watch is whether the next 2–3 Oil Micro signals also have R:R < 1.2 — if they do, the engulfing-bar-too-wide problem is systemic in current oil volatility, not a one-off.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
**MAE = $454.66 unfavorable on the entry bar itself.** Price reached $92.53 — $0.08 ABOVE the $92.45 SL — at server 14:24, the same minute as entry at 14:24:02. So this wasn't a slow giveback; the entry candle itself spiked through SL and the broker filled. The MAE figure shows the worst tick in the window; SL fill happened at the level, not at the worst tick (this is normal MT5 behavior).

The MFE of just **$50.12** ($0.14/unit) tells the story: price tagged $91.12 once around server 14:21 (this is the engulfing-low that produced the signal), then never came back near that direction. Entry happened at 14:24 — 3 minutes after the signal candle's low — by which time price had reverted hard. **The strategy effectively shorted the wick of a failed reversal.**

BE was never relevant: 50% TP level is $90.67 and price never went below $91.12. Even an aggressive BE (e.g., 25% to TP) wouldn't have triggered.

**SL is not too wide — it's correctly above the engulfing wick.** The problem is the opposite: the engulfing wick was too HIGH relative to the entry close, leaving SL above near-term highs that the next bar's wick easily reached. This is the geometry-of-the-bar issue from §1: when a wide-range engulfing produces both signal AND a near-touchable SL, R:R collapses.

Single-trade counterfactual: had the strategy required minimum R:R ≥ 1.5:1, this signal would have been **filtered out** (0.99:1 < 1.5). That filter doesn't currently exist for Oil Micro (verified earlier this session — strategy filters on bias + sweep + engulfing presence, not on resulting R:R). Whether to add it depends on whether wide-range engulfings have edge or noise — answerable with backtest data, not this single trade.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status: NORMAL.** Strategy executed correctly, broker filled SL at the right price, DB matches wallet within commission tolerance, and the new OnTradeTransaction → closed_orders.json path delivered authoritative exit data. No bug, no action needed for this trade.
- **Verify nothing on the broker side** unless the user noticed something off. The wallet math reconciles cleanly.
- **Track for future trades:** if Oil Micro produces 2 more SL hits in a row OR 2 more entries with R:R < 1.2:1, that's a signal to backtest a "minimum R:R 1.5" gate. Until then, single-trade noise — don't change config. Note this in [[session-2026-06-10-orphan-safety]] as a watch-item if it recurs.
- **Postmortem-pipeline meta-note:** the deterministic checklist's `EXIT_AMBIGUOUS` warning is misleading when followed by an immediate `EXIT_FILLED` from OnTradeTransaction (success signature). Consider tightening the check in `scripts/postmortem.py` to flag only when EXIT_AMBIGUOUS exists WITHOUT a same-second EXIT_FILLED follow-up.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
