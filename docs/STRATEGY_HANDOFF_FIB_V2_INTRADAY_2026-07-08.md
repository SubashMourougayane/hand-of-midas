# Fib V2 Intraday A+D — Strategy Handoff (Causally Explained)

**Updated:** 2026-07-08
**Supersedes the operational sections of:** `docs/FIB_V2_INTRADAY_PAPER_LIVE_CERTIFICATION.md` (2026-07-02)
**Strategy id:** `fib_v2_intraday_a` (long) + `fib_v2_intraday_d` (short)
**Symbol / TF:** XAUUSD.ecn (gold) · **M15** base == M15 pivots
**Broker / account:** JustMarkets-Demo2 · login 1100447101 · UTC+3 · hedging
**Status:** PAPER-LIVE, both legs running. Real capital NOT authorized.
**Freeze state:** strategy + engine FROZEN (monitoring mode). Do not edit strategy/engine code without an explicit un-freeze.

---

## 0. What changed since the 2026-07-02 certification

| Item | Was | Now (2026-07-08) | Where |
|---|---|---|---|
| Risk per trade | 1.5% | **3.0%** | `--risk-pct 0.03` on both leg services (ops config, no code edit) |
| Start balance seed | $5k / $10k | **$10k**, hydrated to live balance on restart | `--start-balance 10000`, `[SIZER] hydrated ... -> $10787` |
| Live balance | ~$9,930 | **~$10,786** | broker `account_info.json` |
| TP-reachability | assumed | **proven fat-tail** (see §6) | 27,963-trade bar-walk sim, 2026-07-08 |
| Market-data tooling | MT5 only | + TradingView MCP wired (macro/crypto only, **not** used for gold decisions) | `.mcp.json` |

Everything else (entry logic, brackets, causality guarantees, parity) is unchanged and still holds.

---

## 1. One-paragraph mental model

The strategy waits for a **confirmed swing** on gold, then waits for price to **pull back into a Fibonacci zone** of that swing, then requires a **confirmation candle** in the trade direction before entering on the **next bar's open**. It books **half the position at +1R** (moving the stop to breakeven) and lets the **other half run to a far 2.618 Fibonacci extension**. It loses small and often; it wins rarely and huge. The rare runners are the entire edge (§6). Two legs run in parallel and independent: **A = longs only** (London+NY session), **D = shorts only** (all sessions).

---

## 2. The causal pipeline, bar by bar

Everything below happens on a **just-closed M15 bar**. The engine guarantees `on_bar` only ever sees a bar that has fully closed — no partial/forming bars. This is the root of the no-look-ahead property. (`fib_v2_intraday/strategy.py:89-100`)

### Step 1 — Pivot detection (the causal lag that matters most)
Each closed M15 bar is fed directly to `PivotTracker(lb=3)`. A swing **high** or **low** at bar *i* is **only confirmed at bar *i+3*** — it needs 3 higher/lower bars on each side. So a pivot is **never known until 45 minutes after it printed**. (`strategy.py:100`, `PivotTracker.update`)

> This is exactly why, in live, the engine "hasn't adopted the fresh low yet" — by construction it *cannot* recognise a swing until 3 bars later. A human eyeballing the chart sees the low instantly; the engine legally cannot. That gap is a feature, not a bug.

### Step 2 — Setup construction
When both a confirmed low `L` (at `L_ts`) and confirmed high `H` (at `H_ts`) exist, and they are ordered correctly for the leg, a **FibSetup** is built. (`fib_v2/strategy.py:424-503`)

For a **long** (needs `L_ts < H_ts` — low before high, i.e. an up-leg):
```
diff     = H - L
fib_382  = H - 0.382*diff     ← shallow edge of entry zone
fib_786  = H - 0.786*diff     ← deep edge of entry zone
fib_100  = L                  ← invalidation level
TP       = H + 2.618*diff     ← far extension target (the runner's goal)
SL       = L - 0.02*diff      ← just under the swing low
```
For a **short** (needs `H_ts < L_ts` — high before low, a down-leg) everything mirrors: zone is `fib_382..fib_786` measured up from `L`, `TP = L - 2.618*diff`, `SL = H + 0.02*diff`.

`setup_confirm_ts = max(L_ts, H_ts)` — the setup is only "live" from the later of its two confirmed pivots.

### Step 3 — Entry scan (all checks on closed data only)
From the **first bar strictly after** `setup_confirm_ts` (research parity — `strategy.py:104-121`), each subsequent closed bar is tested, in order (`fib_v2/strategy.py:505-601`):

1. **Invalidation** — long: `close < fib_100 (=L)` → setup killed (structure broke). Short mirror. → `GATE_SETUP_INVALIDATED`
2. **Zone hit** — long: `fib_786 <= close <= fib_382`. Price must have pulled back INTO the fib zone. → miss = `GATE_SIGNAL_ZONE_MISS` (the most common "no trade" reason)
3. **Session** — A: NY-hours 3–17 (London+NY). D: all. → `GATE_SIGNAL_SESSION_FAIL`
4. **Regime** — `any` for both legs → gate is OFF (never blocks). (kept wired for auditability)
5. **Confirmation candle** — long: **bullish engulfing** (prev bar red, this bar green and engulfs it) **OR lower-wick pin** (lower wick > 50% of range). Short: bearish engulfing OR upper-wick pin. Uses the **previous** bar's open/close (cached last bar) — never the future. → pass = `GATE_SIGNAL_PASSED`, fail = `GATE_SIGNAL_CONFIRM_FAIL`

### Step 4 — Fill on the NEXT bar's open (no same-bar fill)
A passed signal at bar *k* is **queued** (`pending_entries`) and finalized on bar *k+1* using **`bar.open` as the entry price** (`strategy.py:198-215`, `fib_v2/strategy.py:603-682`). It is structurally impossible to fill on the signal bar — this kills the classic phantom-fill look-ahead.

At finalization, three production gates run (`fib_v2_intraday/strategy.py:135-175`):
- **Risk sign/finite** — `risk = entry - SL` (long) must be > 0.
- **Risk-pct cap** — reject if `risk > 2% * entry_price`.
- **Min-risk floor** — reject if `risk < $0.50` (broker-untradeable tiny stops).
- **Dedup** — `(entry_ts, side, leg_name)` seen-set blocks multi-pivot stacking on the same bar.

Survivors emit an `Order` (fixed-TP bracket) → `ENTRY_SUBMIT`.

### Step 5 — Bracket management (exit logic)
The engine bracket then runs, per trade:
- **Partial TP:** once MFE reaches **+1R**, close **50%** and move SL to **breakeven**. (`partial_tp_at_r=1.0`, `partial_tp_pct=0.5`)
- **Runner:** remaining 50% targets the **2.618 extension** TP.
- **Hold cap:** A = 12h (**48 M15 bars**), D = 24h (**96 bars**) → `TIMEOUT` exit. (`max_hold_bars = max_hold_h * 4`)
- **Stop:** SL (full loss, pre-partial) or SL_BE (breakeven after partial booked).

---

## 3. The four exit outcomes (what actually happens, 21yr)

| exit | meaning | D-short freq | avg R |
|---|---|---|---|
| `SL` | full stop, never reached +1R | 43.6% | −1.31 |
| `SL_BE` | partial booked, runner stopped at breakeven | 42.7% | +0.17 |
| `TP` | runner reached 2.618 extension | **8.9%** | **+6.93** |
| `TIMEOUT` | hold cap hit | 4.9% | +2.55 |

A-long is the same shape (TP 9.6%, +6.93R). **~9% of trades reach full TP, and they carry the entire strategy** — see §6.

---

## 4. Why there is no look-ahead (causality guarantees)

Certified line-by-line in `docs/audit/CAUSALITY_15POINT_LINE_AUDIT_2026-07-02.md` (ALL 15 PASS, two hostile reviewers). Essence:

1. **Closed bars only** — `on_bar` receives a just-closed bar; every signal check reads `bar.close` / `bar.high` / `bar.low` of closed bars and the *previous* cached bar.
2. **Pivots lag by design** — confirmed at `i+lb` (3 bars), never centered/future.
3. **No phantom fill** — 2-phase queue; entry price = *next* bar open, mathematically after the signal.
4. **Regime (when used) is shift(1)-lagged** — prior closed D1 only. (here `any`, gate off.)
5. **Risk & cost computed once at fill**, from the fill price, no forward peek.
6. **Session from bar timestamp** in NY tz; setup expiry from confirmed timestamps.

This is the non-negotiable house rule: **every feature comes from CLOSED bars before entry.** No exceptions.

---

## 5. Position sizing — Model B (updated to 3%)

`bt_engine/runner/equity_sizer.py`. Single lever.

```
risk_$   = current_equity * risk_pct          # risk_pct = 0.03 (was 0.015)
lot      = risk_$ / (stop_distance * 100)      # XAU contract = 100 oz/lot
lot      = clamp(lot, step=0.01, max=2.0)
```

- **Equity** is the sizer's internal Model-B equity, refreshed on trade close (not mid-flight). On restart it **hydrates from the live broker balance** (`[SIZER] hydrated equity ... -> $10787.28`), so a restart does not reset sizing to a stale seed.
- **Model B skim:** monthly asymmetric — on a profitable month, equity resets to the start baseline (profit skimmed off the risk base); losing months are kept. Structurally **cannot wipe** the account.
- **Slip-reject guard:** after fill, if `actual_risk / expected_risk > 1.15`, the fill is rejected and closed. (A near-cap slip can leave real risk marginally above 3% — e.g. a 1.135 slip → ~3.3% actual-at-stop; still inside tolerance.)
- Worked example (live 2026-07-08, both correct at 3%):
  `equity 10787.28 × 0.03 = $323.62 risk` → lot = 323.62 / (stop×100). Stop 34.56 → 0.09 lot; stop 22.55 → 0.14 lot.

To change risk: edit `--risk-pct` on the leg services and restart **while flat**. No code change.

---

## 6. TP-reachability study (2026-07-08) — why the "impossible" TP stays

User intuition: the 2.618 TP looks unreachable. **Correct — and it must stay that way.** Simulated every alternate runner-TP on the **real recorded bar path** of all 27,963 backtest trades (`bt_bar_walk.mfe_r`; a trade that reached peak-R ≥ new-TP takes it, else keeps its real outcome):

| Runner TP | % trades hit | net R (21yr) |
|---|---|---|
| +1.5R | 41.7% | **−652** ❌ |
| +2.0R | 33.1% | −606 ❌ |
| +3.0R | 23.5% | −297 ❌ |
| +4.0R | 17.9% | +68 |
| +5.0R | 13.8% | +607 |
| +6.0R | 9.7% | +2,379 |
| **2.618-ext (live)** | ~9% | **+8,562** ✅ |

**Lowering the TP to make it "reachable" turns the strategy negative below +4R.** The +1R partial already banks the reachable money (fires on 56.7% of trades). The runner exists solely to catch the +2R…+45R fat tail. **Conclusion: do not touch the TP.** This is on-record, quantified, closed.

Peak-R reachability (both legs): `+1R 56.7% · +2R 33% · +3R 23.5% · +4R 18% · +6R 9.7% · +10R 2.1%`.

---

## 7. Evidence chain (unchanged, still valid)

- **Edge (21yr, 2006–2026, run `b6604240`):** 27,950 trades · +8,279 net R · **48.9% win · PF 1.516 · 21/21 positive years.** Survived 15-pt stress battery, cross-symbol, delay/cost stress, FLIP, bootstrap P(net<0)=0.000, permutation p=0.000.
- **BT = Live parity (21yr):** 27,965 trades, **0-delta** on trades/net-R/win/PF; every trade identical. Research = BT = live code path. (`scripts/parity_21yr_bt_vs_live.py`)
- **Execution audits:** L99 (13 suspects, 4 real bugs fixed) + A+D 100x audit (decision layer proven deterministic; C1/H1 fixed+deployed). Slip-reject, reconciler aggregation, partial-TP retry, concurrent A+D all hardened.
- **Realistic PnL (all costs modeled, P0-P2 on):** ~**5,209 net R** (−37% vs fantasy), ~$22k/yr avg on a $5k compounding start, 18/21 positive years after costs. **This is the number to trust — not the fantasy compounded total.**
- **Loss-cut research:** 474-combination sweep → ZERO positive delta-R. Baseline is optimal; partial-TP already caps the loss tail.

---

## 8. Live state (2026-07-08)

- Both legs up: `midas-live-a` (pid 8532) + `midas-live-d` (pid 11492), started 7/7 23:27 IST, `--risk-pct 0.03 --start-balance 10000 --max-live-lot 2.0 --max-entry-slip-ratio 1.15 --max-open-positions 4`.
- Broker: balance **$10,785.67**, equity **$10,747.20**, 2 open D-short positions (0.09 + 0.14 lot), both **verified correct at 3%**.
- Telegram notifier live (decoupled via Postgres LISTEN/NOTIFY); env bug fixed, delivery verified.
- Dashboard: Hand of Midas terminal, MT5-as-truth, mobile pass done.

---

## 9. Known limitations / open items (not blocking)

1. Open-trade fib geometry not persisted to DB (dashboard trade-story partial for *open* trades) — instrumentation only.
2. `fib_v2/strategy.py:18-39` docstring references an old "bar.close proxy" — code uses next-bar OPEN correctly; cosmetic.
3. DST: `_infer_server_utc_offset_hours` read once at start — safe for JM (UTC+3, no DST); re-audit if broker changes.
4. Cert doc §"Live operation record" still cites 1.5% / $9,930 — see §0 here for the current 3% / $10,786 truth.

---

## 10. Conditions before real capital (still pending, deliberately)

- [ ] 30+ days clean paper-live, realized P&L within realistic-BT band
- [ ] Broker cost reconciliation within 10% of modeled per-lot cost
- [ ] Cross-symbol live validation (EUR secondary) if expanding
- [ ] Explicit user authorization + real-account risk limits

**Current status: PAPER-LIVE. Real capital: NOT authorized.**

---

*Strategy code causal-proven (15-pt line audit), BT=live parity-proven (21yr 0-delta), execution-audited (L99 + 100x), realism-modeled (P0-P2), loss-cut-exhausted (474-combo), TP-fat-tail confirmed (2026-07-08, 27,963-trade bar-walk). Live clean. Real capital requires the pending conditions above + explicit approval.*
