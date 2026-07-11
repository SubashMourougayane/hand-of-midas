# The Iron-Clad Edge Audit

**Every backtest, every "edge," every P&L number, every strategy change passes this
BEFORE it is believed, quoted, certified, deployed, or put in front of anyone.**

Written 2026-07-12 after the partial-TP over-count wiped a "20-year, PF 1.49,
$534k, 21/21" certified track record down to its real value: a thin, regime-gated
edge that only turned profitable in the last ~2 years. The certified numbers were
inflated ~2× for months and passed every prior audit — because those audits checked
the code against *itself*, never against reality.

**The one law this document exists to enforce:**
> **Internal consistency is not correctness. A number is only real when it matches
> an INDEPENDENT ground truth — the actual broker's realized cash.**

Parity, 0-delta, "15-point pass," reproducing the cert — all can be green while the
number is a fantasy, if the same wrong assumption lives on both sides. Never again.

---

## GATE 0 — The Big-Number Trip-Wire (runs first, always)

Any result that is **surprisingly good** — high PF, big $, smooth equity curve,
high win rate, "beats baseline," passes cross-asset — is **presumed wrong until
proven otherwise.** Good news triggers MORE scrutiny, not celebration.

- [ ] Did this number make me want to celebrate? → Then hostile-audit it before saying it out loud.
- [ ] Quote the **median**, not the mean. Quote the **worst** window, not the average.
- [ ] State the number **with its kill condition**: "X, and here is exactly what would make X false."

*Why: the whole arc celebrated cross-asset confirmation and "cert PASS" instead of
auditing first. Silver Bullet, COBRAX, and the partial-TP cert all died to this.*

---

## GATE 1 — Ground Truth Beats Every Simulation

- [ ] **Reconcile to the broker, per trade.** Every closed trade's engine `$` must
      equal the broker's realized `$` (deal history / `broker_net_usd`) within cents.
      A mismatch is a BUG, not "slippage," until proven.
- [ ] **The broker balance is the only P&L that cannot lie.** If a sim disagrees
      with the real account, the SIM is wrong.
- [ ] Parity (BT==live 0-delta) proves the two code paths MATCH. It does **not**
      prove either is CORRECT. Never present parity as correctness.
- [ ] Every `$` projection names its independent check: "validated against N real
      broker deals" — or it is labeled *unvalidated*.

*Why: BT=live 0-delta passed for months because both sides booked the same
over-count. Only comparing engine-`$` to actual broker deals exposed it.*

---

## GATE 2 — Physical Accounting (no phantom money)

Any position that is **scaled, partially closed, or fractional** must be booked
by what the broker actually fills — never additively.

- [ ] **Fractional exits are physical:** `total = Σ(fraction_i × exit_R_i)`. A 50%
      partial at +1R plus a 50% runner to +2.6R is `0.5·1 + 0.5·2.6 = 1.8R` —
      **NOT** `2.6 + 0.5 = 3.1R`.
- [ ] **`$` uses the LIVE remaining lot**, not the original lot, at every point.
      If `qty` is reduced at the broker, it must be reduced in the `$` math.
- [ ] **Invariant test (mandatory):** losers unchanged (a full-stop is −1R,
      period); breakeven-after-partial = the banked partial only; a winner cannot
      book more R than `fraction · target + partial`.
- [ ] **A "fix" is itself audited.** When you correct an accounting bug, re-derive
      from first principles AND check the invariants. (The first "physical
      recompute" was *also* wrong — it scaled losers by 0.5 and inflated the result.)

*Why: `outcome_r = tp_r + partial` (full runner + partial) booked ~2× on every
winner; `$ = full_qty × over-counted_R` doubled it again. It even had a passing unit
test asserting the wrong value (`2.5`).*

---

## GATE 3 — Causality / Known-At (no look-ahead)

- [ ] **Every input to a DECISION comes from a bar CLOSED strictly before
      `entry_ts`.** Not the sweep bar, not the FVG bar — the *decision-input* bar.
- [ ] Audit the **decision bar itself**, not just the fill. Assert
      `signal_ts < fill_ts` for **100%** of trades, and log the gap.
- [ ] **HTF / multi-timeframe bias** must be read at or before the entry bar — never
      at an outer-loop index that sits after the fill.
- [ ] **The +1 bar delay test:** if the edge dies when entry is delayed one bar, it
      was microstructure/look-ahead, not a real edge.
- [ ] **Random-benchmark test:** the signal must beat a random-entry same-direction
      benchmark. If it doesn't, it's a phantom.

*Why: COBRAX's `bias_align` read HTF bias at the outer loop bar — after the fill,
41% of trades. Headline PF 1.57 → causal PF 0.82. Look-ahead, not edge.*

---

## GATE 4 — Regime & Cost Honesty (no blended averages)

- [ ] **Never trust a single blended aggregate over a long history.** Slice by year
      and by regime. An "edge" can be a couple of good years dragging a decade of losers.
- [ ] **Cost is a fraction of R, and it moves.** `cost_r = fixed_$_cost /
      stop_distance`. As the underlying's price changes, the same `$` cost becomes a
      different % of every trade. Report `cost_r` per regime.
- [ ] **State the regime the edge needs**, and its kill condition: "profitable while
      gold > \$X; below that, cost eats it."
- [ ] Per-year PF table is mandatory for any multi-year claim. "21/21 positive years"
      must be true **per year under physical accounting**, not on the blended total.

*Why: the 21yr "edge" was a cheap-gold decade of losses (cost_r 0.3–0.5, PF <1)
hidden under a couple of expensive-gold winners. Real edge only appears 2025+
(gold \$2k–4k, cost_r ~0.05).*

---

## GATE 5 — Separate the EDGE from the SIZING

- [ ] **Measure the edge flat-risk, in R-space** — no compounding, no Model-B, no
      skim, no DB. This is the clean signal (PF, netR per year).
- [ ] **Then, separately,** project `$` with the real sizer. Never let a
      sizing/compounding artifact masquerade as the edge (or hide its absence).
- [ ] **Compounding a negative-expectancy stream WIPES.** If a Model-B run "wipes"
      or a snapshot `$` looks absurd, go back to flat-risk R to read the true edge.
- [ ] **Skim ≠ loss.** A sizer that withdraws profit shows a low trading balance
      while the wealth sits elsewhere; reconcile `equity + lifetime_skim` before
      comparing to a no-skim physical balance.

*Why: physical + Model-B 1.5% "wiped to \$33 / PF 0.56," while flat-risk R showed a
clean marginal PF ~0.85 and where it turns positive. The wipe was the sizing
death-spiral, not the edge itself; the `$` numbers were skim-vs-no-skim artifacts.*

---

## GATE 6 — ONE Source of Truth (no parallel re-implementations)

- [ ] **The backtest IS the live code path.** No research re-implementation of the
      strategy, sizing, bracket, or `$`-booking that can silently drift from live.
      One code, two modes; a change to live changes the backtest automatically.
- [ ] If two "backtests" of the same thing give different numbers (e.g. 25,902 vs
      27,959 trades), **both are suspect** — stop and reconcile before quoting either.
- [ ] Historical replays must stamp the **bar timestamp** on fills (not `now()`), or
      per-year / equity-curve analysis silently corrupts.
- [ ] Every surface that shows a number — landing page, dashboard, video, cert doc —
      cites the **same** canonical run. A visitor clicking "see track record" must
      see the number the marketing claims.

*Why: three "certified" runs (dashboard seed, cert doc, single-path) disagreed with
each other before the physical bug was even considered. Each was a separate
re-derivation. The fix: `run_live_path_bt.py` — the live code, run over history.*

---

## GATE 7 — Certification Is Not Permanent

- [ ] "Certified / frozen / 15-point PASS" means *it passed the checks we ran* — it
      is not a guarantee. A cert of a buggy convention is a certified bug.
- [ ] **Every cert must include a Gate-1 ground-truth check** (reconciled to real
      broker deals) and a **Gate-4 per-year regime table**, or it is provisional.
- [ ] When a foundational assumption is corrected, **all downstream certs are VOID**
      until re-run. No exceptions for "but it was frozen."
- [ ] Keep a **graveyard** of killed edges with the exact reason, so a dead idea is
      never silently resurrected.

*Why: "Fib V2 Certified + Frozen" and the "15-point audit PASS" were both of the
inflated convention. Frozen didn't mean correct.*

---

## The 8-line pre-commit checklist (tape it to the wall)

1. Did a good number make me happy? → audit it harder (Gate 0).
2. Does engine `$` == real broker `$`, per trade? (Gate 1)
3. Is every fractional exit booked physically, on the live lot? (Gate 2)
4. Is every decision input from a bar closed before entry? (Gate 3)
5. Per-year + per-regime table done; cost_r stated; kill condition named? (Gate 4)
6. Edge measured flat-risk in R, separate from the `$`/sizing projection? (Gate 5)
7. Is this the ONE live code path, and do all surfaces cite the same run? (Gate 6)
8. Any cert includes ground-truth + regime table, or it's provisional? (Gate 7)

If any answer is "no" or "not sure" — the number does not ship, does not get quoted,
does not get celebrated. It goes back to the bench.
