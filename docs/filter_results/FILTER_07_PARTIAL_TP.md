# Filter #7 — Partial TP at 50%

**Generated:** 2026-06-13 (weekend session)
**Branch:** `filter-07-partial-tp`
**Engine source:** real `run_backtest()` 21-yr × 4 systems
**Status:** Pending user ship/stash decision

---

## Hypothesis

When price reaches 50% of the entry→TP distance, bank half the position
at the halfway price; let the other half ride to full TP / SL / BE / trail
under unchanged rules. Reduces variance, locks in profit on bars that retrace
before TP, common pro-trader practice.

## Implementation

**Fill model layer** (`backend/execution/fill_model.py`,
`backend-oil/execution/fill_model.py`, `backend-oil-micro/backtest/engine.py`):

Three new kwargs on `execute_trade` / `_execute_trade`:
- `partial_tp_at_pct` (0.0 = off, 0.5 = halfway)
- `partial_tp_size` (0.0 = off, 0.5 = bank half)
- `partial_arms_be` (Variant B: partial fire arms BE on the partial bar)

Same-bar order: gap-through SL → **partial fire** → full TP touch → SL touch.
Partial fires first if price reaches halfway; remainder still hits full TP same
bar if applicable. Reported `pnl_per_unit` = `partial_pnl × size + runner_pnl × (1−size)`,
so all downstream sizing/equity code stays identical.

Exit reasons extended: `tp_partial+tp`, `tp_partial+sl`, `tp_partial+expired`
(or `PARTIAL+TP` etc. on Oil Micro's separate engine).

**BT engines** (all 4 `run_backtest()`): added kwargs that read from per-system
config via `.get(key, default=0.0)` — selective ship pattern ready.

**Note:** Filter #7 is fill-side. Live signal-gen unchanged → no Live extraction
needed in this measurement run.

## Variants tested

| Variant | partial fires | BE timing |
|---|---|---|
| Baseline | no partial | original schedule (BE_pct from #5) |
| Variant A | partial @ 50%, size 50% | original BE schedule |
| Variant B | partial @ 50%, size 50% | BE arms immediately on partial fire |

## Results — 21-year backtest, all 4 systems

| System | Baseline | Variant A | Variant B |
|---|---|---|---|
| **Gold Macro** | N=2242, PF 2.56, $346k | PF 3.53, $427k (**+$81k, +23.5%**) ✅ | PF 3.53, $422k (+$76k, +21.9%) ✅ |
| **Gold Micro** | N=1911, PF 2.77, $252k | PF 4.40, $335k (**+$82k, +32.7%**) ✅ | PF 4.35, $329k (+$77k, +30.4%) ✅ |
| **Oil Macro** | N=1683, PF 2.96, $781k | PF 4.70, $826k (**+$45k, +5.8%**) ✅ | PF 4.68, $820k (+$39k, +5.0%) ✅ |
| **Oil Micro** | N=4601, PF 3.10, $2.13M | PF 5.76, $3.18M (**+$1.05M, +49.5%**) ✅ | PF 5.80, $3.18M (+$1.06M, +49.7%) ✅ |

**Aggregate Variant A: +$1,261,109 / 21yr (+36.0%, +$60.1k/yr).**
**Aggregate Variant B: +$1,247,762 / 21yr (+35.6%, +$59.4k/yr).**

## Interpretation

- **All 4 systems gain materially.** This is a rare across-the-board winner —
  Filters #5 and #6 each had at least one system that lost (Filter #5 hurt
  Gold Macro -$5k; Filter #6 only helped Oil Macro). Filter #7's geometry
  (bank closer level, runner free-rolls) is genuinely strategy-agnostic.

- **Variant A vs Variant B is essentially a tie.** Variant B (BE arms on
  partial) gives marginally lower P&L on every system except Oil Micro
  (where it's +$3.8k better). The partial bar usually triggers BE soon
  anyway under the original schedule, so forcing BE earlier costs a tiny
  amount of room for the runner. Going with Variant A is the cleaner default.

- **Profit factor improvements are large** (PF +0.97 to +2.66 across systems).
  This is consistent with the hypothesis — banking half at a closer level
  cuts loser sizes (when BE-stop catches the runner after partial banked)
  more than it cuts winner sizes (full TP still pays full second leg).

- **Trade counts are essentially identical** (signals don't change, only
  fill behavior). Tiny +6 to +56 deltas come from the runner sometimes
  surviving where the full-size single-leg got trail-stopped.

## Same-pattern questions

**Will partial-TP feasibility differ live vs backtest?**
Yes, slightly — live partial close fires at the broker via a second limit
order placed at entry. JustMarkets/MT5 supports partial closes via DWX EA.
Fill quality on the partial limit should be at-or-better than the BT model
(BT assumes exact fill at halfway price; live partial limit fills at halfway
or better). So live should be at least as good as BT, possibly modestly better.

**Why does Oil Macro gain less than the others?**
Oil Macro already has Filter #6 trail (HWM ratchets remainder SL up on
favorable moves), so the runner's downside on partial-then-stop-out is
already protected. Marginal gain from also banking the partial leg at 50%
is smaller. Still positive.

## Implementation files

**Fill models (3 files):**
- `backend/execution/fill_model.py` — kwargs + partial logic
- `backend-oil/execution/fill_model.py` — same (oil's separate copy)
- `backend-oil-micro/backtest/engine.py` `_execute_trade` — same logic

**BT engines (4 files):**
- `backend/backtest/engine.py` — config import + kwarg forward
- `backend-micro/backtest/engine.py` — kwarg forward
- `backend-oil/backtest/engine.py` — kwarg forward
- `backend-oil-micro/backtest/engine.py` — kwarg forward

**Harness (new):**
- `scripts/run_filter_07.py` — 12 backtests (3 variants × 4 systems), Telegram

## Config keys (when shipped)

Each `<backend>/config.py` ALPHA_SWEEP / MICRO_ALPHA_SWEEP gets:
```python
"partial_tp_at_pct": 0.5,
"partial_tp_size": 0.5,
"partial_arms_be": False,   # Variant A is the default
```

For systems excluded from ship, omit the keys entirely — the `.get()` fallback
gives 0.0/0.0/False = legacy single-leg behavior.

## Decision

**Recommendation:** SHIP Variant A on all 4 systems.

Rationale: every system gains materially in both PF and total P&L; aggregate
+$1.26M / 21yr; no system loses; Variant A is marginally better than B on
3 of 4 systems with the same direction on the 4th; geometry rationale is
clean (banking closer level locks profit, runner free-rolls). This is the
cleanest filter to ship of the seven we've evaluated.

**Awaiting user reply:** `ship 7 A all` / `ship 7 A <subset>` / `ship 7 B …` /
`stash 7` / `next`.

## Open follow-up (post-ship)

If shipped and live deploy proceeds, build:
1. DWX EA partial-close command (CLOSE_HALF action).
2. Live engine: place partial-close limit order at entry time alongside
   main entry. On partial fill confirmation, halve `units` in DB,
   set `partial_tp_taken=True` flag (need schema migration).
3. Position monitor: read `partial_tp_taken` to skip duplicate partial fires.

That's a separate work block (~3 hrs incl EA + DB migration) — only worth
doing if BT measurement holds (it does).
