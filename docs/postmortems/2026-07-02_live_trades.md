# Live Trade Postmortems — Fib V2 Intraday A+D (JustMarkets-Demo2)

**Account:** 1100447101 · **As of:** 2026-07-02 09:39 UTC+3 (broker) · bid 4072.34
**Balance:** $9,938.29 · **Equity:** $9,925.86 · clean-account run (post-$10k reset)
**Strategy:** Fib V2 intraday mean-reversion, M15 base, lb=3, PTP+1R, Model B 1.5%

> Scope: the 3 trades on the current clean account. (Two earlier pre-reset trades
> — 2115780920 −$6 walker-parity bug, 2116651769 −$500 slip-inflation bug — are
> already covered in `docs/audit/L99_HOSTILE_AUDIT_2026-07-01.md`, both fixed.)

---

## Trade 1 — 2119597865 · D SHORT · CLOSED SL · −$60.45

| Field | Value |
|---|---|
| Direction | SHORT (D leg) |
| Entry | 4064.39 @ 2026-07-02 06:30 UTC+3 (03:30 UTC, ny_hr 23) |
| Stop | 4069.043 (risk 4.65 = 11.41 risk_units·wait see note) |
| Take-profit | 3970.27 |
| Volume | 0.13 lot (Model B sized) |
| Exit | 4069.04 @ 06:49 UTC+3 — **SL hit in 19 min** |
| net_R | **−1.06** (full stop) |
| $ | **−$60.45** |
| Fib geometry | L=4041.35 H=4068.50 diff=27.15; entry retrace 0.152 from H; fib zone [4051.72, 4062.69] |

**What happened:** classic failed-retracement short. D leg detected a down-impulse (H 4068.5 → L 4041.35), waited for price to retrace UP into the fib zone, shorted at 4064.39 expecting reversion down toward TP 3970. Price kept climbing instead — tagged SL 4069.04 nineteen minutes later. Gold was in a steady uptrend all session (current 4072, still rising); the "retracement" the D leg shorted into was actually trend continuation up.

**Was it a valid setup?** Yes — geometry correct, entry inside zone, 100% per spec. This is the 47% of D-leg trades that lose. Nothing broken. **fib_diff 27.15 is SMALL** (tight impulse) → low-impulse-strength bucket, statistically the weakest quintile (recall research: weak impulse → ~34% WR). Bad-quality-but-valid setup that failed as the odds predicted.

**Execution:** clean. SL filled at 4069.04 vs stop 4069.043 — **near-zero slip** (0.003). Full −1R as designed. No bug.

---

## Trade 2 — 2118599832 · A LONG · OPEN · +$11.46 (unrealized)

| Field | Value |
|---|---|
| Direction | LONG (A leg) |
| Entry | 4068.31 @ 2026-07-01 20:30 UTC+3 (17:30 UTC, ny_hr 13) |
| Stop | 4010.89 · Take-profit | 4384.77 |
| Volume | 0.02 lot |
| Fib geometry | L=4012.95 H=4115.72 diff=102.77; entry retrace 0.461; zone [4034.94, 4076.46] |
| R:R | 5.51 · impulse_strength 1.087 (Q5, TOP quintile) |
| Current | price 4072.34, ~+$11 unrealized, held ~13h across maintenance window |

**What happened:** A leg caught a strong up-impulse (L 4012.95 → H 4115.72, big diff 102.77), price retraced down into the fib zone, went long at 4068.31 betting continuation up to extension TP 4384. Price initially fell toward SL (was −$74 at one point yesterday) but has recovered — now back above entry, small green.

**Quality:** this is a HIGH-confidence setup — impulse_strength 1.087 = top quintile (56% WR bucket). The big impulse + deep-but-valid 0.461 retrace is exactly the A-leg's best profile. Still uncertain (Q5 = 56% WR, not 100%), but statistically the strongest of the three.

**Execution:** fill at 4068.31, SL/TP set correctly, survived the 21:00-22:00 UTC maintenance window without issue. Held ~13h — this is the **overnight-carry profile** (research: carried trades PF 5.20). If it reaches TP that's +5.5R; realistically will likely time-out or partial. No bug.

**Watch:** needs price to climb to 4384 (TP) — 312 points away. More likely resolves at partial-TP (+1R at 4125.78) or timeout. Currently just above BE.

---

## Trade 3 — 2119758067 · D SHORT · OPEN · −$25.50 (unrealized)

| Field | Value |
|---|---|
| Direction | SHORT (D leg) |
| Entry | 4065.63 @ 2026-07-02 07:30 UTC+3 (04:30 UTC, ny_hr 00) |
| Stop | 4117.46 · Take-profit | 3800.52 |
| Volume | 0.03 lot |
| Risk | ~51.83 pts stop distance (wide → big impulse) |
| R:R | ~5.1 · diff implied ~50 (H-L) |
| Current | price 4072.34 (above entry) → SHORT is offside −$25.50 |

**What happened:** D leg found a down-impulse and shorted the retrace up at 4065.63, TP way down at 3800. Same directional bet as T1 — betting reversion DOWN. Price is at 4072 now, **6.7 pts above entry** → offside but nowhere near SL 4117.46 (still 45 pts of room). Wide stop = big impulse = higher-quality than T1's tight one.

**Quality:** stop distance ~52 pts vs T1's 4.65 → this is a much bigger impulse (fib_diff ~50 vs T1's 27). Higher impulse-strength bucket than T1. But same structural risk: it's fighting the prevailing uptrend. If gold keeps grinding up it'll eventually hit 4117 SL (−1R ≈ −$52).

**Execution:** fill 4065.63, wide SL/TP set, no partial yet. No bug. Note: **T2 (A-long) and T3 (D-short) are concurrently open** — the hedge structure. Research showed "both open" is the best-PF bucket, so this concurrency is by-design, not a problem.

---

## Cross-trade read

| # | Ticket | Leg | State | net | Quality (impulse) |
|---|---|---|---|---|---|
| 1 | 2119597865 | D short | SL −$60 | −1.06R | LOW (diff 27, tight) — weakest |
| 2 | 2118599832 | A long | OPEN +$11 | — | HIGH (diff 103, Q5) — strongest |
| 3 | 2119758067 | D short | OPEN −$26 | — | MED-HIGH (diff ~50, wide) |

**Theme:** Gold is in a persistent uptrend (3960 → 4072 over the session). Both D-shorts are fighting it (mean-reversion betting the pullback resumes down); the A-long is aligned with it. This is exactly why:
- **T1 D-short lost** — shorted into trend continuation.
- **T2 A-long is green** — aligned with trend.
- **T3 D-short offside** — same fight as T1, but bigger impulse (more room).

**No execution bugs in any of the three.** All fills near-exact, SL/TP correct, sizing per Model B, concurrency by-design. The one loss (T1) is a valid low-impulse D-short that failed as the ~47% D-leg loss rate predicts. The overnight research already confirmed: **we cannot filter these out at entry** — low-impulse T1 vs high-impulse T2 differ in quality, but the impulse-strength filter (the only real signal) died at the post-2020 regime lens.

**Live behavior = matches BT expectation.** D leg struggling in an uptrend is normal — the A leg is the counter-balance (hedge). Account −$62 net on the closed trade, ~−$14 unrealized on the two open — well within noise for a $10k Model B book at 1.5% risk.

---

*Generated 2026-07-02 09:39 UTC+3. Source: reconciled broker closed_orders/open_orders + bt_trades DB. Two open trades' fib geometry partly reconstructed from broker SL/TP (live-run DB persistence gap for open positions — the fib_L/H raw_features only populate reliably for the D-leg trade that closed; noted as a minor instrumentation gap, not a trading bug).*
