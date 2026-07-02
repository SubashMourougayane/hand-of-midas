# MORNING RESEARCH REPORT — Overnight-Carry Tradeability & Loss-Cut Filters

**Strategy:** Fib V2 intraday mean-reversion, XAUUSD M15
**Baseline run:** `b6604240` — 27,950 trades, 8,279R, PF 1.516, 48.9% WR, 21/21 positive years
**Date:** 2026-07-02
**Scope:** 100% post-hoc research on existing trades + raw M5. ZERO edits to strategy/BT/live code. Research only — nothing ships without full 3-phase gauntlet + your explicit approval.

---

## PLAIN-ENGLISH VERDICT (read this if you read nothing else)

No. The overnight-carry edge cannot be turned into a tradeable signal, and none of the loss-cut filters we tried actually save money. The overnight PF of 4.11 is real but it is pure survivorship — "overnight" is only knowable at *exit* (a trade that survives to the next day without being stopped is definitionally already winning), and every at-entry proxy we built to predict it (late-session entry, TP-distance, impulse strength) either drops PF below baseline or captures a *different* quality edge with a low carry rate. The direct test — late-session entry, the strongest carry proxy at 0.72 hit-rate — **lowers** PF from 1.516 to 1.393. On the loss-cut side, every single one of the ~55 candidates across seven families has a **negative delta-R**: they all raise PF cosmetically by shrinking the book, but every one throws away more winner-R than it saves in loser-R. There is exactly one filter with positive delta-R (skip NY hour 17, +4.1R over 21 years) and it is statistical noise (0.05% of total R). Bottom line: the book is already tight, the losers are structurally inseparable from the winners at entry time, and there is no free profit to be recovered by cutting. Zero survivors reached the adversarial gauntlet. Baseline stays exactly as-is.

---

## 1. TL;DR

- **Did overnight-carry become tradeable? NO.** The 4.11 PF of overnight-carried trades is an exit-time survivorship artifact, not an at-entry signal. The strongest at-entry carry proxy (late-session entry, on_rate 0.72) drops PF *below* baseline (1.393). Definitively untradeable.
- **Loss-cuts that survived: ZERO.** Every candidate in every family has negative delta-R. All PF "improvements" are sample-shrink cosmetics that destroy more winner-R than loser-R saved.
- **The one positive-delta filter** (skip NY hour 17) contributes +4.1R over 21 years (+$743 lifetime) — noise, not a rule.
- **Adversarial gauntlet survivors: 0.** No candidate was promising+causal enough to enter the 3-lens gauntlet. `SURVIVORS: []`.
- **The real home of the losers** (intraday + low daily vol, PF 0.51) is an **exit-time label** with a flat carry rate (~0.38–0.40) across vol quintiles — no at-entry feature separates it. Look-ahead killed.

**Actionable conclusion:** Do nothing. The baseline is already tight. There is no profit currently "given back to losers" that can be recovered by an at-entry filter — the losers and winners are structurally entangled at decision time.

---

## 2. Overnight-Edge Section — Can Carry Become a Tradeable Signal?

### The raw fact (look-ahead — the thing we wish we could trade)
| Metric | Value |
|---|---|
| Rule | `entry_date != exit_date` (crosses UTC day) |
| Knowable at entry | **NO** (exit-time label) |
| n | 10,876 |
| Filtered PF | **4.114** |
| delta-R | +3,242.8 |
| Verdict | **LOOKAHEAD_KILLED** |

A trade that survives overnight without hitting SL is *definitionally* winning — the label is contaminated by outcome. Known decomposition: overnight PF 5.20 / WR 70.7% vs intraday PF 0.77 / WR 38.5% (net loser). The question is whether an **at-entry proxy** recovers this. It does not.

### At-entry proxies tested for carry+win

| Proxy | Rule (knowable@entry) | Carry rate | Filtered PF | delta-R | Verdict | Why it fails |
|---|---|---|---|---|---|---|
| **P1a late-session** | `entry hour in [15..23]` | **0.72 (highest)** | 1.393 | -5,910.7 | LOOKAHEAD_KILLED | Strongest carry proxy yet PF DROPS below baseline. late&carried PF 2.44 uses exit-time label; late&intraday PF 0.156. Direct test of hypothesis — **fails**. |
| P1b/P7b mid-session | `entry hour in [11,12,13,14]` | 0.28 (low) | 1.974 | -5,221.6 | WEAK | Genuine London/NY-overlap quality edge, 21/21 yrs — but LOW carry rate, opposite direction to hypothesis. Captures impulse quality, not carry. Negative delta-R. |
| P7c hr12-13 peak | `entry hour in [12,13]` | — | 2.198 | -6,457.4 | WEAK | Highest PF cut, 21/21 yrs, causal — but keeps 10.7% of trades, discards ~21,000R winners. Quality concentration, not carry. |
| P7d hr11-18 broad | `entry hour in [11..18]` | — | 1.743 | -3,580.1 | WEAK | Best delta-R of set but still discards more winner-R than loser-R saved. |
| P4 TP-distance/D1_ATR | `abs(TP-entry)/D1_ATR14` bucketed (corr 0.34 w/ carry) | Q5=0.66 | 1.694 (Q4) | 0 | WEAK | **Non-monotonic**: PF rises Q1→Q4 then rolls over Q5 despite Q5 highest carry. Carry-most quintile is NOT best-PF quintile. Reconfirms carry ≠ driver. |
| P5 fib_diff/D1_ATR | impulse strength bucketed | — | 1.715 (Q4) | 0 | REJECT | Duplicate of already-catalogued fib_diff impulse signal. Same roll-over shape as P4. Redundant. |

### Honest verdict on tradeability
**Overnight-carry is not tradeable.** Three independent lines of evidence converge:
1. **Direct test fails:** the strongest at-entry carry proxy (late-session, 0.72 hit-rate) drops PF below baseline.
2. **Non-monotonicity:** the highest-carry quintile (P4 Q5, 0.66) is NOT the highest-PF quintile — the carry rate does not track profitability.
3. **Decomposition:** late&carried PF 2.44 is entirely an exit-time artifact; the same late window filtered to intraday is PF 0.156.

The mid-session window (P1b/P7c) is a *real* causal quality edge but it is orthogonal — it wins by catching London/NY-overlap impulse, has a LOW carry rate, and is a PF-concentration filter with negative net-R (a keep-filter discarding 79% of trades including winner-R). It is not a loss-cutter and it is not the overnight edge.

---

## 3. Itemised Loss-Cut Table — All Candidates, Ranked by delta-R

Every candidate below is knowable at entry (causal) unless flagged. **All 21 causal loss-cut candidates have negative delta-R.** PF gains are sample-shrink cosmetics. Ranked best (least-bad) delta-R first.

| Rank | Candidate | Family | n | base PF | filt PF | delta-R | pos-yrs | Verdict |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | A_skip_worst1_ny_hours (`ny_hr != 17`) | Time | 27,751 | 1.516 | 1.521 | **+4.1** | 21/21 | WEAK (noise) |
| 2 | B_lastloss<=-2.0 (skip next after ≤-2R) | Streak | 27,734 | 1.516 | 1.519 | -37.2 | 21/21 | REJECT |
| 3 | A_skip_worst1_utc_hours (`!= 22`) | Time | 27,355 | 1.516 | 1.526 | -35.5 | 21/21 | REJECT |
| 4 | F6_skip_m15_atr_exp_bottom10 | Volatility | 25,155 | 1.516 | 1.570 | -165.6 | 21/21 | WEAK |
| 5 | C_dd>=40R throttle | Streak | 26,843 | 1.516 | 1.527 | -189.3 | 21/21 | REJECT |
| 6 | A_streak>=5 cooldown | Streak | 26,819 | 1.516 | 1.524 | -222.5 | 21/21 | REJECT |
| 7 | D_skip_fri_from_21utc | Time | 27,861 | 1.516 | 1.516 | -26.3 | 21/21 | REJECT |
| 8 | B_lastloss<=-1.5 | Streak | 26,085 | 1.516 | 1.540 | -283.2 | 21/21 | REJECT |
| 9 | A_skip_worst4_utc_hours (`!= 1,5,20,22`) | Time | 24,459 | 1.516 | 1.576 | -311.4 | 21/21 | REJECT |
| 10 | B2_leglastloss<=-1.5 | Streak | 25,877 | 1.516 | 1.538 | -380.4 | 21/21 | REJECT |
| 11 | F1_skip_d1_atr_pct252_bottom10 | Volatility | 25,205 | 1.516 | 1.542 | -538.3 | 21/21 | WEAK |
| 12 | A_skip_utc_hours_avgR_lt_0.15 | Time | 23,008 | 1.516 | 1.594 | -524.5 | 21/21 | REJECT |
| 13 | B_skip_within15m_around_session_boundary | Time | 26,613 | 1.516 | 1.500 | -618.2 | 21/21 | REJECT |
| 14 | A_streak>=4 cooldown | Streak | 25,736 | 1.516 | 1.514 | -710.4 | 21/21 | REJECT |
| 15 | F9_skip_stop_atr_ratio_top10 | Volatility | 25,158 | 1.516 | 1.512 | -749.3 | 21/21 | REJECT |
| 16 | A2_legstreak>=4 | Streak | 24,509 | 1.516 | 1.521 | -955.5 | 21/21 | REJECT |
| 17 | F5_skip_m15_atr_exp_top10 | Volatility | 25,155 | 1.516 | 1.497 | -1,039.1 | 21/21 | REJECT |
| 18 | F4_skip_d1_atr14_bottom25 | Volatility | 20,970 | 1.516 | 1.635 | -1,025.7 | 20/21 | WEAK |
| 19 | A_streak>=3 cooldown | Streak | 23,731 | 1.516 | 1.533 | -1,074.6 | 21/21 | REJECT |
| 20 | C_dd>=20R throttle | Streak | 23,552 | 1.516 | 1.540 | -1,087.8 | 21/21 | REJECT |
| 21 | F7_skip_m15_range_ratio_top10 | Volatility | 25,155 | 1.516 | 1.492 | -1,160.6 | 21/21 | REJECT |
| 22 | F2_skip_d1_atr_pct252_top10 | Volatility | 25,140 | 1.516 | 1.487 | -1,166.0 | 21/21 | REJECT |
| 23 | W1 M15 rej wick >=0.4 | Wick | 23,104 | 1.516 | 1.530 | -1,255.6 | 21/21 | REJECT |
| 24 | E_maxhold_K48m5_X0.5R early-exit | Time (max-hold) | 27,950 | 1.516 | 1.331 | -1,297.5† | 21/21 | REJECT |
| 25 | A2_legstreak>=3 | Streak | 22,256 | 1.516 | 1.522 | -1,627.6 | 21/21 | REJECT |
| 26 | F8_skip_stop_atr_ratio_bottom25 | Volatility | 20,971 | 1.516 | 1.593 | -1,691.6 | 21/21 | WEAK |
| 27 | C_skip_Fri | Time | 22,682 | 1.516 | 1.503 | -1,734.8 | 21/21 | REJECT |
| 28 | F3_keep_d1_atr_pct252_mid80 | Volatility | 21,533 | 1.516 | 1.531 | -1,784.1 | 20/20 | REJECT |
| 29 | C_skip_Thu | Time | 22,228 | 1.516 | 1.498 | -1,928.0 | 21/21 | REJECT |
| 30 | W3 M15 small-body + big wick | Wick | 20,979 | 1.516 | 1.520 | -2,024.8 | 21/21 | REJECT |
| 31 | C_dd>=10R throttle | Streak | 18,290 | 1.516 | 1.586 | -2,326.2 | 20/21 | REJECT |
| 32 | M15_RSI_align L≤50/S≥50 | Oscillator | 19,290 | 1.516 | 1.531 | -2,388.7 | 21/21 | WEAK |
| 33 | A_streak>=2 cooldown | Streak | 20,061 | 1.516 | 1.514 | -2,401.7 | 20/21 | REJECT |
| 34 | A2_legstreak>=2 | Streak | 18,558 | 1.516 | 1.550 | -2,491.6 | 21/21 | REJECT |
| 35 | M15_UO_align L≤50/S≥50 | Oscillator | 18,250 | 1.516 | 1.546 | -2,626.4 | 21/21 | WEAK |
| 36 | F10_mid_d1vol_and_no_range_spike | Volatility | 19,376 | 1.516 | 1.506 | -2,693.6 | 20/20 | REJECT |
| 37 | L1sr near ANY S/R d≤1.0 ATR | Location | 16,312 | 1.516 | 1.600 | -2,773.3 | 20/21 | WEAK |
| 38 | M15_MFI_align L≤50/S≥50 | Oscillator | 17,933 | 1.516 | 1.518 | -2,950.5 | 21/21 | REJECT |
| 39 | A_skip_worst4_ny_hours | Time | 25,438 | 1.516 | 1.555 | -269.6 | 21/21 | REJECT |
| 40 | B_skip_within60m_around_session_boundary | Time | 18,172 | 1.516 | 1.474 | -3,259.3 | 21/21 | REJECT |
| 41 | L4b stop within 0.5 ATR of S/R | Location | 14,257 | 1.516 | 1.615 | -3,367.5 | 21/21 | WEAK |
| 42 | H1_EMA200_trend_align | Oscillator | 13,771 | 1.516 | 1.596 | -3,614.2 | 20/21 | WEAK |
| 43 | B_lastloss<=-1.0 | Streak | 15,681 | 1.516 | 1.514 | -3,645.7 | 21/21 | REJECT |
| 44 | B2_leglastloss<=-1.0 | Streak | 14,578 | 1.516 | 1.522 | -3,905.6 | 21/21 | REJECT |
| 45 | M15_EMA200_trend_align | Oscillator | 13,367 | 1.516 | 1.570 | -3,978.8 | 21/21 | WEAK |
| 46 | C_dd>=5R throttle | Streak | 12,924 | 1.516 | 1.604 | -3,990.1 | 20/21 | REJECT |
| 47 | M15_EMA200_meanrev_stretch | Oscillator | 14,592 | 1.516 | 1.468 | -4,303.4 | 21/21 | REJECT |
| 48 | W2 M5 rej wick >=0.5 | Wick | 5,999 | 1.516 | 1.466 | -6,648.7 | 19/21 | REJECT |
| 49 | L5 vwap+S/R confluence ≤1 ATR | Location | 9,232 | 1.516 | 1.685 | -4,761.1 | 21/21 | WEAK |
| 50 | L4 stop-protected (level in stop band) | Location | 20,781 | 1.516 | 1.582 | -1,523.5 | 21/21 | WEAK |
| 51 | W4 M15 vol spike >=1.25 | Wick | 8,397 | 1.516 | 1.635 | -5,243.7 | 21/21 | REJECT |
| 52 | W5 M15 wick + vol spike combo | Wick | 7,202 | 1.516 | 1.609 | -5,779.2 | 21/21 | REJECT |
| 53 | W7 MTF wick (M15 & M5) | Wick | 7,519 | 1.516 | 1.507 | -6,064.6 | 20/21 | REJECT |
| 54 | L6 aligned bounce d≤0.5 ATR | Location | 5,053 | 1.516 | 1.557 | -6,674.5 | 19/21 | WEAK |
| 55 | E_maxhold_K6m5_X0.5R early-exit | Time (max-hold) | 27,950 | 1.516 | 0.960 | -6,787.1† | 11/21 | REJECT |
| 56 | W4 M15 vol spike >=2.0 | Wick | 2,756 | 1.516 | 1.863 | -6,958.6 | 20/21 | REJECT |
| 57 | W6 M15 stacked rejections >=2 | Wick | 4,414 | 1.516 | 1.487 | -7,027.0 | 21/21 | REJECT |
| 58 | L3 near Asia low d≤0.5 ATR | Location | 2,241 | 1.516 | 1.683 | -7,398.2 | 19/21 | WEAK |
| 59 | INV M15 opposite wick >=0.4 (falsification) | Wick | 1,863 | 1.516 | 1.813 | -7,461.1 | 21/21 | REJECT |
| 60 | H1_RSI_align L≤35/S≥65 | Oscillator | 2,341 | 1.516 | 1.311 | -7,848.5 | 15/21 | REJECT |
| 61 | L3 near PDH d≤0.5 ATR | Location | 1,486 | 1.516 | 1.491 | -7,880.4 | 19/21 | REJECT |
| 62 | M15_RSI40/60 + EMA200 align | Oscillator | 1,082 | 1.516 | 1.700 | -7,890.6 | 15/21 | REJECT |
| 63 | M15_MFI_align L≤20/S≥80 | Oscillator | 862 | 1.516 | 1.818 | -7,891.0 | 18/21 | REJECT |
| 64 | W8 full whale checklist (wick+vol+streak) | Wick | 1,341 | 1.516 | 1.633 | -7,805.2 | 18/21 | REJECT |

† Category-E max-hold deltas are vs a same-engine M5 **replay** baseline (PF 1.393), not the DB PF 1.516 — the replay has imperfect M5 parity. The `E_maxhold_Kx_X0.0R` control fires 0 cuts (delta-R=0) because the bracket logic precludes X=0 from ever triggering; it confirms the replay-baseline read.

**Time-based candidates additionally listed:** A_skip_worst8_utc_hours (n=21,591, PF 1.609, delta-R **-930.7** — highest PF of hour-skips, a pure profit-destruction trap), D_skip_fri_from_18utc (n=27,012, PF 1.518, delta-R -247.3 — weekend-gap hypothesis fails, late-Fri entries are net +247R).

---

## 4. Survivors Deep-Dive

**There are ZERO survivors.** `SURVIVORS: []` and `ADVERSARIAL VERIFY: []`.

No candidate cleared the promising+causal bar required to enter the 3-lens adversarial gauntlet (post-2020 stability / cross-symbol / +1-bar delay). The reason is structural and consistent across all 64 candidates: **every filter that raises PF does so by shrinking the book, and every one discards more winner-R than the loser-R it saves (negative delta-R).** The Fib V2 book is already tight — the partial-TP structure caps the typical loss near -1R, so there is no fat tail of large losers for a filter to surgically remove. The winners and losers are entangled at entry time.

There is no survivor to deep-dive, no post-2020 PF lift to report, and no deployment recommendation other than: **keep baseline as-is.**

---

## 5. Graveyard — Rejected This Round and Why

**Overnight-edge family:** All at-entry carry proxies rejected. The overnight PF 4.11 is exit-time survivorship (LOOKAHEAD_KILLED). Late-session (strongest proxy, 0.72 carry) drops PF below baseline. TP-distance and fib_diff proxies are non-monotonic and roll over exactly where carry rate peaks — proving carry is not the profit driver.

**Time-based loss-cuts:** Every hour-skip, session-boundary skip, day-of-week skip, and Friday-late skip removes *net-positive* buckets. No UTC/NY hour, no weekday, no session window, and no weekend-gap slice is net-negative (except NY hour 17 at a noise-level -4.1R). Session-boundary trades are *better* than average (whipsaw hypothesis inverted). Max-hold early exits: mean-reversion needs room — cutting fast (K=6) collapses PF to 0.96 / 11-21 pos years; even the gentlest (K=48) loses -1,297R because laggards recover often enough that banking small MtM losses forfeits their upside.

**Whale-location filters (PDH/PDL/Asia/London/VWAP proximity, stop-protection):** All raise PF but all cut winners > losers (best case L4 stop-protected still winners_lost 5,953 > losers_saved 4,430). Prior-day levels weakest (PDH proximity fails to beat baseline). Quality proxies, not loss-cutters.

**Mean-reversion oscillators (RSI/UO/MFI/EMA200 regime):** RSI+200EMA trend-align raises PF but delta-R -3,600 to -4,000. Counter-trend "stretch" flavour drops PF below baseline (fib entry already handles stretch). Higher-TF (H1) extreme alignment is actively harmful (PF 1.311). Extreme-selectivity variants (MFI ≤20/≥80, RSI40/60+EMA) hit PF 1.7-1.82 but keep <1,100 trades, delta-R ~-7,900, pos-years collapse to 15-18/21.

**Wick/absorption (candle geometry + volume):** The falsification control is decisive — the *wrong-direction* (continuation) wick scores HIGHER (PF 1.813) than the aligned rejection wick, proving wick direction is not causal. The only real gradient in the family is the volume-spike leg (monotone 1.32→1.67), and it is profit-concentration with delta-R -5,244, not loss-cutting. The "full whale absorption checklist" is a volume filter in disguise; wick + streak add only overfit noise.

**Volatility/ATR regime:** High daily-vol decile is the BEST bucket (PF 1.80) — strategy is long-vol; skipping high vol hurts. Compressed-vol decile is worst-PF (1.30) but still net-positive. Dropping either tail loses money. Tight ATR-normalized stops are low-WR but net-positive. F6 (skip M15 vol-contraction bottom 10%) is closest to break-even (-165.6R) but still net-negative.

**Streak/sequence (loss-streak, big-loss cooldown, DD throttle, leg-autocorrelation):** All reject. Streaks do not predict losses — meanR *after* 4 losers is actually +0.451 (higher). DD throttle at 5R has the seductive highest PF (1.604) but is on-nearly-always (median run-DD 5.8R), drops 54% of book for -3,990R. Partial-TP caps typical loss near -1R so "skip after big loss" rarely fires and still costs net-R.

---

## 6. Cross-Reference — Filter-Research Graveyard

Consistent with memory `filter-research-graveyard.md`: **every bolt-on filter to enhance Fib V2 intraday has been rejected via the 3-phase gauntlet; the baseline stays as-is.** This round confirms and extends that record. Do NOT re-propose the following as "new":

- **fib_diff / impulse-strength** — already catalogued (P5 here is an explicit duplicate; rejected as redundant). See memory fib_diff research.
- **ATR / volatility regime** — the long-vol nature of the strategy is known; high-vol is the best bucket, not a cut target. All F1-F10 reject/weak this round.
- **H1 / H4 higher-TF confirmation** — H1 oscillator alignment is actively harmful (PF 1.311). Consistent with prior HTF-confirmation rejections.
- **200-EMA trend regime** — raises PF, negative delta-R, sometimes degrades a pos-year. Classic survivor-combo (RSI40/60+EMA) over-filters to 15/21 years.
- **Momentum bolt-ons** — previously rejected; nothing here revisits or revives them.

Nothing in this round contradicts the graveyard; it reinforces it with a fresh 64-candidate sweep specifically aimed at loss-cutting rather than profit-adding.

---

## 7. Next Steps

**What merits a full 3-phase production gauntlet:** Nothing from this round. Zero candidates cleared the promising+causal bar. No candidate should consume gauntlet cycles.

**What is DONE (do not re-run):**
- Overnight-carry tradeability — definitively answered NO across three independent lines of evidence. Close this thread.
- At-entry proxies for carry (late-session, TP-distance, fib_diff) — exhausted.
- Time / streak / volatility / wick / location / oscillator single-factor loss-cuts — swept, all negative delta-R.

**What could still be explored (lower priority, needs care):**
1. **The mid-session quality edge (P1b/P7c, London/NY overlap, 21/21 pos years, causal).** This is a *real* orthogonal edge but it is a keep-filter with negative net-R (concentration, not addition). It does NOT answer the loss-cut question and does NOT add profit. Only worth revisiting if the mandate ever changes from "cut losses without more profit" to "position-size up in the highest-quality window" — a sizing question, not a filter question. Not a gauntlet candidate as-is.
2. **Interaction / joint filters** — this sweep was largely single-factor (a few 2-way combos: L5, W5, F10, W8 — all rejected). A disciplined 2-3 factor search *conditioned on the intraday-loser bucket* is the only remaining place a real loss-cut could hide. BUT: the true loser home (intraday + low daily vol, PF 0.51) is an exit-time label with a **flat carry rate across vol quintiles** — there is no at-entry feature that separates it. This is a low-probability lead; only pursue if a new at-entry regime feature (not yet tested) shows separation on the intraday sub-book *before* combining.
3. **More data** — none of these conclusions are data-starved. 27,950 trades over 21 years is ample. The negative delta-R results are structural (partial-TP caps loss size → no fat loser tail to cut), not noise-limited.

**Standard held:** nothing ships to production without a full 3-phase gauntlet + your explicit approval. This is research only. Recommended action for the live book: **no change.**

---

*Generated 2026-07-02. Baseline b6604240 unchanged. All candidates causal-verified via `_causal_lib.py` (close_ts <= entry_ts enforcement). Overnight and intraday-loser labels flagged LOOKAHEAD_KILLED where they depend on exit-time information.*
