# Economic-Signal Edge Hunt — Plan (next-session handoff)

**Status:** planned, not started. Pick up here next session.
**Prereq context:** `docs/EDGE_AUDIT_IRONCLAD.md` (the battery every candidate passes),
`[[real-edge-nopartial-costfilter]]` (our only surviving edge), and the graveyards
(`[[downloads-desktop-strategies-graveyard]]`, COBRAX/S1/silver-bullet).

## Why this pivot

The entire mechanical SMC/ICT space is dead on gold — 7 independent sources, 250+
parameter combos, **zero survivors**. Root cause: chart-pattern geometry has **no
economic reason to predict**; it's a coin flip and the fixed spread turns every coin
flip into a loser. Our one survivor (no-partial + cost-filter, PF 1.20, live=BT
proven) works because it's *structure + cost-discipline*, not a pattern.

**New direction:** hunt signals with a **real economic causal thesis** — the way a
macro/quant desk does. Gold's price is economically driven by **real interest rates**
(opportunity cost of a zero-yield asset), the **US dollar**, **speculative
positioning**, and **correlated-asset flow** (silver, yields, risk). These have a
reason to predict; chart shapes don't. Every candidate goes through the identical
iron-clad audit, and any survivor is ported to the live code path
(`bt_engine/scripts/run_live_path_bt.py`) for the live=BT gate.

## Non-negotiable quant rigor (the ways macro edges fake out)

1. **Point-in-time / publication lag.** COT for Tuesday positions is released Friday
   3:30pm ET — usable only Friday+. Yields/DXY use the *prior* close (T-1). Never use
   a revised or not-yet-published value. **The #1 way macro backtests lie.**
2. **Multiple-testing / data-mining discipline.** We test several signals; each must
   have its **economic thesis stated FIRST**, then survive OOS + bootstrap +
   per-regime + threshold-stability (monotonic, not a hand-picked spike — same test
   that validated our cost_r filter). In-sample-only or single-threshold = rejected.
3. **Cost + physical accounting** carried over from the over-count disaster.
4. **Gate 0 stays on:** a surprisingly-good macro result → suspect point-in-time
   leakage BEFORE celebrating.

## Phase 0 — Data acquisition

Reuse `research/data/oanda_fetch.py::fetch_range(symbol, gran, start, end)` (OANDA
token already in `.env`). Add small fetchers. Three routes:

| route | how | series | use |
|---|---|---|---|
| **OANDA** (have token) | `oanda_fetch.py` | `XAG_USD` (silver), `EUR_USD`/`USD_JPY` (dollar proxies), `SPX500_USD`, `NAS100_USD`, `XAU_USD`, 2019→2026, intraday+daily | lead-lag, SMT |
| **yfinance** (`pip install`) | new `research/macro/fetch_macro.py` | `^TNX` (10y), real-yield proxy (`TIP`), `DX-Y.NYB` (DXY), `GLD`, `SLV`, `GDX`, daily 20yr, free | macro fair-value |
| **CFTC** (curl, free) | new `research/cot/fetch_cot.py` | disaggregated gold-futures COT, weekly (managed-money + commercial net) | positioning |

**Point-in-time alignment module** `research/macro/align.py`: join every series to the
gold trade timeline using only values known-at-entry (apply each source's publication
lag). One tested utility, reused by all signals. Unit-assert no future value leaks.

## Signal classes (ranked by economic edge × data feasibility)

**S1 — Gold macro fair-value model (flagship).** Thesis: gold ≈ f(real 10y yield,
DXY); real yields down → gold up. Sub-signals: (a) **reversion** — rolling regression
gold~(realyield, dxy), trade the residual z-score back to fair value; (b) **yield
momentum** — real-yield N-day change predicts gold direction. Daily/swing. Strongest
rationale + cleanest data.

**S2 — COT positioning.** Thesis: managed-money net-long at a percentile extreme →
contrarian reversal; commercials accumulating → trend. Signal: MM-net z-score →
fade extremes, hold ~1-3 weeks. **Strict Friday-release lag.**

**S3 — Cross-asset intraday lead-lag.** Thesis: gold is the "slow" leg; a sharp DXY
(EUR_USD proxy) or silver move leads gold by minutes → tradeable intraday with an
economic driver (the honest version of the intraday edge, unlike the dead ORB).
Signal: leader moves >kσ in a short window → take gold the implied direction, ATR
SL/TP, intraday close.

**S4 — SMT divergence (economic form).** Thesis: gold & silver (both real-rate/precious
assets) should confirm; a divergent high/low = exhaustion → reversal. Extend
`research/smt/`.

**S5 — Options gamma — DEFERRED.** Needs point-in-time historical option chains /
dealer positioning (paid); yfinance gives only current chains. Revisit only with a
historical options feed. Do not fake it.

## Group B — OHLCV-only anomalies (NO external data — from `XAUUSD Quantitative Trading Edge.pdf`)

Distinct from Group A (S1–S5, which need macro/COT/cross-asset data). These four use
only the 21yr OHLCV we already have → **zero data acquisition, testable immediately →
run these FIRST in the breadth pass.** Alpha from temporal/liquidity frictions, not
chart shapes.

**B1 — Overnight drift vs intraday asymmetry (★ STANDOUT).** Documented anomaly: gold's
overnight return (NY close → next NY open) is structurally positive and captures most
long-run gains, while intraday US hours are choppy/mean-reverting. Signal: buy NY
close, sell next NY open (or a filtered version). **This is the one with a real
economic thesis (overnight risk-premium / gap accrual), not geometry — highest
priority, test to the dot.** No spread on a hold-through if modeled right; watch the
close→open gap cost + swap.

**B2 — East-West session volatility fracture.** Mark Asian-session H/L (01:00–08:00
GMT); momentum breakout when price cleanly breaks it during the London/NY overlap
(12:00–16:00 GMT) with a volume spike. *Caution:* breakout-family — ORB variants
already died (PF 0.31–0.84). But Asian-range + overlap-timing + volume-confirm is a
specific untested variant; test precisely, expect it to die, be ready to be surprised.

**B3 — Anchored-VWAP mean reversion.** Daily anchored VWAP + std-dev bands; fade when
price stretches 1–2% away on *declining* volume (exhaustion) → snap-back to VWAP.
Relates to the prior `[[vwap-mss-survivor]]`; pure band-fade is a different test.

**B4 — Volatility-normalized breakout (ATR + volume).** Breakout requiring volume
≥1.5–2× rolling avg (institutional participation) + ATR-based dynamic stops/targets
(1.5×ATR). *Caution:* breakout-family again; the volume+ATR filters are the twist —
same skepticism as B2.

**Honest read on Group B:** B1 (overnight drift) is the genuine economic anomaly and
the best shot in this group. B2/B4 are breakout re-skins (likely dead, but cheap to
confirm precisely). B3 is a reversion variant near a prior partial-survivor. All
OHLCV-only → test before the Group A data fetch.

## Execution — BREADTH-FIRST (decided)

1. **Group B first (OHLCV-only, no data fetch — fastest).** Rough base test of B1–B4,
   B1 (overnight drift) to the dot. Already have 21yr OHLCV → start immediately.
2. **Then Phase 0 data fetch** (yfinance macro, CFTC COT, OANDA cross-asset) →
   **rough pass on Group A** (S1–S4).
3. Rank ALL by net-of-cost per-year PF → **go DEEP + full battery + live=BT on the
   strongest lead(s) only.** A class showing nothing net-cost is a fast, valuable kill.

## Per-signal battery (identical to our edge)

Reuse `research/harness/causal_sim.py` (`simulate`/`headline`/`gate`) + the
`research/smc_campaign/s1_session_gauntlet.py` battery pattern:
Gate 0 hostile · Gate 2 physical R · Gate 3 causal known-at **with publication lag** ·
Gate 4 per-year + per-regime + stated kill condition · Gate 5 flat-risk R first then
`$` · bootstrap P(net≤0) · IS/OOS · delay robustness · cost stress $0.30–0.80 ·
threshold-stability (monotonic). **Survivor → live=BT** via a strategy variant through
`run_live_path_bt.py` (real sizer/bracket/$-booking) — the gate COBRAX failed.

## Files

- New: `research/macro/{fetch_macro.py, align.py, fair_value_signal.py, run_battery.py}`,
  `research/cot/{fetch_cot.py, cot_signal.py}`, `research/leadlag/{fetch_xasset.py,
  leadlag_signal.py}`; extend `research/smt/`. Results under `research/<class>/results/`.
- Reuse: `research/data/oanda_fetch.py`, `research/harness/causal_sim.py`,
  `research/smc_campaign/s1_session_gauntlet.py`, `bt_engine/scripts/run_live_path_bt.py`.
- Deps: `pip install yfinance`.

## Honest risks

- **Most of these will also die.** Real edges are rare — a real desk tests hundreds to
  keep a few. The bar (net-of-cost, OOS, live=BT) is high on purpose. Expect mostly
  negatives; each cheaply kills a hypothesis.
- **Data lag is the trap.** A "great" macro edge → suspect point-in-time leakage FIRST.
- **Gamma** likely un-testable without a paid feed → flagged, not faked.

## First actions next session

1. **Group B (no data needed):** `research/ohlcv_anomalies/` — build B1 overnight-drift
   (NY close→open) to the dot + B2/B3/B4 rough tests on the 21yr OHLCV. Battery the
   best. This is the fastest path to a possible survivor.
2. `pip install yfinance`; write `research/macro/fetch_macro.py` (DXY, ^TNX, TIP, GLD,
   SLV daily 20yr) + `research/cot/fetch_cot.py` (CFTC gold COT) + OANDA XAG_USD/EUR_USD
   intraday via `oanda_fetch.py`.
3. Build + unit-test `research/macro/align.py` (point-in-time, publication lags).
4. Rough base test of S1–S4; rank ALL (A+B) by net-of-cost per-year PF; deep-battery
   the winner + live=BT.

*(Also mirrored in `~/.claude/plans/golden-wondering-book.md`.)*

## Files (add)

- New: `research/ohlcv_anomalies/{overnight_drift.py, session_fracture.py,
  vwap_reversion.py, atr_vol_breakout.py, run_battery.py}` (Group B).
