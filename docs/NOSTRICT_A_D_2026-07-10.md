# No-Strict A+D — Implementation for Review (2026-07-10)

**Status:** implemented + proven in BT, **NOT deployed live.** Live cutover (VPS service
switch + restart) is gated on Subash's explicit go. Review this doc first.

---

## What & why

Drop the `strict-after` gate on the Fib V2 intraday A+D legs. `strict-after` blocked entry
evaluation **on** the setup-confirm bar (bar K); it was a research bit-for-bit parity choice
(`searchsorted side='right'`), **not** a causality requirement. Dropping it makes bar K a
valid entry-scan bar too. Result over 20yr XAU: **+6.1% net-R, +2,311 trades, still 21/21
positive years.**

**Decision (Subash):** deploy no-strict at **2.5% risk** (down from live 3%).
- Risk-curve context: no-strict beats baseline at every risk 0.5–2.5% and **peaks at 2.5%**
  ($2.16M vs baseline $1.76M on the earlier fractional study); it **craters at 3%** (near-ruin
  cliff — extra trades raise stream variance, lowering the growth-optimal risk fraction).
- Honest caveat on record: at each variant's own optimal, baseline@3% ($2.63M) still exceeds
  no-strict@2.5% ($2.16M). So this is a **matched-risk quality win**, not a guaranteed $ increase
  vs the current 3% line. Subash chose 2.5%+no-strict deliberately.

---

## Causality (no time travel, no look-ahead)

No-strict does **not** relax look-ahead:
- Setup is fully confirmed at bar K's **close**.
- The confirm bar merely becomes a valid entry-**scan** bar.
- The fill is still bar **K+1's open** (base `_finalize_entry` next-bar-open queue).
- known_at was audited earlier this session: **0 violations across all 1,745 confirm-bar
  entries** (setup_confirm_ts ≤ signal_bar_ts < fill_ts, fill exactly 1 bar after signal).
- Time-aware bar close preserved: `on_bar` receives a just-closed M15 bar; pivots via
  `PivotTracker` idx+lb; no resample / no interior peek.

---

## Implementation (additive, zero blast radius on the frozen baseline)

| File | Change |
|---|---|
| `strategies/fib_v2_intraday/config.py` | add `strict_after: bool = True` to `FibV2IntradayConfig`; `make_intraday_{a,d}_config(*, strict_after=True)` thread it |
| `strategies/fib_v2_intraday/strategy.py` | gate the strict block on `self._intraday_cfg.strict_after`; `FibV2IntradayA/D` accept `strict_after` kwarg |
| `strategies/fib_v2_intraday/combined.py` | `FibV2IntradayAPlusD` accepts + forwards `strict_after` |
| `strategies/registry.py` | register `fib_v2_intraday_{a,d,a_plus_d}_nostrict` (build `strict_after=False`) |

Default everywhere is `True` → existing behavior and all baseline tests unchanged. No-strict is
opt-in via the `_nostrict` registry names. **One code path**: BT and live both run the same
class + `run_engine`; only the flag differs.

---

## Proof (all via the real engine, `scripts/prove_nostrict_a_d.py`, 20yr XAU M15 = 485,374 bars)

| metric | BT strict (baseline) | BT no-strict | LIVE no-strict |
|---|---|---|---|
| trades | **27,965** | 30,276 | 30,276 |
| net-R | **7,655.21** | 8,122.98 | 8,122.98 |
| win% | 48.77 | 48.34 | 48.34 |
| PF | 1.4882 | 1.4745 | 1.4745 |
| pos years | 21/21 | 21/21 | 21/21 |

1. **Regression:** strict=True == certified baseline (27,965 / 7,655R) **bit-for-bit**. Flag
   plumbing did not disturb the default.
2. **No-strict delta:** +2,311 trades (+8.3%), **net-R +6.1%**, 21/21 positive.
3. **BT == LIVE 0-delta:** shared 30,276, only_BT=0, only_LIVE=0 → **PERFECT PARITY**.

---

## Deployment runbook (NOT executed — gated on Subash)

1. Commit + push these changes; `git fetch/pull` on the VPS.
2. Change the A+D live service command(s):
   - strategy name → `fib_v2_intraday_a_plus_d_nostrict` (or the `_a` / `_d` nostrict names if legs run separately)
   - `--risk-pct 0.03` → **`--risk-pct 0.025`**
3. Two-step restart (Stop → Start; not `Restart-Service -Force` — that left legs Stopped once).
4. Verify: sizer logs show `risk_pct=0.0250`; legs warm up (200-bar replay) before live bars;
   confirm no orphaned positions from the restart.

**Restart cost:** every leg restart blinds warmup + resets state → a few missed entries around
the cutover. Batch with any other pending deploy. Do the switch on a weekend / low-activity window.

---

## Not done / open

- Live cutover not performed (this is BT-proven only).
- The `+6.1% R` is gross-of-live-execution; real fills may differ (broker physics untested for
  the extra confirm-bar entries specifically).
- Independent hostile reviewer + formal un-freeze of `fib-v2-certified-frozen` still advisable
  before flipping real money.
