# Filter #28 — Disable Bias Filter (CRITICAL CANDIDATE)

**Status:** RESEARCH STAGE — single-seed BT done, **NOT shipped**, awaiting full sweep workflow
**Discovered:** 2026-06-17 during user-driven investigation after −$868 live day
**Severity:** Potential MASSIVE alpha — +$3.58M over 21yr in initial BT — but unverified

---

## Origin

Today (2026-06-17) was a brutal Brent day:
- Yesterday's daily candle was −4.5% (close $79.22 vs open $82.94) → bias filter classified today as `bearish`
- Brent intraday actually MEAN-REVERTED upward from $77.61 morning low to $79.65+ afternoon
- Bias filter forced 4 SHORT trades, all SL'd, **net −$868** on Oil systems alone
- 3 BULLISH wick LONG signals fired and got `bias_block` in early UTC — would have likely been profitable

User asked: **"what if bias were neutral every day?"**

I ran the same `run_backtest()` code path the dashboard uses, with `daily_bias` monkey-patched to always-neutral. Results below.

## Initial BT result (single-seed, no fake fills, real engine path)

| System | WITH bias | NEUTRAL | Δ P&L |
|---|---|---|---|
| Gold Macro | N=2242, WR 65.5%, $+428k | N=2863, WR 66.8%, $+661k | **+$233k** |
| Gold Micro | N=1784, WR 77.1%, $+390k | N=2286, WR 79.1%, $+576k | **+$186k** |
| Oil Macro | N=1656, WR 62.7%, $+1.01M | N=2442, WR 63.4%, $+2.00M | **+$997k** |
| Oil Micro | N=4504, WR 79.9%, $+3.71M | N=6128, WR 80.4%, $+5.87M | **+$2.16M** |
| **TOTAL 21yr** | **$+5.54M** | **$+9.11M** | **+$3.58M** |

**ALL 4 SYSTEMS improved without bias filter.** Trade count up 30-65%, WR up 1-2pp, P&L up 33-100%+.

## Reproduction

```
Script: /tmp/neutral_bias_v2.py (committed snapshot at scripts/research/filter_28_neutral_bias_baseline.py)
Method: NeutralBiasDict subclass overrides .get() and __getitem__ to always return "neutral"
        Pre-import strategy module → swap generate_signals → engine import sees patched ref
        Engines run unchanged via fresh sys.modules wipe per run
Verified: trade counts go UP (proves bias filter was blocking), WR same/better (rules out bad-trade-influx)
```

## Why this is suspicious — DO NOT SHIP YET

🦣 The result is too good. Defensive checks BEFORE believing:

### 1. Distribution check needed
- Is the +$3.58M concentrated in volatility spikes (2008, 2020) where mean-reversion broke down?
- Is the equity curve smoother or LUMPIER without bias?
- What's the worst single-day, worst-month, worst-year on neutral vs bias?

### 2. Drawdown stress
- Bias filter likely sacrifices average P&L for smaller drawdowns
- More trades + more concurrent risk → harder DD profile
- DD>20% killed many strategies in this codebase historically

### 3. Multi-seed determinism
- BT engine has `seed=42` for slippage RNG. Single-seed = single point estimate
- Need ≥5 seeds to get confidence interval

### 4. Yearly slice (per [[project-filter-sweep-workflow]])
- 21 years × 4 systems = 84 (year, system) cells
- "Recent regime" check: is the win concentrated in ancient years that don't match today's volatility regime?
- If 5/7 most recent years are RED on neutral but old ones are GREEN — STASH it

### 5. Per-system selective ship per [[feedback-selective-ship-pattern]]
- Even if some systems benefit, others may not
- Each system needs its own ship/stash decision

### 6. Live↔BT parity
- Today's live data should match BT outcome on those exact 4 trades
- If neutral BT says today would have been +$X, but live data + code path says different, parity broken

## Counter-hypothesis to verify

🦣 The bias filter might be filtering out **trend-day signals that happen to be profitable**, but the filter exists to protect against **regime-shift days where unbiased trading gets killed**. Without it, we could be lucky in BT but exposed to catastrophic single-day losses in regimes the BT's 21-year window happens to under-sample.

Specifically:
- The 2008-2009 oil collapse (Brent dropped 75% in 6 months)
- The 2020 negative-oil-price event (April 2020 WTI went −$37, Brent dropped 50%)
- Both are in our BT data, but a single 21-yr window doesn't have enough such events to estimate true tail risk

## Plan of action — full sweep workflow

Following [[project-filter-sweep-workflow]]:

| Step | Owner | Status |
|---|---|---|
| 1. Write research doc (this file) | claude | ✅ DONE |
| 2. Preserve baseline script as committed artifact | claude | ⏸ TODO — `/tmp/neutral_bias_v2.py` → `scripts/research/filter_28_neutral_bias_baseline.py` |
| 3. Create branch `filter/28-bias-disable` off `midas-deploy` | user | ⏸ |
| 4. Per-system real BT pre/post on dedicated branch | user/claude | ⏸ |
| 5. Multi-seed runs (5 seeds, 21yr each) | user/claude | ⏸ |
| 6. Yearly slice + recent-regime check | user/claude | ⏸ |
| 7. Drawdown stress test (max DD, worst-month, worst-year) | user/claude | ⏸ |
| 8. User ship/stash decision per system | user | ⏸ |
| 9. If ship: per-system config flag + selective rollout | user/claude | ⏸ |
| 10. If ship: live verification + 30-trade calibration window | user/claude | ⏸ |

## DO NOT

- ❌ Touch live config tonight
- ❌ Ship globally — must be per-system per [[feedback-selective-ship-pattern]]
- ❌ Skip yearly slice — even +$3.58M is meaningless if 5 of last 7 years RED
- ❌ Trust single-seed result — could be slippage-RNG-lucky

## DO

- ✅ Treat as #1 candidate for next filter wave
- ✅ Run full workflow when next time-window opens
- ✅ Reference today's −$868 live day as the trigger event in the research log

## Today's live data point

```
Date: 2026-06-17
Bias used: bearish (correctly computed from yesterday's daily)
Actual day: trending-up Brent (mean-reversion of yesterday's selloff)

Trades fired (all SHORTs, bias-aligned):
  OIL-MI-08b725d3  SHORT @ $79.03 → BE-stop +$9.10
  OIL-MI-ea9d591d  SHORT @ $79.09 → SL −$318.50
  OIL-MI-6fbb7040  SHORT @ $79.23 → SL −$306.60
  OIL-AS-e5705d4e  SHORT @ $79.28 → SL −$252.00

Trades BLOCKED by bias (would-have-fired LONGs):
  ~05:00 UTC bullish wick at $77.90 (poked below 0-4 range_low $78.25)
  ~06:00 UTC bullish wick at $78.02
  ~07:00 UTC bullish wick at $77.61

Counterfactual (rough):
  Net WITH bias:    −$868 (actual)
  Net NEUTRAL:      ~+$500 to +$1500 (estimated, all 3 LONGs likely BE-stopped or TP'd)
```

## Decision log

| Time | Decision |
|---|---|
| 2026-06-17 ~17:30 IST | User asked "what if no bias?" — single-seed BT showed all 4 systems improve |
| 2026-06-17 ~18:00 IST | Filter #28 candidate added to backlog (#289) |
| 2026-06-17 ~18:15 IST | Research doc written (this file) |
| (pending) | Full sweep + multi-seed + yearly slice |
| (pending) | User ship/stash per system |
| (pending) | If ship: branch merge + live deploy |

## Cross-references

- Memory: [[bug-daily-bias-keying]] — June 12 fix corrected bias keying off-by-one (PF was 2.3x inflated). The FILTER itself was assumed beneficial; we never tested disabling.
- Memory: [[project-filter-sweep-workflow]] — canonical sweep workflow
- Memory: [[feedback-selective-ship-pattern]] — per-system, not global
- Memory: [[feedback-no-auto-ship]] — explicit user sign-off required
- Memory: [[feedback-replay-vs-real-backtest]] — only real BT counts; today's result IS from real BT engine path
- Doc: `docs/SESSION_2026_06_12.md` — drift bug #6 history
- Doc: `docs/FILTER_27_AUDIT_BACKLOG.md` — current audit backlog
