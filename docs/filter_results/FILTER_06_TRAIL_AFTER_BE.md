# Filter #6 — Trailing SL after BE (high-water-mark)

**Status:** ✅ SHIPPED selectively (Oil Macro only). Gold Macro / Gold Micro / Oil Micro EXCLUDED.

**Branch:** `filter-06-trail-after-be` → merged into `midas-deploy` 2026-06-13

## Hypothesis

After BE arms, instead of leaving SL parked at entry+1c, **trail SL upward**
using a high-water-mark of bar high (longs) / low (shorts) since BE armed.
SL only ratchets in favorable direction — never moves backward.

`new_sl = entry + (hwm - entry) × trail_after_be_pct`  (longs)
`new_sl = entry - (entry - hwm) × trail_after_be_pct`  (shorts)

Hypothesis: catches partial wins on trades that run far toward TP then reverse,
which currently scratch out at BE.

Tradeoff: trail closer to current price = more trades stopped out before TP.
Some clean TPs sacrificed.

## Implementation

Per-system `trail_after_be_pct` config key. **Only Oil Macro gets the key set
(0.50)**; the other 3 systems' configs don't have the key, engines fall back
to `0.0` (legacy behavior — no trail).

| Path | Edit |
|---|---|
| `backend-oil/config.py` | Add `"trail_after_be_pct": 0.50` |
| `backend/config.py` | Unchanged (no key, default 0.0) |
| `backend-micro/config.py` | Unchanged |
| `backend-oil-micro/config.py` | Unchanged |
| `backend/execution/fill_model.py` | `execute_trade` accepts `trail_after_be_pct=0.0` kwarg, implements HWM trail logic |
| `backend-oil/execution/fill_model.py` | Same (Oil Macro's own copy) |
| `backend-oil-micro/backtest/engine.py` | `_execute_trade` accepts `trail_after_be_pct=0.0`, implements trail |
| `backend/backtest/engine.py` | Forwards kwarg from `run_backtest` |
| `backend-micro/backtest/engine.py` | Reads `MICRO_ALPHA_SWEEP.get("trail_after_be_pct", 0.0)` |
| `backend-oil/backtest/engine.py` | Reads `ALPHA_SWEEP.get("trail_after_be_pct", 0.0)` |
| `backend-oil-micro/backtest/engine.py` | Reads `MICRO_ALPHA_SWEEP.get("trail_after_be_pct", 0.0)` |
| `backend-oil/scanner/live_engine.py` | New: `_post_be_hwm` dict + post-BE trail check in `check_alpha_sweep_breakeven` + cleanup on exit + cleanup on MAX_HOLD |

## Live engine implementation notes

The Oil Macro live BE-monitor (`check_alpha_sweep_breakeven`) runs once per
scheduler poll (~30s). On each poll for an open Oil Macro trade post-BE-armed:

1. Update `_post_be_hwm[oid]` with current bid (LONG) or current ask (SHORT)
2. Compute `proposed_sl = entry + (hwm - entry) × 0.5`
3. If `proposed_sl > current sl + 0.005` (0.5c minimum delta to avoid noisy modifies),
   call `modify_stop_loss(oid, proposed_sl)`
4. Cap at `tp - 0.05` (avoid SL >= TP race)
5. On EXIT_FILLED or MAX_HOLD, clear `_post_be_hwm[oid]`

Live → BT divergence risk: live updates HWM with **mid-bar tick prices** every 30s,
BT updates HWM with **completed bar high/low** every M3. Live's HWM may track
slightly higher peaks than BT can see. We accept this drift — it's directionally
neutral (live captures tighter trail = same direction as BT's trail intent).

## BT 21-yr pre/post — full

Baseline = post-Filter-#5 (all 4 systems with their respective be_trigger_pct).
Filter ON adds `trail_after_be_pct=0.5`.

| System | Baseline (no trail) | Filter (trail=0.5) | Δ Trades | Δ WR | Δ PF | Δ P&L | $ Δ |
|---|---|---|---:|---:|---:|---:|---:|
| Gold Macro | PF 2.56, $346k | PF 2.54, $341k | 0 | 0.0pp | -0.02 | -1.5% | -$5.3k |
| Gold Micro | PF 2.77, $252k | PF 2.70, $249k | +23 | +0.5pp | -0.07 | -1.4% | -$3.5k |
| Oil Macro | PF 2.93, $701k | **PF 2.96, $781k** | **+31** | **+0.6pp** | **+0.03** | **+11.5%** | **+$80,245** |
| Oil Micro | PF 3.10, $2.13M | PF 2.87, $2.13M | +82 | +0.1pp | -0.23 | +0.1% | +$1.9k |

**Only Oil Macro passes ship criteria** (PF ↑ AND material P&L ↑).
- Gold Macro / Gold Micro: PF and P&L both worse → EXCLUDED
- Oil Micro: P&L flat but PF drops 0.23 (worse capital efficiency for same outcome) → EXCLUDED

## Why Oil Macro works (intuition)

Oil Macro has the longest hold time and most directional behavior of the 4 systems.
Trades that arm BE typically continue toward TP with relatively small pullbacks
relative to TP distance. Trail captures real continuation gains without often
getting stopped out on micro-pullbacks.

The other 3 systems have faster, choppier trade dynamics — pullbacks within bars
are large relative to TP distance, so trail catches more whipsaws than continuations.

## Live signal-gen impact

**N/A** — fill-side filter, signals unchanged. Parity audit pre-#6 still applies.

## Risks

- **Live ↔ BT timing variance** in HWM updates. Live polls every 30s with current
  price; BT updates per M3 bar. Empirically the trail SL trajectory should be similar
  but not identical. If the next live Oil Macro trade with trail-armed SL behaves
  unexpectedly, the postmortem `trade-postmortem` skill will catch it.
- **Modify-rate impact.** Live now issues `modify_stop_loss()` calls during the
  trail phase. Each MODIFY is a broker round-trip. Expected rate: ~1 modify per
  bar-after-BE on a trending trade. Within JM rate limits (1 req/sec). Should be fine.
- **Whipsaw on volatile bars.** A bar that spikes high (raising HWM, raising trail SL)
  then closes low could trip the trail SL same-bar. The fill model's order-of-checks
  (gap-through SL → TP → SL → BE → trail) protects this — SL check uses the OLD SL,
  trail update happens AFTER SL check. So no phantom-trail-then-stop within same bar.

## Recommendation

✅ **Ship to Oil Macro.** Aggregate impact: **+$80,245 / 21yr (+$3.8k/yr).**

Other 3 systems excluded. Their `trail_after_be_pct` defaults to 0.0 via
`.get("trail_after_be_pct", 0.0)` in their respective engines.

## Files changed

- `backend-oil/config.py` (add trail key)
- `backend/execution/fill_model.py` (HWM trail in execute_trade)
- `backend-oil/execution/fill_model.py` (same)
- `backend-oil-micro/backtest/engine.py` (HWM trail in _execute_trade + run_backtest forward)
- `backend/backtest/engine.py` (run_backtest forwards kwarg)
- `backend-micro/backtest/engine.py` (read default from config)
- `backend-oil/backtest/engine.py` (read default from config)
- `backend-oil/scanner/live_engine.py` (`_post_be_hwm` + post-BE trail in BE monitor + cleanup hooks)

## Related artifacts

- `scripts/run_filter_06.py` — pre/post benchmark
- `scripts/validate_filter_06.py` — selective ship verification
- `scripts/output/filter_06_results.json` — raw pre/post numbers
- `scripts/output/filter_06_validation.json` — selective ship match check
