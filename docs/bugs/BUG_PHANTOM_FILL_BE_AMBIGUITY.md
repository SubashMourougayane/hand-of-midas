# BUG: Phantom Fill Bug (BE-Ambiguity Variant)

**Discovered**: June 10, 2026 ~14:00 IST  
**Severity**: HIGH — DB reports wrong P&L, equity tracking drifts from broker  
**Affected**: Gold Micro, Oil Micro (both have the same `check_open_positions` fallback path)  
**First observed trade**: `GD-MI-cce2a254` reported +$9 in DB but broker filled at TP (+$910)

---

## What Happened

Trade `GD-MI-cce2a254` (Gold Micro, June 10):
- SHORT 30 oz @ $4,204.66
- Original SL $4,223.90, BE moved to $4,204.36 after 50% TP hit
- Original TP $4,174.30
- **Broker actual fill: TP at $4,174.30** (per JustMarkets and MT5 history)
- **DB recorded: exit_price=$4,204.36, exit_reason=SL, pnl_usd=$9.00**

Reality: +$910 win. DB: +$9 win. **$901 missing in our equity tracking.**

The money is in the wallet (broker is correct). The bug is purely in how we record/calculate the close.

---

## Root Cause

`backend-micro/scanner/live_engine.py:check_open_positions()` lines 309–354.

When a trade disappears from `open_orders.json` (i.e., broker closed it via SL or TP), the code can't ask the DWX EA "what price did you fill at?" because the EA only writes OPEN orders. So the function falls back to a **heuristic** based on `_price_extremes` (high/low seen during the trade's life):

```python
if trade["side"] == "SHORT":
    sl_reached = extremes["high"] >= sl_price  # broker SL trigger price
    tp_reached = extremes["low"] <= tp_price   # broker TP trigger price

    if tp_reached and not sl_reached:
        fill_price = tp_price        # TP win
        realized_pl = (entry - tp) * units
    else:
        fill_price = sl_price        # ← falls here if both reached
        realized_pl = (entry - sl) * units
```

For our trade:
- `extremes["high"] = $4,208.04` (peak adverse)
- `extremes["low"]  = $4,174.26` (peak favorable)
- BE-moved SL = $4,204.36
- TP = $4,174.30

Evaluation:
- `sl_reached = 4208.04 >= 4204.36 = TRUE` (high crossed BE-stop level)
- `tp_reached = 4174.26 <= 4174.30 = TRUE` (low crossed TP by $0.04!)
- Both TRUE → falls to `else` branch → records as SL fill at BE stop

**The problem**: the `extremes` only tells us if the SL or TP level was *touched* during the trade's life. It doesn't tell us **which one was touched FIRST**. In our case:
- Price hit $4,208.04 at server 10:09 (before BE armed at 10:44)
- Price hit $4,174.26 at server 11:00 (after BE armed)
- Broker filled at TP at server ~11:04+

But the heuristic doesn't know the time order. It sees both touched → defaults to SL → records wrong outcome.

---

## Why "Both Reached" Happens with BE

This bug is uniquely triggered by the BE mechanism:
1. Original SL (e.g., $4,223.90) was never threatened — high only got to $4,208.04
2. After 50% TP, SL moved to $4,204.36
3. Earlier high $4,208.04 is now ABOVE the new SL level
4. So `sl_reached` becomes TRUE retroactively because we compare against the CURRENT (BE-moved) sl_price, not the original

If BE never armed (original SL stayed at $4,223.90), `sl_reached` would be FALSE and the bug wouldn't trigger.

So this bug **only fires when BE was armed AND price subsequently went both directions enough to touch both BE-stop and TP**. That's a fairly common pattern in trending-after-reversal trades.

---

## Why Did Broker Fill at TP, Not BE Stop?

The DB stores the SL value. When BE armed, the code called `modify_stop_loss()` to update the broker-side SL to $4,204.36. The broker accepted that SL. The BE-stop level was below the price at that moment ($4,189.45) so the order was valid.

After BE armed, price went DOWN to $4,174.26 — below TP $4,174.30. **The broker filled the limit-TP order first** because it was reached before the price came back up to the BE stop. So the broker recorded a TP exit, but our `_price_extremes` retroactively shows the high also crossed the BE stop level (from earlier in the trade).

The broker has the TIME-AWARE truth. We're using a TIME-OBLIVIOUS proxy.

---

## Impact

**Per-trade**: Wrong exit_price, wrong exit_reason, wrong pnl_usd.

**Cumulative effects**:
1. `gd_dd_state.equity` drifts from broker reality (today: off by ~$901 already)
2. `consecutive_losses` counter wrong (reports a 30-cent "win" when it was actually a $910 win — minor)
3. Daily recon reports wrong total P&L
4. Future strategy comparison vs backtest is skewed
5. User can't trust dashboard P&L numbers

**This is a phantom fill bug — same class as the May 22 phantom fill bug that killed the previous system.** We've been here before. Critical to fix correctly.

---

## Fix Options

### Option A (quick, partial): Use timing to disambiguate

When both `sl_reached` and `tp_reached` are TRUE, check the timestamps. If we tracked WHEN each extreme was hit, we'd know which one came first in time. The trade should be attributed to whichever extreme was touched first relative to the BE-arm event.

Cost: requires `_price_extremes` to track both (price, timestamp) pairs.

### Option B (correct, requires EA change): Track closed trades in DWX

Extend `mql5/DWX_Server.mq5` to write a `closed_orders.json` (or append to a rolling log) when MT5's `OnTradeTransaction` fires for a position close. Include actual fill price, fill time, profit. Then `get_trade_details()` can read that file for closed trades, eliminating the heuristic entirely.

Cost: ~30 lines of MQL5. This is the proper fix.

### Option C (workaround): Use MT5 account_info delta

`account_info.json` contains balance & equity. We can read it before and after the close to derive realized P&L. This is fragile when multiple trades close in the same poll cycle, but works for single-trade scenarios. Not recommended as primary fix.

### Option D (best): Combine A + B

Use B (closed trades file) as the authoritative source. Keep A (timing-aware heuristic) as the fallback if the file isn't yet populated for some reason. Update both files in tandem so we have defense in depth.

---

## Recommended Plan

**Phase 4-A** (immediate, today):
1. **Manually correct the GD-MI-cce2a254 DB row** to actual broker outcome
2. **Update Oil Micro's `check_open_positions()`** with the same fix (it has the identical bug)
3. **Document for future investigation**

**Phase 4-B** (this week):
1. Add `OnTradeTransaction` handler to `mql5/DWX_Server.mq5` that writes `closed_orders.json`
2. Update `get_trade_details()` in `mt5_executor.py` to read closed history
3. Update `check_open_positions()` to use real fill price when available
4. Add regression test that simulates "both extremes reached" + "real broker fill at TP"

---

## SQL Cleanup for the Wrong Trade

```sql
-- Correct GD-MI-cce2a254 to reflect actual broker outcome
UPDATE gd_trades
SET
  exit_price = 4174.30,
  pnl_usd = 910.80,
  pnl_gbp = 910.80,
  exit_reason = 'TP'
WHERE trade_ref = 'GD-MI-cce2a254';

-- Update DD state to match
UPDATE gd_dd_state
SET
  equity = equity + (910.80 - 9.00),  -- add the missing $901.80
  peak_equity = GREATEST(peak_equity, equity + (910.80 - 9.00)),
  consecutive_losses = 0,  -- it was a win
  updated_at = NOW()
WHERE id = 3;  -- Gold Micro

-- Audit trail
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp)
VALUES (
  'GD-MI-cce2a254',
  'micro_alpha_sweep',
  'PNL_CORRECTED',
  4174.30,
  '{"reason": "phantom_fill_bug_be_ambiguity", "wrong_pnl": 9.00, "correct_pnl": 910.80, "see": "docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md"}'::jsonb,
  NOW()
);
```

---

## Connection to Earlier Phantom Fill Bug

The May 22 phantom-fill bug invalidated 21 years of backtest. That bug was about **fill timing within bars** in the backtest fill model. This new bug is about **fill attribution after broker close** in live execution. Different code paths, same lesson:

> **Never reason about broker outcomes from heuristics. Always use the broker's authoritative record.**

The DWX EA is currently a one-way bridge (we send orders, EA writes prices/balance/open positions). It needs to also write **closed trades** for full reconciliation. Until that's added, every closed trade is at risk of misattribution under specific conditions.
