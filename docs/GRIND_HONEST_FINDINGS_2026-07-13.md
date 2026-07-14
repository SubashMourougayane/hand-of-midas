# Honest Edge-Hunt Findings — 2026-07-13 (autonomous grind)

**Mandate:** find a both-direction, 1–5 trade/day, money-making intraday edge — "whatever it takes."
**Method:** ~27 iterations, full universe, both directions, STRICT causality, honest cost + financing, iron-clad Gate-0/execution audits.
**Verdict:** one real LONG-only edge; **no honest short exists**; the deployed A+D is an execution artifact.

---

## 1. What is REAL (causal, cost-honest, validated)

**Gold overnight risk-premium.** Buy XAU at 17:00 NY close, sell 08:00 NY next open. No stop. Long-only.

| filter | trades/day | Sharpe | WR | CAGR@10%vol | maxDD | $100k→20yr |
|---|---|---|---|---|---|---|
| strong-months (Jan/Feb/Jul/Aug/Nov/Dec) | 0.51 | 0.87 | 52% | +5.6% | −16% | $302k |
| + high-vol regime (atr20 > expanding-median) | 0.13 | 1.45 | 51% | +2.1% | −7% | $152k |

- Causal (calendar known; vol = expanding-median-lagged; entry at known close[t]).
- Confirmed independently: falling-real-yields long (Sh 0.84), trend-up long.
- Multi-asset overnight-long (SPX/NAS/BTC) exists too but weaker net of CFD financing (~5%/yr); combined Sh ~0.48, DD −47%.
- **Honest read:** real but MODEST + LONG-ONLY + low-frequency (below the 1/day target). Not a money-machine.

## 2. What is FAKE (caught + retracted by the audit)

- **Fib intraday PF-1.5 (incl deployed A+D):** close-based/−1R **execution artifact**. Under honest execution (hard-stop OR walker-with-real-loss) A+D **LOSES** (PF 0.76–0.91) and hides **−22R tail trades**. The −1R booking + close-based exits inflate every fib PF. Same class as the partial-TP over-count.
- **Multi-asset "session-momentum" system + "robust cross-asset short" (Sharpe 0.95–2.24, $836k–$110M, 21/21yr):** **LOOK-AHEAD**. The session legs (enter open, exit close) classified trend with `close[t]` — the very close being traded. Fixing to causal (prior close) collapses every session leg. VOID.
- Both phantoms were caught by the **Gate-0 tripwire** (too-good number → hostile audit). This is the discipline working.

## 3. NO SHORT EXISTS — proven from every angle

Gold short tested via: **trend-following, session, overnight, macro/real-yields, mean-reversion, COT-positioning (point-in-time), FX** — every one **dead or look-ahead**. Gold (and equities/BTC) are **long-drift assets**; the drift overwhelms every short thesis. FX (EUR/JPY) is efficient — no edge either direction. A real short needs a *different instrument class* (VIX/vol, options, futures roll-yield, inverse-ETF decay) — data not available via OANDA.

## 4. Dead ends (don't re-test)

Momentum breakout (0/1080), intraday mean-reversion (PF 0.38), cross-asset lead-lag (efficient), ORB, all SMC/ICT, gold/silver ratio RV (modern-sample mirage), silver overnight (gold-specific), COT contrarian.

## 5. Methodology lessons (permanent)

1. **A too-good number ($110M, Sharpe 2.2, Medallion-beating) = look-ahead. Always.** Gate-0 tripwire.
2. **OVERNIGHT drift legs are causal** (enter at known close[t]); **SESSION legs using close[t] for the signal are LOOK-AHEAD.**
3. **Fib/stop PFs are inflated** by −1R booking + close-based exits; honest execution reveals breakeven-to-losing + −22R tails.
4. **Vol-conditioning must use expanding-median (point-in-time), not full-sample median** (that's look-ahead).

## 6. Actions

- **CRITICAL (capital):** A+D loses under honest execution. **Never add a hard stop to A+D** (flips it to a certain loser — it survives only walker-style). **Don't scale it; watch live vs real broker cash.**
- **Deployable (modest):** the gold overnight strong-month(+hivol) long — long-only, Sharpe 0.87–1.45.
- **To find a short / more money:** requires a new data class (VIX/options/COT-futures-curve) with point-in-time discipline from the start.

*Full detail in auto-memory: `honest-both-direction-drift`, `fib-execution-artifact-critical`, `mega-sweep-long-short-system`, `intraday-ny-bull-pf15`, `ote-enhancement-regimefit`, `economic-signal-hunt-graveyard`.*
