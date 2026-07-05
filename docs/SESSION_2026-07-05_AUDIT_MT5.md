# Session Handoff — 2026-07-05 (A+D 100X Audit + MT5 Single-Source-of-Truth)

## Theme
Full deterministic 100X audit of the live A+D legs, RCA + fix of the two shipping bugs (C1/H1), and a cutover of dashboard + engine to MT5 as the single source of truth for open/closed status and floating P&L. Ends with the ticket 2125574587 phantom-$544 reconciliation.

## What Happened (Chronological)
1. **12-strategy SMC/ICT campaign** (committed `2f61e22c2`, doc `SESSION_2026-07-05_SMC_CAMPAIGN.md`): quantized the SMC/ICT PDF to the dot, built + swept 12 strategies. Only **S1 (sweep→CHoCH→OTE long)** clears the gate (PF 1.43–1.72, MAR 2.0–2.9, 8/8 yrs). All other 11 + all shorts fail. Confirmed by 3 independent sweeps. No tradeable short edge exists to pair with S1.
2. **100X audit of live A+D** (`1990c8c92`): triple-run bit-identical determinism proof — A=3503 trades/+1497.93R (SHA 07703c6a), D=5695/+1636.83R (SHA 9252f11a). Strategy/decision layer is PROVEN deterministic + causal. Surfaced 9 execution/state findings.
3. **RCA fresh-eyes** (`3f8858cfa`, doc `RCA_AD_LIVE_2026-07-05.md`): confirmed each of the 9 really exists; classified which lose money.
4. **Fixed C1** (`23b4e4d23`): walker TIMEOUT exit never closed the broker position → orphan + phantom P&L. Now `on_close` closes broker on `reason=="TIMEOUT"`.
5. **Fixed H1** (`6651a1e11`): broker-side intrabar SL/TP close wasn't detected → engine managed a ghost. Added `on_broker_closed_check` engine hook (live-only; None in BT preserves determinism).
6. **MT5 single source of truth** (`76fefcadf` → `1265dc556`): shared reader `broker_state.py`; dashboard Trades page + Live cockpit key off `broker_open` (MT5 truth); floating P&L via account-wide WS socket; heartbeat re-broadcast so a fresh client shows floating fast.
7. **Deployed + verified** on VPS: 3 open positions re-adopted, dashboard open tickets == broker tickets.
8. **Ticket 2125574587 fix**: MT5 net was +$5.04 (SL: +73.80 partial, −68.76 remainder) but a SUPERSEDED DB fragment carried phantom `partial_booked_usd=73.80` → dashboard showed +$544. Corrected SL row to broker_net_usd=+5.04/reason SL, neutralized the phantom row. Dedup now picks the SL row.
9. **10s update delay** diagnosed = 15s WS heartbeat → changed to 3s (`4477b82e1`, `ab4a54a6b`). Deployed.

## What's Live
- Branch `fib-v2-clean`, tip **`ab4a54a6b`**.
- VPS (Contabo, Windows RDP-only): `midas-dashboard` on ab4a54a (HEALTH 200), `midas-live-a` + `midas-live-d` RUNNING, 3 open positions untouched (2118599832 L, 2125844421 S, 2126588609 L).
- C1/H1/MT5-truth all live + verified.

## Commits This Session
| SHA | Description |
|-----|-------------|
| 2f61e22c2 | SMC/ICT 12-strategy campaign (only S1 clears) |
| 1990c8c92 | 100X audit: determinism proven, 9 findings |
| 3f8858cfa | RCA fresh-eyes confirmation of 9 findings |
| 23b4e4d23 | FIX C1: close broker on walker TIMEOUT |
| 6651a1e11 | FIX H1: detect broker-side intrabar closes |
| 76fefcadf | MT5 single-source-of-truth reader + Option A |
| 5f8f2d288 | Trades page MT5-truth broker_open |
| ce28289cb | Trades page floating P&L on broker-open rows |
| 1265dc556 | Trades page floating via account-wide WS socket |
| 4477b82e1 | WS heartbeat re-broadcast positions_live |
| ab4a54a6b | WS heartbeat 15s→3s |

## Outstanding Issues
- **HIGH — F7**: partial-TP reconcile can bank ONLY the partial deal + lock it → P&L overstatement (this caused the 2125574587 phantom). Code fix pending: validate deal volume before banking. Real money risk. Fix FIRST.
- **MEDIUM — F2**: EquitySizer state not hydrated from DB/broker on live restart.
- **MEDIUM — F5**: composite a_plus_d warmup doesn't clear pending_entries (latent dup-order).
- **MEDIUM — F6**: consumed_entry_keys in-memory only, not rehydrated on restart (dedup gap).
- **MEDIUM — parity** (C2/C3/H3/H4/F4): cost model, sizer-reject, SL touch, pos-cap, tz/fill-timing BT-live divergences. H1 of this group already fixed.
- **LOW — F1**: hash() non-determinism, BT-realism knobs only, gated off in production.
- **NOT A BUG — F3**: A+D = 2 sizers by design (per-leg 1.5%, legs hedge). Closed.
- Pending: 1-week live A+D workhorse audit; fresh 100X re-audit after F7/F2/F5/F6.

## Decisions Made
- **MT5 is the single source of truth** (user mandate). A corrupt/missing `open_orders.json` read returns **None** (trust DB), NEVER an empty set — never blank the board / mark all closed.
- **F3 kept as-is**: user explicitly wants per-leg individual sizers.
- Only fix the two shipping bugs (C1/H1) + MT5-truth for now; defer the rest until after live verification.

## What's Next
1. Fix F7 (validate deal volume before banking partial) — highest $ risk.
2. F2/F5/F6 restart-safety trio.
3. Fresh full 100X re-audit.
4. Watch the 1-week live workhorse.

## File Inventory
- New: `bt_engine/bt_engine/data/broker_state.py`, `docs/RCA_AD_LIVE_2026-07-05.md`, `docs/AUDIT_100X_AD_2026-07-05.md`, `bt_engine/scripts/audit_100x_determinism.py`, `research/smc_campaign/*` + `CAMPAIGN_FINDINGS.md`.
- Modified: `bt_engine/bt_engine/runner/live.py`, `core/engine.py`, `dashboard_backend/app/routers/{runs,live}.py`, `dashboard_backend/app/ws/price_stream.py`, `dashboard/src/pages/TradesPage.tsx`, `dashboard/src/lib/api.ts`.

## Numbers to Remember
- Determinism: A 3503 trades / +1497.93R / SHA 07703c6a; D 5695 / +1636.83R / SHA 9252f11a.
- Ticket 2125574587: true net **+$5.04** (SL), was showing +$544.
- WS heartbeat: 15s → 3s.
- S1 (only SMC survivor): PF 1.43–1.72, MAR 2.0–2.9, 8/8 yrs.
