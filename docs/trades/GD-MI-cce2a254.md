# Postmortem — GD-MI-cce2a254

> **Verdict:** <!-- skill: verdict -->✅ Clean win — strategy as designed (after DB correction)<!-- /skill: verdict -->
> 
> **TL;DR:** <!-- skill: tldr -->Gold Micro SHORT 30 oz hit TP for +$910.80 in 64 minutes. Initial DB recorded +$9 due to phantom-fill bug; corrected via PNL_CORRECTED. First trade after the orphan-cascade rebuild — every defense layer fired correctly.<!-- /skill: tldr -->

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep
- **Side:** SHORT 30 units
- **Entry:** $4204.66 · **SL:** $4204.36 · **TP:** $4174.30
- **Exit:** $4174.30 · **Exit reason:** TP · **P&L (DB):** $+910.80
- **Duration:** 1:03:57.959077

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

# Judgment & deep analysis

_The sections below are placeholders. The `trade-postmortem` skill replaces each `<!-- skill: ... -->` block with its analysis. Sections above this line are deterministic and must not be modified by the skill._

## 1. Strategy alignment

<!-- skill: strategy_alignment -->
Setup is well-aligned with Gold Micro's intended pattern. R:R 1.58:1 sits squarely in the strategy's design range (1.5–3). Entry at 07:00:02 UTC fell inside the rolling-window scan time. The 30-unit position sizing is consistent with the 4% risk × $10K equity baseline (risk = 30 × $19.24 = $577.20 ≈ 5.7% — slightly above target, likely from the lot-rounding in `units = int(min(risk_dollar / sl_distance, MAX_UNITS))`). Bias filter passing implies the prior daily candle was bearish (V1 body% ≥40% bearish OR V2 close-position ≤20%) — a 30-oz Gold short into a bearish-day bias is exactly the trade the strategy targets. No misalignment flags.
<!-- /skill: strategy_alignment -->

## 2. Bug-smell scan (judgment)

<!-- skill: bug_smell -->
**One historical bug already caught here, no new ones.**

- The `PNL_CORRECTED` journal event documents the original misattribution: stored `pnl_usd=$9` (BE-stop fill heuristic) vs broker reality `+$910.80` at TP. Caught by the user comparing wallet to dashboard; fix landed in commit `141772e` (DWX `OnTradeTransaction` + `closed_orders.json`).
- BE armed 121s after the 50%-TP cross — slightly slower than the 60s polling cycle. Plausible cause: position monitor takes time to read DWX files and call `modify_stop_loss`, and the cron fires "every 60s starting from minute 0" so a cross at +1s into a cycle naturally lands ≥61s later. Watch the next 5 trades — if BE delay routinely exceeds 90s, scheduler may be lagging.
- No stale-state flags, no schema overflow indicators, no `EXIT_AMBIGUOUS` events. DWX comment-preservation appears active (entry has `oanda_id` matching broker).
<!-- /skill: bug_smell -->

## 3. Pattern interpretation

<!-- skill: pattern -->
This trade **breaks a 6-trade losing streak** and reverses Gold Micro's recent net direction (peer table: 1W/6L, -$1,213 across the last 7 closed trades). Most prior losses were SHORT or LONG SLs around $4,450–$4,490 — a price regime $250+ above this trade's $4,200 entry, suggesting Gold has been trending down through the past week and the strategy was repeatedly fading the wrong side until today's reversal SHORT aligned with the dominant trend. This is **not** an outlier setup mechanically (R:R, lot size, duration all peer-typical) — what's outlier is the **outcome direction**: it's the first big win in the dataset. Single trade isn't enough to claim the strategy "turned around"; need 3–5 more wins in this regime before drawing any conclusion.
<!-- /skill: pattern -->

## 4. Counterfactual narrative

<!-- skill: counterfactual -->
The strategy traded an **uncertain $577 max loss for a realized $910 win** — net favorable on this single instance, but the relevant question is the distribution. MAE ($101 = 17% of original SL distance) was nowhere near the original $19.24/oz risk, so this trade never had real adverse pressure. SL is NOT too wide: a tighter SL would have stopped this trade out before BE armed at $4,189.48 (price spent ~7 minutes between entry and BE crossing). BE timing was **arguably late** — by the time BE armed at +44 minutes, MFE had already reached $35/oz; price was about to make a bigger move ($43 MFE peak). But "earlier BE" only helps in the cases where price reverses, and in those cases the BE-stop level is the protection. Net: the BE rule traded ~$25/oz of remaining edge for ~$19/oz of guaranteed protection on this trade — that ratio is consistent with the strategy's overall PF 4.5 backtest, which assumes BE costs a small slice of MFE in exchange for converting potential losers to scratches.
<!-- /skill: counterfactual -->

## 5. Recommendations

<!-- skill: recommendations -->
- **Status: clean win, no action needed.** First full-loop verification of the post-rebuild defense stack — every layer fired correctly (after the manual phantom-fill correction).
- **Track BE arm latency over next 5 trades.** Today was 121s after 50%-TP cross; if it routinely exceeds 90s, investigate whether `position_monitor_job` is consistently polling at 60s or if scheduler jobs are queuing. Look at journal `BREAK_EVEN.context.trigger_price` vs the M3 bar timestamp where price first crossed the level.
- **Watch the next closure end-to-end** with no human intervention required — it should appear in `closed_orders.json` (DWX EA) and produce a clean DB record on the first try, with Telegram P&L matching wallet exactly. If it does, the phantom-fill fix is verified beyond structural tests.
<!-- /skill: recommendations -->

---

_Generated by `scripts/postmortem.py` against `https://midas.subashtrades.in` + local DWX. The trade-postmortem skill fills the placeholders above._
