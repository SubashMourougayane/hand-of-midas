# RCA — Live A+D Legs, 9 Findings — Fresh-Eyes Confirmed — 2026-07-05

Each finding independently re-verified by a fresh RCA pass (verifiers given ONLY the
claim, not the original conclusions) against the actual code. Verdict + file:line +
reproduction + fix recorded before any code change. Deployment = two separate single-leg
NSSM services (`fib_v2_intraday_a` / `_d`), `--use-equity-sizer --start-balance 10000
--risk-pct 0.015 --max-live-lot 2.0 --max-open-positions 4`.

| ID | RCA verdict | severity | hits live now | money impact |
|----|-------------|----------|---------------|--------------|
| C1 | ✅ CONFIRMED | HIGH | YES | direct — unmanaged orphan on timeout |
| F2 | ✅ CONFIRMED | HIGH | YES | direct — mis-size after restart |
| F3 | ⚠️ DOWNGRADED (by design) | LOW | YES | NOT 2× — A-long/D-short partially hedge; per-leg 1.5% is valid. Only real residual = F2 (per-leg restart hydration). Keep individual sizers per user decision. |
| F6 | ✅ CONFIRMED (narrower) | MED-HIGH | YES (cold-fallback only) | direct — dup order if warmup throws |
| F5 | ✅ CONFIRMED | CRIT-latent | NO (composite only) | blocks F3-via-composite fix |
| F7 | ⚠️ REVISED | MED | YES | indirect — P&L UNDERSTATE (opp. sign) if partial ages off buffer |
| C2/C3/H1/H3/H4 | (parity pass) | HIGH/MED | YES | edge erosion — live < BT |
| F4/H2 | (parity pass) | HIGH | YES | edge erosion — late fill |
| F1 | ✅ (prior) | LOW | NO | none (BT-realism knobs off) |

## C1 — walker TIMEOUT never closes broker position — CONFIRMED HIGH
`bracket.py:210-225` emits `reason="TIMEOUT"` at hold cap; `engine.py:157-161` calls
on_trade_close + removes from open_trades; `live.py:573-640` on_close does DB+sizer+
reconcile, **no broker.cancel/close**. SL/TP self-close at broker (server-side from OPEN);
TIMEOUT has no broker equivalent → MT5 position runs unmanaged, DB says closed.
**Fix:** in on_close, if `oc.reason == "TIMEOUT"` and `tr.broker_ticket` and not dry_run,
`broker.cancel(ticket)` (the CLOSE| path) with slow-ack verify + warning event on fail.
SL/SL_BE/TP must NOT be double-closed.

## F2 — EquitySizer not hydrated on restart — CONFIRMED HIGH
`cli.py:114-119` builds fresh sizer at start_balance=10000 every launch; `equity_sizer.py:
98-105` hard-sets current_equity=start_balance. No hydration anywhere (docstring admits
"caller responsible", caller never does). NSSM restart mid-month → equity resets → mis-size
+ wrong month-roll baseline. **Fix:** persist sizer state on every on_trade_closed (DB row
keyed by shared account) + reload on run_live start before the engine loop.

## F3 — 2 processes = 2 sizers = ~2× risk — CONFIRMED HIGH
`live_a.ps1`/`live_d.ps1`/`install_services.ps1` run A and D as distinct services, each
own EquitySizer seeded $10k, each risks 1.5% of phantom $10k on ONE account, neither sees
the other's realized PnL. Combined ~3%. **Fix:** ONE shared DB-persisted sizer state (read-
modify-write under lock on each close, hydrated on start — also fixes F2), OR single-process
composite (needs F5 first), OR interim halve --risk-pct to 0.0075/leg.

## F6 — consumed_entry_keys in-memory, not durable across restart — CONFIRMED (narrower)
`state.py:62,69` sets are default_factory=set, never persisted/rehydrated. Only warmup
(200-bar replay) repopulates. Mitigants: setups expire by max_hold (12/24h) < 200-bar
window (~50h) so live setups normally re-consumed; `live.py:438` clears pending post-warmup.
**Genuinely uncovered:** `live.py:453-454` — if warmup THROWS, falls back to fully cold
state → all dedup lost, no DB backstop → dup-order risk. **Fix:** pre-submit DB idempotency
guard on (leg, entry_ts/setup_confirm_ts, side) in _submit_live_order — durable regardless
of warmup.

## F5 — composite warmup doesn't clear pending_entries — CONFIRMED (latent)
`combined.py:33-42` FibV2IntradayADState has no pending_entries attr → `live.py:438`
hasattr no-op → a_state/d_state pending survive → first live bar finalizes stale → dup order.
Single-leg SAFE (state IS FibV2State, cleared). **Fix:** give the composite a
`clear_pending_entries()` the runner calls (forwards to a_state/d_state), OR runner walks
sub-states. BLOCKS migrating to composite (the clean F3 fix).

## F7 — partial-TP reconcile — REVISED to MEDIUM, opposite sign
Overstatement claim REFUTED: reconcile only runs from on_close (full exit) or the
`exit_timestamp IS NOT NULL` sweep; `_ticket_still_open` defers while the remainder is open
→ `broker_reconciled_at` never armed prematurely. REAL residual (opposite): if the partial
DEAL_ENTRY_OUT ages off the ~57-deal closed_orders buffer before full close,
`find_closed_deal` len==1 returns only the final deal → **understates** gross by the partial.
**Fix:** compare summed deal volume vs DB qty; flag/retry when short (a deal is missing).

## C2/C3/H1/H3/H4/F4 — BT-live parity cluster — (verified in parity RCA pass; see audit doc)
C2 cost model (live flat $0.65 vs BT qty-scaled) → sizer equity diverges. C3 sizer-reject
(BT floors 0.01 & trades, live drops). H1 walker close-based SL vs broker intrabar touch.
H3 max_open_positions counts this-run (BT) vs whole account (live). H4 server_utc_offset=0
on inference fail shifts session gate + month-roll. F4 live fills K+1 close vs BT K+1 open.
All make LIVE ≤ BT (edge erosion / gating drift), not account-draining bugs. Quantify in the
1-week live audit; fix cost-parity + pos-cap universe.

## Fix order (money-first)
1. F3 (live 2× risk NOW) 2. C1 (orphan) 3. F2 (restart mis-size) 4. F6 (dup on cold-fallback)
5. F7 (understate) 6. C2/C3/H1/H3/H4/F4 (parity) 7. F5 (unblock composite) 8. F1 + MEDIUMs.
