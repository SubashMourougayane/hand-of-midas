# Fib V2 Intraday A+D — Paper-Live Certification

**Strategy:** `fib_v2_intraday_a_plus_d` (A long-leg + D short-leg, M15 base, lb=3 pivots, PTP+1R, Model B 1.5% asymmetric monthly sizer)
**Symbol:** XAUUSD (gold)
**Broker:** JustMarkets-Demo2 (login 1100447101, UTC+3, hedging account)
**Certified:** 2026-07-02
**Branch/commit:** `fib-v2-clean` @ (see git log — post 2a6738e09)

---

## Certification statement

The Fib V2 Intraday A+D strategy is **certified for continued paper-live operation** on the JustMarkets-Demo2 account. Its strategy logic is proven causal (no look-ahead), the BT and live code paths are proven identical over 21 years, execution bugs found in prior audits are fixed and verified, and 24h+ of clean paper-live operation has been observed with zero red flags.

This certifies the **strategy code and execution pipeline** — NOT a profit guarantee. Realistic expected return is stated below with all costs modeled.

---

## Evidence chain

### 1. Edge (research baseline, 21 years, 2006-2026)
Run `b6604240` — research-parity combined A+D:

| Metric | Value |
|---|---|
| Trades | 27,950 |
| Net R | +8,279 |
| Win rate | 48.92% |
| Profit factor | 1.516 |
| Positive years | 21/21 |

Survived: 15-point stress battery, cross-symbol (XAU primary, EUR secondary), delay stress, cost stress, FLIP test, bootstrap P(net<0)=0.0000, permutation p=0.0000.

### 2. Causality — 15-point line-by-line audit (2026-07-02)
`docs/audit/CAUSALITY_15POINT_LINE_AUDIT_2026-07-02.md` — **ALL 15 PASS**, cited to file:line, two independent hostile reviewers + manual cross-check.
- Pivot idx+lb confirm lag, H1/D1 causal aggregation, strict-prior-day regime (shift(1))
- No phantom fill: 2-phase `pending_entries` → next-bar OPEN entry (structurally same-bar-fill-impossible)
- Confirmation candle uses prior bar; all signal checks on closed bar.close only
- Bracket close-based, slip deterministic no forward peek
- Intraday strict-after confirm; risk/cost at fill computed once
- Setup + entry-bar dedup; min-risk floor; setup expiry; live tz UTC+3→UTC at boundary

**Verdict: no look-ahead, fully time-aware candle-close, no causality bug.**

### 3. BT = Live parity — 21 years (2026-07-02)
`bt_engine/scripts/parity_21yr_bt_vs_live.py` — same strategy through `run_engine(mode='bt')` vs `mode='live'` (mirror broker, identical fill semantics):

| Metric | BT path | Live path | Δ |
|---|---|---|---|
| Trades | 27,965 | 27,965 | **0** |
| Net R | 7,655.21 | 7,655.21 | **0.00** |
| Win % | 48.77 | 48.77 | **0.00** |
| PF | 1.4882 | 1.4882 | **0.0000** |
| Pos years | 21/21 | 21/21 | — |

**Trade-level: 27,965 shared / 0 only-BT / 0 only-LIVE — every trade identical (ts, side, net_R).** Research = BT = live code path, proven over full history.

### 4. Execution bugs — found + fixed (L99 audit, 2026-07-01)
`docs/audit/L99_HOSTILE_AUDIT_2026-07-01.md` — 13 suspects, 4 REAL bugs fixed + verified on real broker, 9 NO-BUG proven:
- Sizer post-fill slip re-check (rejects fills where actual/expected risk > 1.15×)
- Reconciler aggregates multi-deal partial-close by position_id
- Partial-TP modify retry (3× + safe-close fallback)
- max_open_positions default 4 (concurrent A+D)

### 5. BT-vs-live realism divergences — mapped (2026-07-02)
`docs/audit/L99_BT_VS_LIVE_PARITY_2026-07-02.md` — 22 divergences (execution physics, NOT code). BT realism layer P0-P2 built (per-lot cost, entry/SL slip, overnight swap, engine caps, gap slip, requote, partial-TP-fail) — 307 tests pass, all opt-in defaults reproduce baseline.

### 6. Realistic PnL (all costs modeled)
| Scenario | Net R | Net $ (from $5k Model B) |
|---|---|---|
| Fantasy (flat cost, no slip) | 8,279 | $850,710 |
| **Realistic (P0-P2 all on)** | **5,209** | **$461,264** |

Realism cost = −37% R / −46% $. Realistic ~$22k/yr avg on $5k compounding start, 18/21 positive years after costs (2006/2017/2018 marginal-negative). **This is the number to trust** — not the fantasy compounded total.

### 7. Loss-reduction research — exhausted, baseline optimal
`docs/research/overnight_2026-07-02/MORNING_REPORT.md` + mega-sweep: 474-combination sweep (single + 2-way + 3-way) across impulse / location / retrace / vol-regime / sentiment / bias / concurrency / day-of-week / session / wick — **ZERO positive delta-R**. Partial-TP+1R already caps the loss tail; winners/losers entangled at entry beyond any filter. Overnight-carry NOT tradeable (exit-time survivorship). S/D breakout REJECT (PF 0.5-0.75, dies at +1 delay). Baseline stays as-is.

---

## Live operation record (as of 2026-07-02)

- **Both legs running:** A (fib_v2_intraday_a) + D (fib_v2_intraday_d) on JM-Demo2, 24h+ continuous.
- **Sizing:** Model B, 1.5% risk/trade, $10k start balance, max_lot cap 2.0, slip-reject 1.15×, max_open_positions 4.
- **Monitor:** 15-30min health snapshots — zero red flags across the full watch (no tracebacks, both procs alive, EA fresh, no >5% equity drops).
- **Trades observed:** postmortems in `docs/postmortems/2026-07-02_live_trades.md` — 3 clean-account trades, 0 execution bugs, all valid setups (1 SL loss = expected low-impulse D-short in an uptrend; 2 open).
- **Account:** ~$9,930 equity (started $10k, small drawdown within noise for a 1.5% book).

---

## Known limitations & open items (not blocking)

1. **Open-trade fib persistence gap** — live open positions don't persist fib_L/H to DB (dashboard trade-story shows partial geometry for open trades). Instrumentation, not trading.
2. **Stale docstring** — `fib_v2/strategy.py:18-39` prose references an old "bar.close proxy" approach; actual code uses next-bar OPEN correctly. Cosmetic.
3. **DST offset** — `_infer_server_utc_offset_hours` reads once at start; safe for JM (UTC+3 no DST); re-audit if broker observes DST.
4. **US-data-window sizing** — one unrefuted research lead (13-15 UTC, +6.8-17% leverage-neutral); pending full gauntlet before any production consideration.

---

## Certification conditions (for going to real capital — NOT yet authorized)

Before real money (all still pending, deliberately):
- [ ] 30+ days clean paper-live with realized P&L within realistic-BT expectation band
- [ ] Broker cost reconciliation confirms modeled per-lot cost within 10%
- [ ] Cross-symbol live validation (EUR secondary) if portfolio expansion desired
- [ ] Explicit user authorization + real-account risk limits set

**Current status: PAPER-LIVE CERTIFIED. Real-capital: NOT authorized.**

---

*Certified 2026-07-02. Strategy code causal-proven (15-pt), BT=live parity-proven (21yr 0-delta), execution-audited (L99), realism-modeled (P0-P2), loss-cut-exhausted (474-combo). Live clean 24h+. Standard held: real capital requires the pending conditions above + explicit approval.*
