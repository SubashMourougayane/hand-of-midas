# Session Handoff — 2026-07-05 (c) — Audit Fixes 2 + Dashboard Verify + ICT-extra Research

Third handoff of 2026-07-05. Prior: `SESSION_2026-07-05_SMC_CAMPAIGN.md` (12-strategy sweep),
`SESSION_2026-07-05_AUDIT_MT5.md` (100X audit + C1/H1 + MT5-truth). This doc = the
audit-fix batch (F7/F2/F5), dashboard number-verify, baseline confirmation, and the
3-more-PDFs + classic-indicator research.

## Theme
Close the remaining money-risk + restart-safety audit findings, verify every dashboard
number against MT5 truth, then exhaustively test 3 more ICT PDFs + classic indicators —
confirming S1 is the only XAU edge.

## What Happened (Chronological)
1. **Dashboard number audit vs MT5** — cross-checked Live + Trades pages against MT5
   ground truth (open_orders/closed_orders/account_info) + DB. All reconcile to the cent
   EXCEPT **OPEN RISK tile** = $10,791 (the "1-lot fantasy" `risk_units*100`, missing
   ×lots). Fixed to `|stop-entry|*lots*contract` mirroring PositionCard → ~$196. Deployed `4eb814a`.
2. **Total-return baseline** — `+$846 = equity − $10,000` hardcoded. User confirmed via MT5
   History: a +$506.31 deposit topped the account to exactly $10,000.00 on 2026-07-01 16:37.
   Baseline is broker-truth; no code change. (EA exports no balance-op history — can't
   self-derive; trust the hardcode, now verified.)
3. **F7 FIX (HIGH, real $)** — reconciler volume-completeness guard: never bank+lock a
   partial-TP until Σclosed-volume ≥ full submitted size (raw_features.qty_lots). Injected
   qty_lots on fresh open (was re-adopt only). +3 tests. This was the +$544-phantom class bug.
   Deployed `fb3e8fe`, both legs restarted, 3 positions re-adopted.
4. **F2+F5 FIX** — F2: sizer hydrates current_equity from broker balance on restart (was
   re-seeding fixed $10k across 43 restarts → mis-sized). Verified live log:
   `hydrated $10000 → $10526.77`. F5: composite A+D state now clears BOTH legs' pending
   entries after warmup (was silent no-op → latent dup-order). +10 tests. Deployed `750d35d`.
   F6 assessed INERT (self-heals via warmup), F3 confirmed not-a-bug.
5. **Fixed-1-lot combined BT** — A+D at 1.0 lot, 6.7yr: +2831 R, PF 1.63, 8/8, MAR 35 (R).
   The $1.8M figure flagged as artifact (fixed-lot ×wide-stops, not tradeable) — R is the
   honest number.
6. **S1-alone Model B $** — $5k → $29k (5.8×), maxDD −$1,406, 8/8, ~105/yr. Low frequency
   caps $, not edge quality (PF 1.72 > A+D's 1.65).
7. **3 more ICT PDFs + classic indicators** — see below. All dead/redundant.

## The Research (all rejected — S1 stands alone)
- **ICT 2022 session-range model**: built to the dot + 1728-combo mega-sweep → 2 marginal
  gate-passers (PF 1.40 < S1's 1.72), knife-edge delay+1 → phantom. NY-only/4R best quality
  but 82/yr (fails freq). REJECT.
- **S1 session-widening**: killzone NY2-11 already optimal; all widenings worse. REJECT.
- **Classic batch** (VWAP / regression-trendline / SMA-cross): FIRST RUN had a same-bar
  look-ahead (market fill at bar-i open knowing close[i]) → phantom +66,000R / PF 4.79.
  **Big-numbers mandate caught it.** Fixed (fill at bar i+1) → ALL PF < 1.0, dead.
  S1∧belowVWAP looked good (PF 1.80) but delay+1 → 0.89 = phantom + redundant. REJECT.

## What's Live
- Branch `fib-v2-clean`, tip **`c5d03785e`** (research; live-code tip = `750d35d`).
- VPS: midas-dashboard on `4eb814a`+ (HEALTH 200), midas-live-a/d RUNNING on `750d35d`,
  3 positions re-adopted (2118599832 L, 2125844421 S, 2126588609 L), sizer hydrated to real balance.
- All money-risk + restart-safety audit findings CLOSED (C1/H1/F7/F2/F5). F4/C2/C3/H3/H4
  parity + MEDIUM dashboard logs remain (non-money, deferred).

## Commits This Session (this batch)
| SHA | Description |
|-----|-------------|
| 4eb814a17 | Live OPEN RISK tile real-$ fix |
| fb3e8fe4b | FIX F7 partial-TP volume guard |
| 750d35d54 | FIX F2+F5 sizer hydration + composite pending clear |
| c5d03785e | Research: 3 ICT PDFs + classics — nothing beats S1 |

## Outstanding
- **MEDIUM**: F4/C2/C3/H3/H4 BT-live parity (fill timing, cost model, SL touch, pos-cap, tz).
- **MEDIUM**: dashboard realized-today ORDER BY, aged-off MT5 fallback (task #250).
- **Deferred research**: HMM regime filter (only untested idea; heavier build).
- **Pending**: fresh full 100X re-audit now C1/H1/F2/F5/F7 landed; 1-week live A+D workhorse watch.
- **S1 still PARKED** — not ported to bt_engine, awaits 1-week live A+D audit before deploying as sleeve.

## Decisions
- OPEN RISK = current downside (`|stop-entry|*lots`), so breakeven-moved stops read $0.
- $10k baseline kept (broker-verified via +506.31 deposit); not wired to EA (no balance-op export).
- Sizer hydrates from **balance** (realized-only), never equity (no MTM peek).
- Deploy money-risk fixes immediately in the quiet weekend window; defer parity/cosmetic.
- ALL 4 PDFs + VWAP/trend/SMA now in the graveyard — stop re-testing these families.

## What's Next
Fresh 100X re-audit → 1-week live workhorse watch → then decide S1 sleeve. If more edge
wanted: S1 on more symbols (SPX/EUR), or build HMM regime filter. NOT more single-symbol
indicator sweeps (exhausted).

## Numbers to Remember
- A+D 1-lot BT: +2831 R, PF 1.63, 8/8, 8590 trades. S1 Model-B: $29k/5.8×.
- ICT2022 sweep: 2/1728 pass (phantom). Classic batch: all PF<1.0 post-fix.
- Look-ahead bug: phantom +66,000R → caught → fixed. Sizer hydrated $10000→$10526.77.
- Deposit: +$506.31 → $10,000.00 baseline (2026-07-01 16:37, broker-verified).
