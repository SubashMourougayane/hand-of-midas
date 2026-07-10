# COBRAX — Deploy as 3rd Live Leg (Implementation Plan)

**Status:** APPROVED, not started. Picking up in a future session. Research fully done +
validated; this is the engineering port + deploy plan.

**Decisions locked:** M5 data via **patching the DWX EA to export M5**; COBRAX on the **same
broker account** as A+D. Config = headline `ote(0.62,0.79)/lb3/edge/sweep + bias_align`,
`tp=rr3`, both directions, realistic cost.

---

## Context
COBRAX (OTE sweep→BOS→FVG scalp, M5 XAU) passed every research gate: additivity vs Fib V2
(monthly-R corr **+0.07** — independent streams), hostile audit, cost, OOS, bootstrap,
cross-asset (XAU+NAS). It is a **real but MINOR** uncorrelated diversifier — ~10% of A+D's R;
value is **smoother risk-adjusted return, not raw $** (combined-$ only pays at ≤2.5% total risk).

Reference research engine (vectorized batch scanner): `research/cobrax/cobrax.py`. Must be
**ported to a streaming, causal `Strategy`** matching the `fib_v2_intraday` pattern, then
**certified** (streaming↔research parity, BT=live parity, causal audit) before real money.

**Reuse-vs-build inventory (from exploration):** REUSE — `PivotTracker(lb=3)`
(`fib_v2/pivot_tracker.py:36`), `_ny_hour`/`_in_session` (`fib_v2/strategy.py:68,82`), execution
spine (`core/engine.py` next-bar-open queue, `core/bracket.py:71`, `core/order.py`), cost model
(`fib_v2/config.py:81/97`). NEW — 3-bar FVG, liquidity-sweep, BOS/MSS detectors (no SMC layer
exists in bt_engine). PARTIAL — fib-OTE math (copy `_build_setup` ratio idiom), HTF bias (mirror
`RegimeTracker` structure but M15/SMA20). Multi-TF: COBRAX derives M15 bias from the M5 stream
internally (slow-path pattern `fib_v2/strategy.py:361-375`) — no 2nd live feed needed.

---

## Phase 0 — Prerequisite: EA M5 export (OUTSIDE repo · HARD GATE)
DWX EA currently exports M1/M3/M15/H1/D1 only. A `--timeframe M5` leg **silently sees zero bars**
until M5 exists (`dwx_live_provider.py:50-83` → empty frame → no trades, no crash).
- Patch `DWX_Server` EA in the MT5 terminal to add **M5** (~30-min MQL5 edit + recompile +
  reattach). EA source is NOT in the repo — it lives in MT5.
- **Verify:** `…\Common\Files\DWX\bars_XAUUSD_ecn_M5.json` appears + updates every ~5 min.
- Recompile/reattach in a low-activity window — may briefly interrupt ALL bar exports (A+D too).
- NOTE: all CODE work (Phases 1-3) can be built + BT-proven WITHOUT this; only live deploy
  (Phase 4) needs it.

## Phase 1 — Build streaming COBRAX strategy
New package `bt_engine/bt_engine/strategies/cobrax/`, mirroring `fib_v2_intraday`:
- **`config.py`** — frozen `CobraxConfig` (composition like `fib_v2_intraday/config.py`):
  `base_tf/pivot_tf=M5`, `mss_lb=3`, `fvg_min`, `ote=(0.62,0.79)`, `sweep_lb=60`, `bias_align=True`,
  `tp_mode=rr`, `tp_r=3.0`, `cost_usd`, `max_hold_bars=120` (M5=10h), `min_risk_units=0.50`.
  `LegSpec` `cobrax_long`/`cobrax_short` (unique tags), `make_cobrax_config()`.
- **`state.py`** — `CobraxState`: `PivotTracker`, confirmed swing-H/L lists, `HtfBiasTracker`,
  `pending_entries` (next-bar-open queue), `consumed_entry_keys` dedup, prev-bar cache.
  `clone()→self`, `clear_pending_entries()`.
- **`detectors.py`** — NEW streaming: 3-bar FVG (`cobrax.py:148-156`), sweep+reject (`:104-133`),
  BOS/MSS (`:116-144`), OTE-band 0.62–0.79 (`:159-178`).
- **`htf_bias.py`** — NEW `HtfBiasTracker`: closed M15 bars from the M5 stream
  (`floor("15min")`), running SMA20, `bias_for(ts)=sign(close-sma20)`. **Causal: index by M15
  CLOSE time, no interior peek** (the leak already fixed in the research engine — carry over).
- **`strategy.py`** — `CobraxStrategy(Strategy)`: `initial_state()` + `on_bar()` mirroring the
  fib_v2 base — drain `pending_entries`→finalize at `bar.open`; update trackers with just-closed
  M5 bar; detect sweep→BOS→FVG∩OTE+bias; queue match; `SL=swept extreme`, `TP=entry±rr3·R`,
  `risk_units=|entry-stop|`; wire `cost_r`/`max_hold_bars` into `Order.extra`; `validate_for_live`
  accepts M5; orders tagged `cobrax_*`.

## Phase 2 — Parity + causal audit (BLOCKING)
- **Research baseline:** dump per-trade parquet from `research/cobrax/cobrax.py` (rr3, OANDA M5
  20yr) → `research/cobrax/cobrax_trades.parquet`.
- **Streaming↔research parity** (`tests/parity/test_parity_cobrax.py`): `CobraxStrategy` via
  `run_engine`/`BTExecutionModel` vs parquet — **count ±5%, net_r ±5%, PF ±10%**.
- **BT=live 0-delta** (reuse `scripts/parity_21yr_bt_vs_live.py`): mode=bt vs mode=live.
- **known_at audit:** `sweep_ts ≤ BOS < fill`, fill = next M5 open, HTF bias from CLOSED M15 → 0 violations.

## Phase 3 — Shared-account coordination (SAFETY-CRITICAL)
- **`_leg_owns_position` (`live.py:1346-1372`)** — add explicit `cobrax` branch owning ONLY
  `cobrax`-tagged comments, BEFORE the final `return True` (unknown leg → owns EVERYTHING →
  COBRAX would hijack A+D positions). A/D branches won't grab cobrax tags.
- **M5 hold-cap** — generalize `_elapsed_m15_bars_fx` (`live.py:1389`) to a step param; adoption
  `_open_trades_from_positions` (`live.py:1494-1526`) hardcodes 48/96 M15 — COBRAX needs M5 slots
  + `max_hold_bars=120`.
- **Registry** — `register("cobrax", …)` in `registry.py::_register_builtins` (pattern `:85-96`).
- **Risk budget (REQUIRED analysis first):** live legs each size at `risk_pct` of FULL balance in
  separate processes → concurrent risk STACKS (A 2% + D 2% + COBRAX X%). Re-run a 3-leg cliff
  with live per-leg sizing (extend `research/cobrax/combined_pnl.py`/`baseline_risk.py`) → set
  COBRAX `risk_pct` off the ruin cliff — likely **≤1%**.
- **`--max-open-positions`** — raise headroom (currently 4, A+D-tuned).

## Phase 4 — Deploy (needs Phase 0)
- New NSSM `midas-live-cobrax`: `python -m bt_engine.runner.cli live --strategy cobrax
  --timeframe M5 --use-equity-sizer --start-balance 10000.0 --risk-pct <X> --max-live-lot 2.0
  --max-entry-slip-ratio 1.15 --max-open-positions <N>`. Env mirrors `midas-live-d`
  (PYTHONPATH, DWX_DIR, BT_ENGINE_DB_URL).
- **Warmup:** confirm pivots + HTF-bias converge within 200 M5 bars (~16.7h); else raise cap
  (`live.py:419`).
- **Verify live:** M5 bars flowing; a cobrax trade fires → DB + dashboard + Telegram; no A/D
  hijack; sizer risk correct.

## Phase 5 — Certify
15-pt causal audit doc + cert candidate (`docs/CERT_COBRAX_*.md`), independent hostile review,
memory update + un-freeze note.

---

## Verification (end-to-end)
1. `pytest tests/parity/test_parity_cobrax.py` — streaming↔research ±5/±10%.
2. BT=live parity → 0-delta.
3. known_at audit → 0 violations.
4. `--dry-run` on the live M5 feed → trades match BT (before real money).
5. Live smoke: first cobrax trade in DB/dashboard/Telegram tagged `cobrax`, A+D untouched.

## Honest risks
- **Minor sleeve:** ~10% R, value is smoothness not raw $ — keep COBRAX risk SMALL or it pushes
  the 3-leg account toward the ruin cliff (session's recurring lesson).
- **EA M5 patch** = external MQL5 dependency (not in repo).
- **Ownership is the #1 live hazard** — get `_leg_owns_position` right or COBRAX closes A+D trades.
- `live.py` (ownership + hold-cap) + `registry.py` edits touch the live A+D path — guard with the
  existing intraday parity tests + the new cobrax parity test.

---

## Where to start next session
1. Confirm the EA M5 patch is done (Phase 0) OR proceed with Phases 1-2 in BT (no live needed).
2. Phase 1 build order: `config.py` → `htf_bias.py` → `detectors.py` → `state.py` → `strategy.py`.
   Read `fib_v2_intraday/strategy.py`, `fib_v2/state.py`, `fib_v2/pivot_tracker.py` first as templates.
3. Full plan mirror: `~/.claude/plans/golden-wondering-book.md`. Research engine + all analyses:
   `research/cobrax/` (cobrax.py engine, additivity.py, combined_pnl.py, baseline_risk.py, freq.py,
   SWEEP_REVIEW / stage1_results.csv). Memory: `[[cobrax-ote-candidate]]`, `[[baseline-risk-cliff]]`.
