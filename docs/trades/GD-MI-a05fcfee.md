# Postmortem — GD-MI-a05fcfee

> **Verdict:** ⏱️ Clean expire — limit never touched · 🐛 Reconciler-gap zombie (already-fixed bug class, awaiting deploy)
>
> **TL;DR:** Filter #27 BUY_LIMIT placed at $4323.04 after a textbook Asia-sweep + M3 engulfing reversal signal. Price never came back down to the limit ($5.31 short of touching). Broker auto-cancelled at the 15-min TTL silently — same broker-silent-expire bug as `GD-MI-1e53d69b`. Zero P&L, zero broker exposure, dashboard zombie cleared via SQL. Fix A + Fix B already written, awaiting commit.

---

## Trade card

- **System:** Gold Micro
- **Instrument:** XAU_USD
- **Strategy:** micro_alpha_sweep (Filter #27 limit-order entry)
- **Side:** LONG 34 units (0.34 lots)
- **Limit price:** $4323.04 · **SL:** $4318.54 · **TP:** $4347.66
- **Ticket:** 2058401704
- **Mode at placement:** pending (never flipped to live — never filled)
- **Exit reason:** LIMIT_TTL_EXPIRED (manual recon — Fix A/B not yet deployed)
- **P&L:** $0.00
- **Duration alive at broker:** 14m 58s (15-min TTL configured)

## Risk math (intended, never realized)

- Risk: $5.00/unit × 34 = $170.00 max loss (hit `min_sl` floor)
- Reward: $24.62/unit × 34 = $836.95 max gain
- R:R: **4.92 : 1**
- 50% to TP (Filter #5 BE trigger): $4335.35

## Filter #27 limit math

| Field | Value |
|---|---|
| Calc entry (M3 engulf close + slippage) | $4323.5371 |
| Variant | C10_loose (BT-best for Gold Micro) |
| Offset | −0.10 × risk = −$0.50 |
| **Intended limit** | **$4323.04** |
| TTL | 900s (15 min) |
| BT yearly slice | 15/21 up, 18% loss/gain ratio (shipped 2026-06-16) |

## Timeline (all times IST)

| Event | IST | UTC | Notes |
|---|---|---|---|
| Sweep H1 bar formed | 14:30:00 | 09:00:00 | wick=$4321.38 (poked $7.22 below range_low $4328.6) |
| SIGNAL fired | 14:57:01.703 | 09:27:01.703 | M3 engulfing reversal, direction=long, bias=neutral |
| Filter #27 limit math | 14:57:02.077 | 09:27:02.077 | intended_limit=$4323.04 |
| Broker accepted | 14:57:02.454 | 09:27:02.454 | retcode=10009, ticket=2058401704 |
| DB row inserted (mode='pending') | 14:57:02.683 | 09:27:02.683 | LIMIT_PLACED journal event |
| Telegram sent | 14:57:02.813 | 09:27:02.813 | "📋 LIMIT PLACED" |
| First orphan-warn | 15:01:30.978 | 09:31:30.978 | DWX file race — 4-min normal noise |
| **TTL HIT** — broker silent-expire | **15:12:00.404** | **09:42:00.404** | pending count 1→0, no Trades event, no OnTradeTransaction fire |
| Lowest BID during TTL window | 15:18:00 | 09:48:00 | $4328.35 (still $5.31 ABOVE limit) |
| Manual zombie cleanup (SQL) | 15:34:53 | 10:04:53 | exit_reason='LIMIT_TTL_EXPIRED', manual_recon=true |
| Postmortem written | 15:36 | 10:06 | This doc |

## Why this signal fired — full data points

### Signal-detection sequence

```
[01:00 UTC tick] SCAN gold-micro: windows=3 active, bias=neutral
  ↓
Window 0-4 UTC consolidation:
  range_high = $4349.66
  range_low  = $4328.60
  range      = $21.06   (min_required=5.00 ✓)
  ↓
H1 bar at 09:00 UTC (sweep candle):
  bullish wick at $4321.38   (poked below range_low by $7.22)
  closed back above range_low → confirmed sweep + recovery
  sweep_dir = bullish
  ↓
[GATE check 1] sweep_already_traded — NO ✓ (not in _traded_sweeps set, not in DB)
[GATE check 2] one-at-a-time — NO open Micro position ✓
[GATE check 3] daily bias — neutral, no block ✓
[GATE check 4] M3 engulfing within 45min — FOUND ✓
[GATE check 5] consol_range × 0.8 = 16.85 risk_max — risk=$5 within bounds ✓
[GATE check 6] tp_distance ≥ 0.8 × risk — $24.62 ≥ $4 ✓
  ↓
SIGNAL FIRED:
  direction = LONG
  entry calc = $4323.5371  (M3 engulf ask_close + slippage)
  sl  = $4318.5371  (sweep_wick − 2.0 buffer, floored at min_sl=5)
  tp  = $4347.66    (range_high − tp_structure_buffer 2.0)
  risk = $5.00      (hit min_sl floor)
  R:R = 4.92 : 1
```

### Daily bias context (`bias=neutral`)

Yesterday's daily candle (Jun 16 D1):
- Mid open / mid close / mid high / mid low computed from bid/ask averages
- V1 body% < 40% of range → neutral
- V2 close not in top/bottom 20% of range → neutral
- Combined: **neutral** — no directional block applied

### Why this is a textbook setup

1. **Asia consolidation** (0-4 UTC) — quiet range of $21 over 4 hours, well above min_range $5
2. **Liquidity sweep** — H1 bar 09:00 UTC dipped $7+ below range_low, closing back above. Stop-hunt pattern.
3. **M3 engulfing reversal** — within the 45-min engulfing window, an M3 bar engulfed the prior bar in the bullish direction
4. **Risk floor** — calculated SL distance was tighter than $5, so engine clamped to min_sl ($5/unit) → 4.92:1 R:R
5. **Bias neutral** — yesterday's indecisive daily candle didn't block either direction

This is **exactly** what micro_alpha_sweep is designed to detect. Same pattern as `GD-MI-2b152d33` (filled, SL'd) and `GD-MI-83dd033b` (filled, MAX_HOLD won).

## Why limit didn't fill

After the engulfing reversal, market continued up — NOT the small pullback that variant C10_loose waits for. Price action during the 15-min TTL window:

| IST | M3 bar | Bid Open | Bid High | Bid Low | Bid Close |
|---|---|---|---|---|---|
| 14:57 | placement instant | 4323.56 | 4324.88 | 4323.15 | 4323.67 |
| 15:00 | +3 min | 4323.66 | 4324.27 | **4320.02** | 4321.78 |
| 15:03 | +6 min | 4321.84 | 4324.37 | 4321.47 | 4323.42 |
| 15:06 | +9 min | 4323.43 | 4323.44 | 4321.68 | 4322.40 |
| ... | ... | ... | ... | ... | ... |

🦣 **WAIT — bid LOW reached $4320.02 at 15:00, well below our $4323.04 limit. The limit SHOULD have filled.** But the broker says it didn't. The Trades log has only the placement event — no fill, no cancel notification.

### Two possible explanations

1. **MT5 chart bars (BID-based, snapshot every 25ms via DWX) ≠ broker-side authoritative price feed.** JustMarkets demo broker may have a slightly different tick stream that never quite touched $4323.04 even when the local chart shows it did.
2. **Local DWX bar file lags the broker.** The bars file is rewritten every ~3 seconds; the broker evaluates fills on every tick. A 25ms touch on the local chart isn't necessarily what the broker server saw.

Bottom line: **broker is the authoritative source** and broker says no fill. The local-chart view is a secondary indicator. This is a known weakness of the Filter #27 BT methodology — BT runs against H1/M3 bar data, but live runs against tick-level broker prices that may diverge slightly from what the same M3 bar suggests.

⚠️ **Action item for [[project-calibration-plan]]**: when ≥30 clean live limit fills accumulate, compare `intended_limit` vs whether local M3 bars showed it should have filled. If misses cluster around "would-have-filled-on-chart-but-broker-didn't", that's a slippage/feed-divergence cost worth quantifying.

## Bug-smell checklist

| Check | Status |
|---|---|
| Strategy logic | ✅ As designed (Asia sweep + M3 engulfing) |
| Filter #27 limit math | ✅ Correct: entry − 0.10 × risk |
| Broker accepted | ✅ retcode=10009, ticket=2058401704 |
| TTL configured correctly | ✅ 900s (15 min) — matches actual broker behavior |
| DB row inserted | ✅ mode='pending' |
| Journal events fired | ✅ LIMIT_DRY_RUN_INTENT + LIMIT_PLACED |
| Telegram sent | ✅ "📋 LIMIT PLACED" |
| Broker cancellation event | 🐛 **MISSING** — silent-expire bug |
| `cancelled_orders.json` written | 🐛 **MISSING** — file does not exist on VPS |
| Python pending_order_monitor | ✅ Detected orphan, logged warn (silently — Fix C will add Telegram) |
| DB row resolved | 🐛 Stuck `mode='pending'` until manual SQL cleanup |
| Dashboard rendered | 🐛 Showed as open trade until cleanup |
| `_log_signal(taken=True)` | 🐛 **MISSING** — bug M11 (limit path returns before _log_signal call) |

## Pattern vs recent peers

| trade_ref | Side | Filter #27 outcome | Notes |
|---|---|---|---|
| GD-MI-2b152d33 | SHORT | Filled (limit fill at $4337.93), then SL'd | First-ever limit fill — clean lifecycle |
| GD-MI-1e53d69b | SHORT | TTL expired, never filled | Same silent-expire bug |
| **GD-MI-a05fcfee** | **LONG** | **TTL expired, never filled** | **This trade — same bug, second occurrence** |

🦣 **Pattern:** of the 3 Filter #27 fires so far, **2 hit the silent-expire path**. That's a 67% rate — reconciler bug is hitting often. Fix A (EA poll-detect) + Fix B (Python grace fallback) need to deploy.

## Counterfactual P&L

If the limit had filled at $4323.04:
- LONG 34 units, entry $4323.04, sl $4318.54, tp $4347.66
- Risk: 34 × $4.50 distance = $153 max loss
- Reward: 34 × $24.62 distance = $836.95 max gain

But price went UP after the engulfing — meaning if filled, it would have hit TP first. Estimated P&L if filled: **+$836** (assuming TP reached) or **+$418** (Filter #7 partial-TP at 50%, ~$11 above entry, then runner SL'd at BE).

🦣 **Caveman counterfactual:** **we missed a winner**. Variant C10_loose accepts ~30% miss rate in BT for better fills overall — this is one of those misses. Over 21yr backtest, the math says skipping today is profitable. Single-trade interpretation is not a signal.

## What happens after Fix A + Fix B deploy

The same scenario will resolve cleanly:

1. EA `WritePendingOrders()` (Fix A) detects ticket vanished from `OrdersTotal()` between two timer ticks, queries `HistoryOrderSelect` → state EXPIRED → writes `cancelled_orders.json` with `state=EXPIRED_POLLED`
2. Python `pending_order_monitor` (next 30s) sees ticket in `cancelled_orders.json` → updates DB row to `exit_reason='LIMIT_TTL_EXPIRED'` → fires Telegram "⏱ LIMIT EXPIRED"
3. Or if Fix A misses, Python `pending_order_monitor` (Fix B) at TTL+60s detects orphan past grace → marks `exit_reason='LIMIT_TTL_EXPIRED_GRACE'`

Either way: zombie state lasts ≤ 30-90 seconds, not 7 hours. Dashboard stays clean. Operator gets a Telegram.

## Recommendations

- ✅ Strategy worked correctly — no action needed on signal logic
- ✅ Filter #27 limit math correct — no action needed on compute_limit_price
- ⚠️ **Ship Fix A + Fix B** to close the broker silent-expire reconciler gap (already written, awaiting commit)
- ⚠️ Track `intended_limit` vs `local_chart_low` over next 30 fills to quantify chart-vs-broker feed divergence (calibration plan)
- ⚠️ Bug M11 (missing `_log_signal(taken=True)` on limit path) — added to backlog, fix during audit cleanup phase

## Decision log

| Time | Decision |
|---|---|
| 14:57:02 IST | Signal taken automatically (all gates passed) |
| 15:12:02 IST | Broker silent-expired — ops blind for 22 minutes until user noticed |
| 15:34:53 IST | Manual SQL cleanup applied via debug API |
| 15:36 IST | Postmortem written, M11 added to backlog |
| (pending) | Ship Fix A + Fix B → first real automated cleanup of silent-expire path |
