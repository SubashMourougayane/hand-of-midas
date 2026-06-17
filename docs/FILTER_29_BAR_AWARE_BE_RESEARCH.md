# Filter #29 — Bar-Aware BE Check

**Status:** RESEARCH / NOT SHIPPED. Awaiting BT validation per `[[project-filter-sweep-workflow]]`.
**Triggered by:** `docs/trades/GD-AL-4af2d62d.md` (Gold Macro SHORT, BE never armed despite price reaching 60.8% to TP, net −$160.32 vs +$3.60 if BE had worked).

---

## The bug Filter #29 fixes

**Current BE check** (`backend/scanner/live_engine.py:526–582` and mirrors in 3 other systems):

1. Per-minute APScheduler tick fires `position_monitor_job()` → `check_alpha_sweep_breakeven()`
2. Function reads `get_current_price()` — single live MT5 tick at moment of call
3. Compares ask (SHORT) or bid (LONG) to `target_50 = entry ± (TP − entry) × 0.5`
4. If trigger hit → modify SL to entry ± $0.30, journal `BREAK_EVEN`

**The gap:** if price wicks below `target_50` for less than 60 seconds and recovers before the next per-minute tick, **the BE check never sees it**. The trigger was breached — but only at moments between scheduler ticks. Single-tick wicks bypass BE entirely.

**Live evidence (GD-AL-4af2d62d):**
- M3 bar `2026.06.17 17:45:00` server (15:45 UTC): low=$4331.09, high=$4355.38
- BE 50% trigger ask = $4334.21; bar low ≈ ask $4331.19 = $3.02 below trigger
- 0 `BREAK_EVEN` journal events for this trade across its full ~89min lifetime
- Trade then reversed within the same M3 bar to $4355.38 (+$24.29 from low, retracing 84% of the down-spike)

The dip+recover happened inside one 3-minute M3 bar. Position_monitor's per-minute tick caught the *recovered* price (post-spike), not the trigger-breaching dip.

---

## The fix proposal

**Bar-aware BE check.** In addition to the live tick comparison, also check the **lowest bid** (for SHORT) or **highest ask** (for LONG) of the most-recently-completed M3 bar since entry. If that extreme breached the trigger — **arm BE retroactively**.

```python
# SHORT branch addition (live_engine.py:568+)
target_50 = entry - (entry - tp) * 0.5
current_ask = price["ask"]

# Existing: live-tick check
if current_ask <= target_50:
    arm_be(); return

# NEW (Filter #29): bar-aware lookback
last_bar_low = get_last_completed_m3_bar_low(instrument, since=entry_time)
spread_adj = current_ask - price["bid"]  # ~$0.10 for XAUUSD
if last_bar_low + spread_adj <= target_50:
    _log.info("be_triggered_via_bar_wick", ...)
    arm_be(reason="bar_wick"); return
```

This catches single-tick wicks that the per-minute snapshot would miss.

**Source of last_bar_low:** read from VPS DWX `bars_XAUUSD_ecn_M3.json` (already exists, the EA writes M3 bars on close). One file read per BE check tick. Negligible overhead.

---

## Variants to BT-sweep (per `project-filter-sweep-workflow`)

| Variant | Lookback | Spread adj | Since |
|---|---|---|---|
| 29-A | last 1 M3 bar | bar_low + spread | since entry |
| 29-B | last 2 M3 bars | bar_low + spread | since entry |
| 29-C | last 3 M3 bars | bar_low + spread | since entry |
| 29-D | last 5 M3 bars | bar_low + spread | since entry |
| 29-E | EVERY bar since entry | min(bar_low) + spread | since entry |
| 29-F | last 1 M3 bar | bar_low (NO spread adj — aggressive) | since entry |
| baseline | (current production — live-tick only) | — | — |

**Per system:** Gold Macro / Gold Micro / Oil Macro / Oil Micro = 7 variants × 4 systems = **28 BT runs.**

**Hypothesis:** 29-E (every bar since entry) catches the most BE arms but may incorrectly arm during transient spikes that don't reflect closed prices. 29-A is safest. Sweep will reveal the bias/variance tradeoff.

---

## Concrete metrics to measure pre/post

For each variant, BT outputs:
1. **PF** (current vs new)
2. **Win rate** (current vs new)
3. **Net P&L total** (21yr, $5k/yr reset)
4. **NEW: BE_ARMED_RATE** (% trades where BE armed) — current production vs variant
5. **NEW: AVG_FINAL_PNL_FOR_REVERSAL_TRADES** — trades that hit BE then reversed → currently $0.30 avg vs current production "BE never armed" loss
6. **AVG_DRAWDOWN_DURING_BE_PROTECTED_TRADES** — sanity check that BE didn't fire too early

If 29-A or 29-B improves PF + reduces drawdown without hurting win rate → ship per-system per `[[feedback-selective-ship-pattern]]`.

---

## Risk considerations

1. **False-positive BE arms** — if M3 bar low is a wick that retraces immediately and price continues against position, BE could fire too early on a still-valid setup that would have continued favorably. Backtest will reveal frequency.
2. **Looking-ahead bias in BT** — must use bar's CLOSED low, not in-progress bar high/low. Variant 29-A's "last 1 M3 bar" must mean **the most recently CLOSED bar**, not the in-progress one.
3. **Sub-M3 wicks** — if the wick is sub-3-minute (sub-bar level), even M3-aware check misses it. Would need M1 or tick-level. Out of scope for Filter #29.
4. **Performance** — file read per BE check tick = trivial. Don't optimize prematurely.
5. **Live↔BT parity** — must verify parity test still passes per `[[project-parity-harness]]` before/after.

---

## Plan of action (when work resumes)

**Phase 1 — instrumentation (NOT in Filter #29 scope, but blocks meaningful BT):**
- Add `BE_PROGRESS` journal events on every position_monitor tick (current `_log.debug` is too quiet for live observability)
- Add `BE_ARMED_VIA` field to `BREAK_EVEN` journal context: `live_tick` | `bar_wick` (will distinguish current vs Filter #29 path post-ship)
- 1-week production data with these in place → see how many wicks the current production missed

**Phase 2 — BT sweep:**
- Branch: `filter/29-bar-aware-be`
- Implement variants in `backend{,-micro,-oil,-oil-micro}/backtest/engine.py` (BE check is duplicated across 4 backtest engines)
- Run sweep across all 4 systems × 7 variants
- Output: `scripts/output/filter_29_results.jsonl`
- Compare to baseline; rank by PF improvement + win-rate stability

**Phase 3 — selective ship per system:**
- For each system independently: ship best variant or stash
- Live wiring is straightforward (live engine has same BE function shape as BT)
- Watch first 5–10 BE arms post-ship; verify `BE_ARMED_VIA = "bar_wick"` is firing for trades the previous code missed

---

## Cross-references

- `docs/trades/GD-AL-4af2d62d.md` — the trigger-event postmortem
- `[[project-filter-sweep-workflow]]` — branch → BT pre/post → user sign-off → ship-or-stash protocol
- `[[feedback-selective-ship-pattern]]` — per-system ship decisions
- `[[project-parity-harness]]` — must pass before/after
- `backend/scanner/live_engine.py:531–582` — current BE check (Gold Macro canonical)
- `backend-micro/scanner/live_engine.py`, `backend-oil/scanner/live_engine.py`, `backend-oil-micro/scanner/live_engine.py` — mirrors

---

**Lock-in date:** 2026-06-17. **Next action:** Phase 1 instrumentation BEFORE BT (need observability data to validate the snapshot-miss hypothesis is the right framing).
