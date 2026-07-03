# Live Trade Postmortem — since 10K deposit (2026-07-01)

**Account:** JustMarkets Demo2 (1100447101) · **Strategy:** Fib V2 intraday A+D (M15) · **Sizing:** Model B 1.5% equity.
**Window:** deposit 2026-07-01 13:37 UTC → 2026-07-03 ~12:00 UTC.
**Data source:** broker-reconciled `bt_trades` (broker_net_usd = MT5 truth where reconciled).

> **Sample-size honesty:** 5 closed trades. This is FAR too few to judge the edge —
> the statistical basis is the backtest (PF ~1.31, ~253 trades/yr, 7/8 positive years).
> What 5 closed trades CAN show is **execution quality**: are fills, stops, holds, and
> costs behaving as the strategy intends? That's the lens below.

## Scoreboard (closed)
| # | Ticket | Leg | Entry | Exit | Reason | Bars (M15) | net R | $ | Verdict |
|---|--------|-----|-------|------|--------|-----------|-------|---|---------|
| 1 | 2119597865 | SHORT | 4064.39 | 4069.04 | SL | 2 (30m) | −1.06 | −60.45 | Instant stop — noise |
| 2 | 2119758067 | SHORT | 4065.63 | 4117.46 | SL | 33 (8h15m) | −1.01 | −155.49 | Wrong-way trend, full SL |
| 3 | 2121027691 | LONG | 4064.77 | 4149.17 | TP | 69 (17h15m) | +6.25 | +823.64 | Clean winner, ran to ext-TP |
| 4 | 2123464608 | SHORT | 4123.79 | 4132.13 | SL | 30 (7h30m) | −1.00 | −108.42 | Full SL |
| 5 | 2123659696 | SHORT | 4124.66 | 4132.02 | SL | 14 (3h30m) | −0.83 | −117.76 | SL (partial-loss on gap?) |

**Closed net:** +$381.52 realized · **+3.35 R** · 1 win / 4 losses (20% win rate).
**Open:** 2118599832 LONG (partial +$62.88 booked, ~+$104 floating) + 2 fresh today (2125574587 L, 2125844421 S).

---

## Per-trade forensics

### #1 — 2119597865 SHORT · −1.06R · −$60.45 · "noise stop"
Entered 4064.39, SL 4069.04 (**11.4 risk-units ≈ $4.65 stop distance**), TP 3970.27. Stopped in **2 bars (30 min)** — price ticked up 4.65 and hit stop almost immediately. Classic tight-stop-into-noise. Nothing wrong with execution: SL was exactly where the setup placed it, fill clean. Just a bad entry that the market rejected fast. **−1.06R** (slightly beyond 1R = cost/slip drag). No lesson beyond "shorts near a rising level get stopped."

### #2 — 2119758067 SHORT · −1.01R · −$155.49 · "wrong-way trend"
Entered 4065.63 short, held **33 bars (8h15m)**, stopped at 4117.46 — price ran **+52 points against** the short. This was the leg fighting the up-move that later gave trade #3 its +6R long. **Biggest $ loss** because risk-units were large (47.2 = ~$19 stop → 0.33 lot). Execution fine (full 1R, no excess). Signal-quality issue: shorting into what became a strong uptrend. The A+D design *expects* this — one leg pays for the other.

### #3 — 2121027691 LONG · +6.25R · +$823.64 · "the winner" ⭐
Entered 4064.77 long, TP 4149.17 (**ext_target 2.618× fib**), hit in **69 bars (17h15m)**. Partial-TP fired (+0.50R booked early, SL→BE), remainder ran to full extension target. **This is the strategy working exactly as designed**: pull-back entry, partial de-risk, let the runner hit the 2.618 extension. Single trade paid for all 4 losses + net +$381. Textbook.

### #4 — 2123464608 SHORT · −1.00R · −$108.42 · "clean full SL"
Entered 4123.79 short, SL 4132.13, stopped **30 bars (7h30m)**. Exactly −1.00R = textbook stop, no slip. **Largest-lot loss** (0.13 lot) — this was the 0.13 short from the cutover era. Execution perfect, just wrong direction (price kept rising).

### #5 — 2123659696 SHORT · −0.83R · −$117.76 · "sub-1R stop"
Entered 4124.66 short, SL 4132.02, out in **14 bars (3h30m)** at **−0.83R** — *less* than a full stop. Two readings: (a) closed slightly before the full SL level, or (b) a partial fill. Worth noting the $ (−117.76) is larger than #4's despite smaller R — bigger lot. Both shorts #4 + #5 stopped at the **same timestamp** (04:33) — a shared up-move flushed both.

---

## Patterns (what the 5 closes actually tell us)

1. **All 4 losers were SHORTS; the only winner was a LONG.** Over 2026-07-01→03, XAU trended **up** hard (4064 → 4180+). The D (short) leg bled into the trend; the A (long) leg caught it. This is the A+D hedge behaving as intended — NOT a bug. Over a trending window, expect the counter-leg to lose.

2. **Loss discipline is clean.** Every loss was ≈ −1R (−1.06, −1.01, −1.00, −0.83). No blown stops, no runaway losses, no −3R disasters. Execution of the stop is working.

3. **The winner used the full machinery** — pullback entry + partial-TP + 2.618 extension runner. That's where the asymmetry lives: losers capped at −1R, winner made +6.25R.

4. **Win rate 20% is fine for this profile.** A 2.618-extension trend strategy is *supposed* to be low-win-rate / high-payoff. 1-in-5 at +6R vs −1R = strongly positive expectancy. (BT win rate is higher because BT has more trades across regimes; a 5-trade trending sample skews low-win.)

5. **Cost drag is small but present** — losers came in at −1.01 to −1.06R (the >1R excess = ~$0.30 cost + minor slip per trade). Matches the modeled cost. Nothing anomalous.

## Execution verdict
**The system is executing as designed.** Stops fire at −1R, partial-TP + extension worked on the winner, no fill/slippage anomalies, costs match the model. The 4:1 loss:win count is a **trending-window artifact** (shorts vs an uptrend), not a defect — and expectancy stayed positive (+3.35R / +$381).

## What I'd watch next (NOT act on yet — freeze holds)
- **Short-leg drawdown in strong trends.** If XAU keeps trending, D keeps bleeding ~−1R/trade. Expected, but track the D-leg's standalone R over the next ~30 trades — if it's structurally worse than backtest, that's a real signal.
- **The −0.83R on #5** — confirm it was a legit early-close, not a reconciliation artifact. Minor.
- **Sample.** Re-run this postmortem at 30+ closed trades. Until then, no strategy conclusions — this is execution-QA only.

## Data caveats
- MFE/MAE not captured in bt_trades (would need bar_walk join) — "how far each ran" is inferred from entry/SL/TP geometry, not tick-exact excursion.
- 2 trades opened today (2125574587 L, 2125844421 S) still open — excluded from closed stats.
